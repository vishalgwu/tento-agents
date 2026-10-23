"""Submission binds locations to current tenancy and creates one durable job."""

from collections.abc import Mapping
from typing import Any, cast
from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from api.deps.tenancy import TenantScope
from api.routers.tickets import SubmitTicketRequest, submit_ticket, _ACTIVE_TENANCIES


class Result:
    def __init__(self, rows: list[dict[str, Any]] | None = None) -> None:
        self.rows = rows or []

    def mappings(self) -> "Result":
        return self

    def all(self) -> list[dict[str, Any]]:
        return self.rows

    def scalar_one(self) -> int:
        return 143


class Session:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self.rows = rows
        self.calls: list[tuple[str, dict[str, object]]] = []

    async def execute(self, statement: object, params: Mapping[str, object]) -> Result:
        self.calls.append((str(statement), dict(params)))
        return Result(self.rows if "FROM public.tenancies" in str(statement) else [])


def scope() -> TenantScope:
    person = uuid4()
    return TenantScope(
        org_id=uuid4(), person_id=person, subject_id=person, role="resident"
    )


def location() -> dict[str, Any]:
    return {
        "id": uuid4(),
        "property_id": uuid4(),
        "building_id": uuid4(),
        "unit_id": uuid4(),
    }


@pytest.mark.asyncio
async def test_submission_uses_only_authorized_location_and_enqueues_in_same_session() -> (
    None
):
    authorized = location()
    session, resident = Session([authorized]), scope()
    receipt = await submit_ticket(
        SubmitTicketRequest(
            description="Kitchen tap leaks", access_permission=False, pets_present=True
        ),
        resident,
        cast(AsyncSession, session),
    )
    assert receipt.ticket_number == 143 and receipt.status == "queued"
    assert len(session.calls) == 3
    _, query = session.calls[1]
    assert query["property_id"] == str(authorized["property_id"])
    assert query["person_id"] == str(resident.person_id)
    assert query["access_permission"] is False
    assert query["pets_present"] is True
    assert session.calls[2][1]["ticket_id"] == str(receipt.ticket_id)
    assert session.calls[2][1]["run_id"] == str(receipt.run_id)


@pytest.mark.asyncio
@pytest.mark.parametrize("count,expected", [(0, 403), (2, 409)])
async def test_ineligible_or_ambiguous_tenancy_never_creates_a_ticket(
    count: int, expected: int
) -> None:
    session = Session([location() for _ in range(count)])
    with pytest.raises(HTTPException) as error:
        await submit_ticket(
            SubmitTicketRequest(description="Leaky tap"),
            scope(),
            cast(AsyncSession, session),
        )
    assert error.value.status_code == expected
    assert len(session.calls) == 1


def test_tenancy_query_binds_identity_current_dates_and_optional_selection() -> None:
    query = str(_ACTIVE_TENANCIES)
    for fragment in (
        "tenancy.org_id = CAST(:org_id",
        "tenancy.person_id = CAST(:person_id",
        "tenancy.status = 'active'",
        "tenancy.starts_on <= CURRENT_DATE",
        "tenancy.ends_on >= CURRENT_DATE",
        "tenancy.id = CAST(:tenancy_id",
    ):
        assert fragment in query


@pytest.mark.asyncio
async def test_emergency_submission_returns_immediate_advice_and_saves_priority() -> (
    None
):
    session = Session([location()])
    receipt = await submit_ticket(
        SubmitTicketRequest(description="I smell gas in the apartment."),
        scope(),
        cast(AsyncSession, session),
    )
    assert receipt.emergency
    assert receipt.message is not None and "has not contacted anyone" in receipt.message
    assert session.calls[1][1]["priority"] == "p0"
    assert session.calls[1][1]["ticket_status"] == "escalated"
    assert receipt.status == "queued"
