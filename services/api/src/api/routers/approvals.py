"""Tenant-safe, append-only human approval queue and decisions."""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
import secrets
from collections.abc import Mapping
from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from api.deps.tenancy import (
    TenantScope,
    get_request_session,
    get_request_tenant_scope,
)
from api.middleware.errors import FORBIDDEN, ProblemDetailsException


router = APIRouter(prefix="/v1/approvals", tags=["approvals"])

_DEFAULT_PAGE_SIZE = 50
_MAX_PAGE_SIZE = 100
_APPROVAL_ACTOR_ROLES = frozenset(
    {"property_manager", "asset_owner", "operations_admin"}
)

# The stable sort is SLA deadline first, then operational priority. It never
# uses request arrival time as the primary ordering key.
_APPROVAL_QUEUE = text(
    """
    SELECT approval.id AS approval_id,
           approval.decision_id,
           approval.required_role::text AS required_role,
           approval.requested_at,
           approval.expires_at AS sla_expires_at,
           decision.priority::text AS priority,
           decision.proposed_trade::text AS proposed_trade,
           decision.proposed_responsible_party::text AS proposed_responsible_party,
           decision.estimated_cost_cents,
           decision.citation_verified,
           ticket.id AS ticket_id,
           ticket.ticket_number,
           ticket.symptom_summary,
           CASE decision.priority
               WHEN 'p0' THEN 0
               WHEN 'p1' THEN 1
               WHEN 'p2' THEN 2
               ELSE 3
           END AS priority_rank
    FROM public.approvals AS approval
    INNER JOIN public.decisions AS decision
      ON decision.org_id = approval.org_id
     AND decision.id = approval.decision_id
    INNER JOIN public.tickets AS ticket
      ON ticket.org_id = approval.org_id
     AND ticket.id = decision.ticket_id
    WHERE approval.org_id = CAST(:org_id AS uuid)
      AND approval.status = 'pending'
      AND approval.expires_at > CURRENT_TIMESTAMP
      AND NOT EXISTS (
          SELECT 1
          FROM public.approvals AS successor
          WHERE successor.org_id = approval.org_id
            AND successor.supersedes_approval_id = approval.id
      )
      AND (
          :is_operations_admin
          OR approval.required_role::text = :role
      )
      AND (
          CAST(:cursor_expires_at AS timestamptz) IS NULL
          OR (
              approval.expires_at,
              CASE decision.priority
                  WHEN 'p0' THEN 0
                  WHEN 'p1' THEN 1
                  WHEN 'p2' THEN 2
                  ELSE 3
              END,
              approval.requested_at,
              approval.id
          ) > (
              CAST(:cursor_expires_at AS timestamptz),
              CAST(:cursor_priority_rank AS integer),
              CAST(:cursor_requested_at AS timestamptz),
              CAST(:cursor_id AS uuid)
          )
      )
    ORDER BY approval.expires_at ASC,
             priority_rank ASC,
             approval.requested_at ASC,
             approval.id ASC
    LIMIT :limit
    """
)
_LOAD_ACTIONABLE_APPROVAL = text(
    """
    SELECT approval.id,
           approval.org_id,
           approval.decision_id,
           approval.requested_by_run_id,
           approval.approval_chain_id,
           approval.required_role::text AS required_role,
           approval.action_scope,
           approval.requested_at,
           approval.expires_at
    FROM public.approvals AS approval
    WHERE approval.org_id = CAST(:org_id AS uuid)
      AND approval.id = CAST(:approval_id AS uuid)
      AND approval.status = 'pending'
      AND approval.expires_at > CURRENT_TIMESTAMP
      AND NOT EXISTS (
          SELECT 1
          FROM public.approvals AS successor
          WHERE successor.org_id = approval.org_id
            AND successor.supersedes_approval_id = approval.id
      )
    FOR UPDATE
    """
)
_INSERT_ACTION = text(
    """
    INSERT INTO public.approvals (
        id, org_id, decision_id, requested_by_run_id, approval_chain_id,
        supersedes_approval_id, required_role, status, action,
        rejection_reason, acted_by_person_id, action_scope, requested_at,
        acted_at, expires_at
    ) VALUES (
        CAST(:id AS uuid), CAST(:org_id AS uuid), CAST(:decision_id AS uuid),
        CAST(:requested_by_run_id AS uuid), CAST(:approval_chain_id AS uuid),
        CAST(:supersedes_approval_id AS uuid), CAST(:required_role AS app_role),
        CAST(:status AS approval_status), CAST(:action AS approval_action),
        CAST(:rejection_reason AS reject_reason), CAST(:acted_by_person_id AS uuid),
        :action_scope, CAST(:requested_at AS timestamptz), CURRENT_TIMESTAMP,
        CAST(:expires_at AS timestamptz)
    )
    RETURNING id, approval_chain_id, status::text AS status, action::text AS action,
              rejection_reason::text AS rejection_reason, acted_at
    """
)
_INSERT_REASSIGNED_PENDING = text(
    """
    INSERT INTO public.approvals (
        id, org_id, decision_id, requested_by_run_id, approval_chain_id,
        required_role, status, approval_token_hash, action_scope, requested_at,
        expires_at
    ) VALUES (
        CAST(:id AS uuid), CAST(:org_id AS uuid), CAST(:decision_id AS uuid),
        CAST(:requested_by_run_id AS uuid), CAST(:approval_chain_id AS uuid),
        CAST(:required_role AS app_role), 'pending', :approval_token_hash,
        :action_scope, CURRENT_TIMESTAMP, CAST(:expires_at AS timestamptz)
    )
    RETURNING id
    """
)


class ApprovalQueueItem(BaseModel):
    """Safe in-context manager view of one actionable proposal."""

    model_config = ConfigDict(extra="forbid")

    approval_id: UUID
    decision_id: UUID
    required_role: str
    requested_at: datetime
    sla_expires_at: datetime
    priority: str | None
    proposed_trade: str | None
    proposed_responsible_party: str
    estimated_cost_cents: int | None
    citation_verified: bool
    ticket_id: UUID
    ticket_number: int
    symptom_summary: str | None


class ApprovalQueueResponse(BaseModel):
    """A deadline-ordered page of approvals awaiting a permitted actor."""

    model_config = ConfigDict(extra="forbid")

    items: list[ApprovalQueueItem]
    next_cursor: str | None


class ApprovalActionReceipt(BaseModel):
    """Immutable audit receipt returned after a human decision."""

    model_config = ConfigDict(extra="forbid")

    id: UUID
    approval_chain_id: UUID
    status: str
    action: str
    rejection_reason: str | None
    acted_at: datetime
    replacement_approval_id: UUID | None = None


class RejectApprovalRequest(BaseModel):
    """Five structured human-feedback labels retained for evaluation."""

    model_config = ConfigDict(extra="forbid")

    reason: Literal[
        "insufficient_evidence",
        "incorrect_priority",
        "incorrect_routing",
        "cost_or_scope",
        "policy_conflict",
    ]


class ReassignApprovalRequest(BaseModel):
    """Move a pending decision to a different approver role in the same chain."""

    model_config = ConfigDict(extra="forbid")

    required_role: Literal["property_manager", "asset_owner"]


class _ApprovalCursor(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expires_at: datetime
    priority_rank: int
    requested_at: datetime
    id: UUID


@router.get("", response_model=ApprovalQueueResponse)
async def list_approvals(
    scope: Annotated[TenantScope, Depends(get_request_tenant_scope)],
    session: Annotated[AsyncSession, Depends(get_request_session)],
    cursor: Annotated[str | None, Query(max_length=512)] = None,
    limit: Annotated[int, Query(ge=1, le=_MAX_PAGE_SIZE)] = _DEFAULT_PAGE_SIZE,
) -> ApprovalQueueResponse:
    """List current approvals by expiring SLA window, never by arrival order."""

    _require_approval_actor(scope)
    boundary = _decode_cursor(cursor) if cursor is not None else None
    result = await session.execute(
        _APPROVAL_QUEUE,
        {
            "org_id": str(scope.org_id),
            "role": scope.role,
            "is_operations_admin": scope.role == "operations_admin",
            "cursor_expires_at": (
                boundary.expires_at.isoformat() if boundary is not None else None
            ),
            "cursor_priority_rank": (
                boundary.priority_rank if boundary is not None else None
            ),
            "cursor_requested_at": (
                boundary.requested_at.isoformat() if boundary is not None else None
            ),
            "cursor_id": str(boundary.id) if boundary is not None else None,
            "limit": limit + 1,
        },
    )
    rows = [dict(row) for row in result.mappings().all()]
    page = [
        ApprovalQueueItem.model_validate(
            {key: value for key, value in row.items() if key != "priority_rank"}
        )
        for row in rows[:limit]
    ]
    next_cursor = _encode_cursor(rows[limit - 1]) if len(rows) > limit else None
    return ApprovalQueueResponse(items=page, next_cursor=next_cursor)


@router.post(
    "/{approval_id}/approve", response_model=ApprovalActionReceipt, status_code=201
)
async def approve(
    approval_id: UUID,
    scope: Annotated[TenantScope, Depends(get_request_tenant_scope)],
    session: Annotated[AsyncSession, Depends(get_request_session)],
) -> ApprovalActionReceipt:
    """Append an approval receipt; no route updates or executes a decision."""

    source = await _load_actionable_approval(approval_id, scope, session)
    return await _append_action(source, scope, session, action="approve")


@router.post(
    "/{approval_id}/reject", response_model=ApprovalActionReceipt, status_code=201
)
async def reject(
    approval_id: UUID,
    body: RejectApprovalRequest,
    scope: Annotated[TenantScope, Depends(get_request_tenant_scope)],
    session: Annotated[AsyncSession, Depends(get_request_session)],
) -> ApprovalActionReceipt:
    """Append a rejection receipt with one evaluation-ready reason label."""

    source = await _load_actionable_approval(approval_id, scope, session)
    return await _append_action(
        source, scope, session, action="reject", rejection_reason=body.reason
    )


@router.post(
    "/{approval_id}/reassign", response_model=ApprovalActionReceipt, status_code=201
)
async def reassign(
    approval_id: UUID,
    body: ReassignApprovalRequest,
    scope: Annotated[TenantScope, Depends(get_request_tenant_scope)],
    session: Annotated[AsyncSession, Depends(get_request_session)],
) -> ApprovalActionReceipt:
    """Append reassignment proof and a new pending request in its audit chain."""

    source = await _load_actionable_approval(approval_id, scope, session)
    receipt = await _append_action(source, scope, session, action="reassign")
    replacement_id = uuid4()
    replacement = await session.execute(
        _INSERT_REASSIGNED_PENDING,
        {
            "id": str(replacement_id),
            "org_id": str(source["org_id"]),
            "decision_id": str(source["decision_id"]),
            "requested_by_run_id": str(source["requested_by_run_id"]),
            "approval_chain_id": str(source["approval_chain_id"]),
            "required_role": body.required_role,
            # Reassignment creates a distinct pending receipt. This route never
            # returns or activates an execution token; an absent later capability
            # broker therefore fails closed rather than enabling a side effect.
            "approval_token_hash": _new_token_hash(),
            "action_scope": str(source["action_scope"]),
            "expires_at": _timestamp_parameter(source["expires_at"]),
        },
    )
    replacement_row = replacement.mappings().one_or_none()
    if replacement_row is None:
        raise RuntimeError("approval reassignment did not create a pending receipt")
    return receipt.model_copy(
        update={"replacement_approval_id": UUID(str(replacement_row["id"]))}
    )


async def _load_actionable_approval(
    approval_id: UUID, scope: TenantScope, session: AsyncSession
) -> dict[str, object]:
    _require_approval_actor(scope)
    result = await session.execute(
        _LOAD_ACTIONABLE_APPROVAL,
        {"org_id": str(scope.org_id), "approval_id": str(approval_id)},
    )
    source = result.mappings().one_or_none()
    if source is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    source_dict = dict(source)
    required_role = str(source_dict["required_role"])
    if scope.role != "operations_admin" and scope.role != required_role:
        raise ProblemDetailsException(FORBIDDEN)
    return source_dict


async def _append_action(
    source: Mapping[str, object],
    scope: TenantScope,
    session: AsyncSession,
    *,
    action: Literal["approve", "reject", "reassign"],
    rejection_reason: str | None = None,
) -> ApprovalActionReceipt:
    """Insert a successor audit receipt using only server-loaded source fields."""

    receipt_id = uuid4()
    result = await session.execute(
        _INSERT_ACTION,
        {
            "id": str(receipt_id),
            "org_id": str(source["org_id"]),
            "decision_id": str(source["decision_id"]),
            "requested_by_run_id": str(source["requested_by_run_id"]),
            "approval_chain_id": str(source["approval_chain_id"]),
            "supersedes_approval_id": str(source["id"]),
            "required_role": str(source["required_role"]),
            "status": "rejected" if action == "reject" else "approved",
            "action": action,
            "rejection_reason": rejection_reason,
            "acted_by_person_id": str(scope.person_id),
            "action_scope": str(source["action_scope"]),
            "requested_at": _timestamp_parameter(source["requested_at"]),
            "expires_at": _timestamp_parameter(source["expires_at"]),
        },
    )
    row = result.mappings().one_or_none()
    if row is None:
        raise RuntimeError("approval action did not create a receipt")
    return ApprovalActionReceipt.model_validate(dict(row))


def _require_approval_actor(scope: TenantScope) -> None:
    if scope.role not in _APPROVAL_ACTOR_ROLES:
        raise ProblemDetailsException(FORBIDDEN)


def _new_token_hash() -> str:
    """Return only a one-way, server-generated approval token digest."""

    return hashlib.sha256(secrets.token_bytes(32)).hexdigest()


def _timestamp_parameter(value: object) -> str:
    if not isinstance(value, datetime):
        raise TypeError("approval timestamps must be datetimes")
    return value.isoformat()


def _integer(value: object) -> int:
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    raise TypeError("approval priority ranks must be integers")


def _encode_cursor(row: Mapping[str, object]) -> str:
    payload = json.dumps(
        {
            "expires_at": _timestamp_parameter(row["sla_expires_at"]),
            "priority_rank": _integer(row["priority_rank"]),
            "requested_at": _timestamp_parameter(row["requested_at"]),
            "id": str(row["approval_id"]),
        },
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return base64.urlsafe_b64encode(payload).decode("ascii").rstrip("=")


def _decode_cursor(value: str) -> _ApprovalCursor:
    try:
        padding = "=" * (-len(value) % 4)
        decoded = base64.b64decode(
            (value + padding).encode("ascii"), altchars=b"-_", validate=True
        )
        payload: object = json.loads(decoded)
        if not isinstance(payload, Mapping) or set(payload) != {
            "expires_at",
            "priority_rank",
            "requested_at",
            "id",
        }:
            raise ValueError("Cursor has an unexpected shape")
        cursor = _ApprovalCursor.model_validate(payload)
        if cursor.expires_at.tzinfo is None or cursor.requested_at.tzinfo is None:
            raise ValueError("Cursor timestamps must have a timezone")
        return cursor
    except (
        ValueError,
        TypeError,
        UnicodeDecodeError,
        binascii.Error,
        json.JSONDecodeError,
    ):
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY) from None
