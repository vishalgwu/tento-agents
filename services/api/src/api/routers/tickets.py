"""Tenant-scoped, cursor-paginated ticket read endpoints."""

from __future__ import annotations

import base64
import binascii
import json
from collections.abc import Mapping
from datetime import datetime
from typing import Annotated, Any
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from brain.agents.safety import screen_deterministic_safety

from api.deps.tenancy import (
    TenantScope,
    get_request_session,
    get_request_tenant_scope,
)


router = APIRouter(prefix="/v1/tickets", tags=["tickets"])

_DEFAULT_PAGE_SIZE = 50
_MAX_PAGE_SIZE = 100

# Each statement carries an organisation predicate in addition to the RLS
# transaction context.  Do not replace either control with the other.
_TICKET_COLUMNS = """
    ticket.id,
    ticket.ticket_number,
    ticket.property_id,
    ticket.building_id,
    ticket.unit_id,
    ticket.status::text AS status,
    ticket.priority::text AS priority,
    ticket.category,
    ticket.symptom_summary,
    ticket.submitted_at,
    ticket.closed_at,
    ticket.created_at,
    (SELECT jsonb_build_object(
        'run_id', run.id, 'status', run.status::text,
        'result', run.result_json, 'error_code', run.last_error_code
    ) FROM public.agent_runs AS run
      WHERE run.org_id = ticket.org_id AND run.ticket_id = ticket.id
      ORDER BY run.created_at DESC, run.id DESC LIMIT 1) AS latest_run
"""
_LIST_TICKETS = text(
    f"""
    SELECT {_TICKET_COLUMNS}
    FROM public.tickets AS ticket
    WHERE ticket.org_id = CAST(:org_id AS uuid)
      AND (:is_staff OR ticket.reporter_person_id = CAST(:person_id AS uuid))
      AND (
          CAST(:cursor_created_at AS timestamptz) IS NULL
          OR (ticket.created_at, ticket.id) < (
              CAST(:cursor_created_at AS timestamptz),
              CAST(:cursor_id AS uuid)
          )
      )
    ORDER BY ticket.created_at DESC, ticket.id DESC
    LIMIT :limit
    """
)
_GET_TICKET = text(
    f"""
    SELECT {_TICKET_COLUMNS}
    FROM public.tickets AS ticket
    WHERE ticket.org_id = CAST(:org_id AS uuid)
      AND (:is_staff OR ticket.reporter_person_id = CAST(:person_id AS uuid))
      AND ticket.id = CAST(:ticket_id AS uuid)
    """
)


class RunSnapshot(BaseModel):
    run_id: UUID
    status: str
    result: dict[str, Any] | None = None
    error_code: str | None = None


class TicketSummary(BaseModel):
    """Safe ticket fields for a collection response.

    Reporter text and access instructions are intentionally absent.  They are
    PII-bearing intake data and will only be exposed through a specifically
    authorised workflow when that contract exists.
    """

    model_config = ConfigDict(extra="forbid")

    id: UUID
    ticket_number: int
    property_id: UUID
    building_id: UUID
    unit_id: UUID
    status: str
    priority: str | None
    category: str | None
    symptom_summary: str | None
    submitted_at: datetime
    closed_at: datetime | None
    created_at: datetime
    latest_run: RunSnapshot | None = None


class TicketDetail(TicketSummary):
    """Current detail shape; deliberately no more sensitive than a summary."""


class TicketListResponse(BaseModel):
    """A stable page of tickets ordered by the opaque continuation cursor."""

    items: list[TicketSummary]
    next_cursor: str | None


class _TicketCursor(BaseModel):
    """The decoded keyset boundary; never exposed directly to callers."""

    model_config = ConfigDict(extra="forbid")

    created_at: datetime
    id: UUID


class SubmitTicketRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    description: str = Field(min_length=1, max_length=20_000)
    tenancy_id: UUID | None = None
    access_permission: bool | None = None
    pets_present: bool | None = None

    @field_validator("description")
    @classmethod
    def nonblank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("description must not be blank")
        return value


class TicketSubmission(BaseModel):
    ticket_id: UUID
    ticket_number: int
    run_id: UUID
    status: str = "queued"
    emergency: bool = False
    message: str | None = None


_ACTIVE_TENANCIES = text("""
    SELECT tenancy.id, tenancy.property_id, tenancy.unit_id, unit.building_id,
           property.name AS property_name, unit.unit_number AS unit_name
    FROM public.tenancies AS tenancy
    JOIN public.units AS unit ON unit.org_id = tenancy.org_id AND unit.id = tenancy.unit_id
    JOIN public.properties AS property ON property.org_id = tenancy.org_id AND property.id = tenancy.property_id
    WHERE tenancy.org_id = CAST(:org_id AS uuid)
      AND tenancy.person_id = CAST(:person_id AS uuid)
      AND tenancy.status = 'active' AND tenancy.starts_on <= CURRENT_DATE
      AND (tenancy.ends_on IS NULL OR tenancy.ends_on >= CURRENT_DATE)
      AND (CAST(:tenancy_id AS uuid) IS NULL OR tenancy.id = CAST(:tenancy_id AS uuid))
    ORDER BY tenancy.id
""")


@router.post("", response_model=TicketSubmission, status_code=201)
async def submit_ticket(
    body: SubmitTicketRequest,
    scope: Annotated[TenantScope, Depends(get_request_tenant_scope)],
    session: Annotated[AsyncSession, Depends(get_request_session)],
) -> TicketSubmission:
    """Atomically save one resident ticket and a durable worker job."""
    if scope.role != "resident":
        raise HTTPException(403, "Resident tenancy required")
    found = await session.execute(
        _ACTIVE_TENANCIES,
        {
            "org_id": str(scope.org_id),
            "person_id": str(scope.person_id),
            "tenancy_id": str(body.tenancy_id) if body.tenancy_id else None,
        },
    )
    tenancies = list(found.mappings().all())
    if not tenancies:
        raise HTTPException(403, "No active tenancy is available")
    if len(tenancies) > 1:
        raise HTTPException(409, "Select a tenancy before submitting")
    tenancy = tenancies[0]
    ticket_id, run_id = uuid4(), uuid4()
    emergency = bool(screen_deterministic_safety(body.description))
    inserted = await session.execute(
        text("""
        INSERT INTO public.tickets (id, org_id, property_id, building_id, unit_id,
            reporter_person_id, reported_text, access_permission, pets_present, priority, status)
        VALUES (CAST(:ticket_id AS uuid), CAST(:org_id AS uuid), CAST(:property_id AS uuid),
            CAST(:building_id AS uuid), CAST(:unit_id AS uuid), CAST(:person_id AS uuid),
            :description, :access_permission, :pets_present, CAST(:priority AS priority), CAST(:ticket_status AS ticket_status))
        RETURNING ticket_number
    """),
        {
            "ticket_id": str(ticket_id),
            "org_id": str(scope.org_id),
            "person_id": str(scope.person_id),
            "property_id": str(tenancy["property_id"]),
            "building_id": str(tenancy["building_id"]),
            "unit_id": str(tenancy["unit_id"]),
            "description": body.description,
            "priority": "p0" if emergency else None,
            "ticket_status": "escalated" if emergency else "submitted",
            "access_permission": body.access_permission,
            "pets_present": body.pets_present,
        },
    )
    ticket_number = int(inserted.scalar_one())
    await session.execute(
        text("""
        INSERT INTO public.agent_runs (id, org_id, ticket_id, workflow_version, trigger_kind)
        VALUES (CAST(:run_id AS uuid), CAST(:org_id AS uuid), CAST(:ticket_id AS uuid), 'maintenance-v1', 'resident_submission')
    """),
        {
            "run_id": str(run_id),
            "org_id": str(scope.org_id),
            "ticket_id": str(ticket_id),
        },
    )
    return TicketSubmission(
        ticket_id=ticket_id,
        ticket_number=ticket_number,
        run_id=run_id,
        emergency=emergency,
        message="This may be an emergency. Move to safety and contact local emergency services or your property emergency maintenance number immediately. This service has not contacted anyone."
        if emergency
        else None,
    )


@router.get("", response_model=TicketListResponse)
async def list_tickets(
    scope: Annotated[TenantScope, Depends(get_request_tenant_scope)],
    session: Annotated[AsyncSession, Depends(get_request_session)],
    cursor: Annotated[str | None, Query(max_length=512)] = None,
    limit: Annotated[int, Query(ge=1, le=_MAX_PAGE_SIZE)] = _DEFAULT_PAGE_SIZE,
) -> TicketListResponse:
    """List only tickets visible to the verified organisation, newest first."""

    boundary = _decode_cursor(cursor) if cursor is not None else None
    result = await session.execute(
        _LIST_TICKETS,
        {
            "org_id": str(scope.org_id),
            "person_id": str(scope.person_id),
            "is_staff": scope.role != "resident",
            "cursor_created_at": (
                boundary.created_at.isoformat() if boundary is not None else None
            ),
            "cursor_id": str(boundary.id) if boundary is not None else None,
            # Fetch one extra row so the continuation signal never relies on
            # a count query and stays correct when rows are deleted concurrently.
            "limit": limit + 1,
        },
    )
    rows = list(result.mappings().all())
    page = [TicketSummary.model_validate(dict(row)) for row in rows[:limit]]
    next_cursor = _encode_cursor(page[-1]) if len(rows) > limit and page else None
    return TicketListResponse(items=page, next_cursor=next_cursor)


@router.get("/{ticket_id}", response_model=TicketDetail)
async def get_ticket(
    ticket_id: UUID,
    scope: Annotated[TenantScope, Depends(get_request_tenant_scope)],
    session: Annotated[AsyncSession, Depends(get_request_session)],
) -> TicketDetail:
    """Return a ticket only when it belongs to the caller's organisation."""

    result = await session.execute(
        _GET_TICKET,
        {
            "org_id": str(scope.org_id),
            "person_id": str(scope.person_id),
            "is_staff": scope.role != "resident",
            "ticket_id": str(ticket_id),
        },
    )
    row = result.mappings().one_or_none()
    if row is None:
        # A foreign ticket is indistinguishable from a missing ticket.
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    return TicketDetail.model_validate(dict(row))


def _encode_cursor(ticket: TicketSummary) -> str:
    """Encode the exact composite ordering key without leaking a query shape."""

    payload = json.dumps(
        {"created_at": ticket.created_at.isoformat(), "id": str(ticket.id)},
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return base64.urlsafe_b64encode(payload).decode("ascii").rstrip("=")


def _decode_cursor(value: str) -> _TicketCursor:
    """Validate an opaque cursor without exposing parser failures to a client."""

    try:
        padding = "=" * (-len(value) % 4)
        decoded = base64.b64decode(
            (value + padding).encode("ascii"), altchars=b"-_", validate=True
        )
        payload: Any = json.loads(decoded)
        if not isinstance(payload, Mapping) or set(payload) != {"created_at", "id"}:
            raise ValueError("Cursor has an unexpected shape")
        cursor = _TicketCursor.model_validate(payload)
        if cursor.created_at.tzinfo is None:
            raise ValueError("Cursor timestamp must have a timezone")
        return cursor
    except (
        ValueError,
        TypeError,
        UnicodeDecodeError,
        binascii.Error,
        json.JSONDecodeError,
    ):
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY) from None
