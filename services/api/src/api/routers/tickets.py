"""Tenant-scoped, cursor-paginated ticket read endpoints."""

from __future__ import annotations

import base64
import binascii
import json
from collections.abc import Mapping
from datetime import datetime
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

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
    ticket.created_at
"""
_LIST_TICKETS = text(
    f"""
    SELECT {_TICKET_COLUMNS}
    FROM public.tickets AS ticket
    WHERE ticket.org_id = CAST(:org_id AS uuid)
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
      AND ticket.id = CAST(:ticket_id AS uuid)
    """
)


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
        {"org_id": str(scope.org_id), "ticket_id": str(ticket_id)},
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
