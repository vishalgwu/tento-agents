"""Cross-tenant invariants for every registered versioned resource route.

The matrix is intentionally coupled to ``create_app``: adding a ``/v1`` route
without adding a corresponding isolation case fails CI.  The fake session
models the database's organisation boundary while each test also asserts the
explicit SQL predicate and bound organisation parameter that RLS backs up.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Annotated, cast
from uuid import UUID

import httpx
import pytest
from fastapi import FastAPI, Header, HTTPException
from fastapi.routing import APIRoute
from sqlalchemy.ext.asyncio import AsyncSession

from api.deps.tenancy import (
    TenantScope,
    get_request_session,
    get_request_tenant_scope,
)
from api.main import create_app
from api.middleware.errors import install_problem_handlers
from api.routers.tickets import _GET_TICKET, _LIST_TICKETS, router as tickets_router


ORG_A_ID = UUID("00000000-0000-4000-8000-0000000000a1")
ORG_B_ID = UUID("00000000-0000-4000-8000-0000000000b2")
ORG_A_PERSON_ID = UUID("00000000-0000-4000-8000-0000000000a3")
ORG_A_TICKET_NEW = UUID("00000000-0000-4000-8000-0000000000a4")
ORG_A_TICKET_OLD = UUID("00000000-0000-4000-8000-0000000000a5")
ORG_B_TICKET = UUID("00000000-0000-4000-8000-0000000000b3")
ORG_A_TOKEN = "Bearer test-token-scoped-to-org-a"


@dataclass(frozen=True, slots=True)
class _RouteIsolationCase:
    method: str
    route_template: str
    request_path: str
    assertion: str


_ROUTE_ISOLATION_CASES = (
    _RouteIsolationCase(
        method="GET",
        route_template="/v1/tickets",
        request_path="/v1/tickets?limit=100",
        assertion="collection",
    ),
    _RouteIsolationCase(
        method="GET",
        route_template="/v1/tickets/{ticket_id}",
        request_path=f"/v1/tickets/{ORG_B_TICKET}",
        assertion="foreign-detail",
    ),
)


class _FakeMappings:
    def __init__(self, rows: list[dict[str, object]]) -> None:
        self._rows = rows

    def all(self) -> list[dict[str, object]]:
        return self._rows

    def one_or_none(self) -> dict[str, object] | None:
        if not self._rows:
            return None
        if len(self._rows) > 1:
            raise AssertionError("The ticket detail query returned more than one row")
        return self._rows[0]


class _FakeResult:
    def __init__(self, rows: list[dict[str, object]]) -> None:
        self._mappings = _FakeMappings(rows)

    def mappings(self) -> _FakeMappings:
        return self._mappings


class _FakeTicketSession:
    """Minimal query recorder with the same tenant boundary as the test data."""

    def __init__(self, rows: list[dict[str, object]]) -> None:
        self._rows = rows
        self.executions: list[tuple[str, dict[str, object]]] = []

    async def execute(
        self, statement: object, parameters: Mapping[str, object]
    ) -> _FakeResult:
        query = str(statement)
        bound = dict(parameters)
        self.executions.append((query, bound))
        if "ORDER BY ticket.created_at DESC, ticket.id DESC" in query:
            return _FakeResult(self._list_rows(bound))
        return _FakeResult(self._detail_rows(bound))

    def _list_rows(self, parameters: Mapping[str, object]) -> list[dict[str, object]]:
        org_id = UUID(str(parameters["org_id"]))
        rows = [row for row in self._rows if row["org_id"] == org_id]
        cursor_created_at = parameters["cursor_created_at"]
        if cursor_created_at is not None:
            cursor_key = (
                datetime.fromisoformat(str(cursor_created_at)),
                UUID(str(parameters["cursor_id"])).int,
            )
            rows = [
                row
                for row in rows
                if (cast(datetime, row["created_at"]), UUID(str(row["id"])).int)
                < cursor_key
            ]
        rows.sort(
            key=lambda row: (
                cast(datetime, row["created_at"]),
                UUID(str(row["id"])).int,
            ),
            reverse=True,
        )
        return [self._public_row(row) for row in rows[: cast(int, parameters["limit"])]]

    def _detail_rows(self, parameters: Mapping[str, object]) -> list[dict[str, object]]:
        org_id = UUID(str(parameters["org_id"]))
        ticket_id = UUID(str(parameters["ticket_id"]))
        return [
            self._public_row(row)
            for row in self._rows
            if row["org_id"] == org_id and row["id"] == ticket_id
        ]

    @staticmethod
    def _public_row(row: Mapping[str, object]) -> dict[str, object]:
        return {key: value for key, value in row.items() if key != "org_id"}


def _ticket_rows() -> list[dict[str, object]]:
    """Two Org-A rows and a plausibly positioned Org-B row for isolation tests."""

    return [
        _ticket_row(
            org_id=ORG_A_ID,
            ticket_id=ORG_A_TICKET_NEW,
            ticket_number=101,
            created_at=datetime(2026, 2, 15, 9, 30, tzinfo=UTC),
        ),
        _ticket_row(
            org_id=ORG_B_ID,
            ticket_id=ORG_B_TICKET,
            ticket_number=201,
            created_at=datetime(2026, 2, 10, 12, 0, tzinfo=UTC),
        ),
        _ticket_row(
            org_id=ORG_A_ID,
            ticket_id=ORG_A_TICKET_OLD,
            ticket_number=100,
            created_at=datetime(2026, 1, 15, 9, 30, tzinfo=UTC),
        ),
    ]


def _ticket_row(
    *, org_id: UUID, ticket_id: UUID, ticket_number: int, created_at: datetime
) -> dict[str, object]:
    return {
        "id": ticket_id,
        "org_id": org_id,
        "ticket_number": ticket_number,
        "property_id": UUID("00000000-0000-4000-8000-000000000010"),
        "building_id": UUID("00000000-0000-4000-8000-000000000011"),
        "unit_id": UUID("00000000-0000-4000-8000-000000000012"),
        "status": "submitted",
        "priority": "medium",
        "category": "plumbing",
        "symptom_summary": "Kitchen sink drains slowly.",
        "submitted_at": created_at,
        "closed_at": None,
        "created_at": created_at,
    }


async def _org_a_scope(
    authorization: Annotated[str | None, Header()] = None,
) -> TenantScope:
    """A verified-token test double whose only permitted org is Org A."""

    if authorization != ORG_A_TOKEN:
        raise HTTPException(status_code=401)
    return TenantScope(
        org_id=ORG_A_ID,
        person_id=ORG_A_PERSON_ID,
        role="property_manager",
        subject_id=ORG_A_PERSON_ID,
    )


@pytest.fixture
def ticket_session() -> _FakeTicketSession:
    return _FakeTicketSession(_ticket_rows())


@pytest.fixture
def ticket_app(ticket_session: _FakeTicketSession) -> FastAPI:
    app = FastAPI()
    install_problem_handlers(app)
    app.include_router(tickets_router)

    async def request_session() -> AsyncSession:
        return cast(AsyncSession, ticket_session)

    app.dependency_overrides[get_request_tenant_scope] = _org_a_scope
    app.dependency_overrides[get_request_session] = request_session
    return app


def test_tenant_matrix_covers_every_registered_versioned_resource_route() -> None:
    """New public routes fail closed in CI until their isolation case is added.

    ``/healthz`` is intentionally excluded: it is an unauthenticated operational
    readiness route and does not address tenant resources. Every ``/v1`` route
    does, and must appear in this matrix.
    """

    registered_routes = {
        (method, route.path)
        for route in create_app().routes
        if isinstance(route, APIRoute) and route.path.startswith("/v1/")
        for method in route.methods
    }
    covered_routes = {
        (case.method, case.route_template) for case in _ROUTE_ISOLATION_CASES
    }

    assert registered_routes == covered_routes


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "case",
    _ROUTE_ISOLATION_CASES,
    ids=lambda case: f"{case.method}-{case.route_template}",
)
async def test_org_a_cannot_obtain_org_b_data_from_any_registered_route(
    case: _RouteIsolationCase,
    ticket_app: FastAPI,
    ticket_session: _FakeTicketSession,
) -> None:
    """An Org-A token never obtains an Org-B ticket, regardless of route form."""

    transport = httpx.ASGITransport(app=ticket_app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.request(
            case.method,
            case.request_path,
            headers={"Authorization": ORG_A_TOKEN},
        )

    if case.assertion == "collection":
        assert response.status_code == 200
        returned_ids = {item["id"] for item in response.json()["items"]}
        assert str(ORG_B_TICKET) not in returned_ids
    else:
        assert response.status_code == 404
        assert response.json()["type"] == "urn:resident-os:problem:not-found"

    assert ticket_session.executions
    for query, parameters in ticket_session.executions:
        assert "ticket.org_id = CAST(:org_id AS uuid)" in query
        assert parameters["org_id"] == str(ORG_A_ID)


@pytest.mark.asyncio
async def test_ticket_list_uses_an_opaque_composite_cursor_without_offset(
    ticket_app: FastAPI,
    ticket_session: _FakeTicketSession,
) -> None:
    """The continuation key is `(created_at, id)`, not a mutable row offset."""

    transport = httpx.ASGITransport(app=ticket_app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        first = await client.get(
            "/v1/tickets?limit=1", headers={"Authorization": ORG_A_TOKEN}
        )
        second = await client.get(
            "/v1/tickets",
            params={"limit": 1, "cursor": first.json()["next_cursor"]},
            headers={"Authorization": ORG_A_TOKEN},
        )

    assert first.status_code == 200
    assert first.json()["items"][0]["id"] == str(ORG_A_TICKET_NEW)
    assert first.json()["next_cursor"]
    assert second.status_code == 200
    assert second.json()["items"][0]["id"] == str(ORG_A_TICKET_OLD)
    assert all("OFFSET" not in query.upper() for query, _ in ticket_session.executions)
    assert "(ticket.created_at, ticket.id)" in str(_LIST_TICKETS)


@pytest.mark.asyncio
async def test_ticket_cursor_parse_failure_is_a_safe_problem_response(
    ticket_app: FastAPI,
    ticket_session: _FakeTicketSession,
) -> None:
    transport = httpx.ASGITransport(app=ticket_app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(
            "/v1/tickets?cursor=not-a-valid-cursor",
            headers={"Authorization": ORG_A_TOKEN},
        )

    assert response.status_code == 422
    assert response.headers["content-type"].startswith("application/problem+json")
    assert response.json()["type"] == "urn:resident-os:problem:invalid-request"
    assert not ticket_session.executions


def test_ticket_queries_always_bind_the_explicit_organisation_predicate() -> None:
    """Keep the application-side tenant boundary visible during code review."""

    for query in (_LIST_TICKETS, _GET_TICKET):
        assert "ticket.org_id = CAST(:org_id AS uuid)" in str(query)
