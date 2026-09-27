"""Approval queue ordering, immutable action receipts, and role boundaries."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from typing import Annotated, cast
from uuid import UUID

import httpx
import pytest
from fastapi import FastAPI, Header, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from api.deps.tenancy import (
    TenantScope,
    get_request_session,
    get_request_tenant_scope,
)
from api.middleware.errors import install_problem_handlers
from api.routers.approvals import (
    _APPROVAL_QUEUE,
    _INSERT_ACTION,
    _INSERT_REASSIGNED_PENDING,
    _LOAD_ACTIONABLE_APPROVAL,
    router,
)


ORG_A_ID = UUID("00000000-0000-4000-8000-0000000000a1")
ORG_B_ID = UUID("00000000-0000-4000-8000-0000000000b2")
PERSON_ID = UUID("00000000-0000-4000-8000-0000000000a3")
APPROVAL_A_ID = UUID("00000000-0000-4000-8000-0000000000a4")
APPROVAL_B_ID = UUID("00000000-0000-4000-8000-0000000000b4")
DECISION_ID = UUID("00000000-0000-4000-8000-0000000000a5")
RUN_ID = UUID("00000000-0000-4000-8000-0000000000a6")
CHAIN_ID = UUID("00000000-0000-4000-8000-0000000000a7")
TOKEN = "Bearer approval-test-token"


class _Mappings:
    def __init__(self, rows: list[dict[str, object]]) -> None:
        self._rows = rows

    def all(self) -> list[dict[str, object]]:
        return self._rows

    def one_or_none(self) -> dict[str, object] | None:
        if len(self._rows) > 1:
            raise AssertionError("expected no more than one approval row")
        return self._rows[0] if self._rows else None


class _Result:
    def __init__(self, rows: list[dict[str, object]]) -> None:
        self._mappings = _Mappings(rows)

    def mappings(self) -> _Mappings:
        return self._mappings


class _ApprovalSession:
    def __init__(self) -> None:
        self.executions: list[tuple[str, dict[str, object]]] = []
        now = datetime(2026, 9, 26, 14, 0, tzinfo=UTC)
        self._source = {
            "id": APPROVAL_A_ID,
            "org_id": ORG_A_ID,
            "decision_id": DECISION_ID,
            "requested_by_run_id": RUN_ID,
            "approval_chain_id": CHAIN_ID,
            "required_role": "property_manager",
            "action_scope": "dispatch:ticket:scope:action:scope",
            "requested_at": now,
            "expires_at": now + timedelta(hours=2),
        }
        self._queue = [
            self._queue_row(APPROVAL_A_ID, now + timedelta(hours=1), "p0", 0),
            self._queue_row(
                UUID("00000000-0000-4000-8000-0000000000a8"),
                now + timedelta(hours=5),
                "p1",
                1,
            ),
        ]

    @staticmethod
    def _queue_row(
        approval_id: UUID, expiry: datetime, priority: str, priority_rank: int
    ) -> dict[str, object]:
        now = datetime(2026, 9, 26, 14, 0, tzinfo=UTC)
        return {
            "approval_id": approval_id,
            "decision_id": DECISION_ID,
            "required_role": "property_manager",
            "requested_at": now,
            "sla_expires_at": expiry,
            "priority": priority,
            "proposed_trade": "plumbing",
            "proposed_responsible_party": "owner",
            "estimated_cost_cents": 25_000,
            "citation_verified": True,
            "ticket_id": UUID("00000000-0000-4000-8000-0000000000a9"),
            "ticket_number": 17,
            "symptom_summary": "Kitchen leak.",
            "priority_rank": priority_rank,
        }

    async def execute(
        self, statement: object, parameters: Mapping[str, object]
    ) -> _Result:
        query = str(statement)
        bound = dict(parameters)
        self.executions.append((query, bound))
        if query == str(_APPROVAL_QUEUE):
            return _Result(self._queue if bound["org_id"] == str(ORG_A_ID) else [])
        if query == str(_LOAD_ACTIONABLE_APPROVAL):
            is_visible = bound["org_id"] == str(ORG_A_ID) and bound[
                "approval_id"
            ] == str(APPROVAL_A_ID)
            return _Result([self._source] if is_visible else [])
        if query == str(_INSERT_ACTION):
            return _Result(
                [
                    {
                        "id": UUID(str(bound["id"])),
                        "approval_chain_id": CHAIN_ID,
                        "status": bound["status"],
                        "action": bound["action"],
                        "rejection_reason": bound["rejection_reason"],
                        "acted_at": datetime(2026, 9, 26, 14, 1, tzinfo=UTC),
                    }
                ]
            )
        if query == str(_INSERT_REASSIGNED_PENDING):
            return _Result([{"id": UUID(str(bound["id"]))}])
        raise AssertionError(f"Unexpected approval SQL: {query}")


async def _manager_scope(
    authorization: Annotated[str | None, Header()] = None,
) -> TenantScope:
    if authorization != TOKEN:
        raise HTTPException(status_code=401)
    return TenantScope(
        org_id=ORG_A_ID,
        person_id=PERSON_ID,
        role="property_manager",
        subject_id=PERSON_ID,
    )


async def _resident_scope(
    authorization: Annotated[str | None, Header()] = None,
) -> TenantScope:
    if authorization != TOKEN:
        raise HTTPException(status_code=401)
    return TenantScope(
        org_id=ORG_A_ID,
        person_id=PERSON_ID,
        role="resident",
        subject_id=PERSON_ID,
    )


@pytest.fixture
def approval_session() -> _ApprovalSession:
    return _ApprovalSession()


@pytest.fixture
def approval_app(approval_session: _ApprovalSession) -> FastAPI:
    app = FastAPI()
    install_problem_handlers(app)
    app.include_router(router)

    async def session() -> AsyncSession:
        return cast(AsyncSession, approval_session)

    app.dependency_overrides[get_request_tenant_scope] = _manager_scope
    app.dependency_overrides[get_request_session] = session
    return app


@pytest.mark.asyncio
async def test_queue_orders_by_approval_sla_not_arrival_time(
    approval_app: FastAPI, approval_session: _ApprovalSession
) -> None:
    transport = httpx.ASGITransport(app=approval_app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/v1/approvals", headers={"Authorization": TOKEN})

    assert response.status_code == 200
    assert [item["approval_id"] for item in response.json()["items"]] == [
        str(APPROVAL_A_ID),
        "00000000-0000-4000-8000-0000000000a8",
    ]
    query, parameters = approval_session.executions[0]
    assert "ORDER BY approval.expires_at ASC" in query
    assert query.index("ORDER BY approval.expires_at ASC") < query.index(
        "approval.requested_at ASC"
    )
    assert "approval.org_id = CAST(:org_id AS uuid)" in query
    assert parameters["org_id"] == str(ORG_A_ID)


@pytest.mark.asyncio
async def test_reject_records_one_of_the_five_evaluation_labels(
    approval_app: FastAPI, approval_session: _ApprovalSession
) -> None:
    transport = httpx.ASGITransport(app=approval_app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            f"/v1/approvals/{APPROVAL_A_ID}/reject",
            headers={"Authorization": TOKEN},
            json={"reason": "incorrect_priority"},
        )

    assert response.status_code == 201
    assert response.json()["status"] == "rejected"
    assert response.json()["action"] == "reject"
    assert response.json()["rejection_reason"] == "incorrect_priority"
    insert_query, parameters = approval_session.executions[-1]
    assert insert_query == str(_INSERT_ACTION)
    assert parameters["supersedes_approval_id"] == str(APPROVAL_A_ID)
    assert parameters["rejection_reason"] == "incorrect_priority"
    assert "UPDATE public.approvals" not in insert_query


@pytest.mark.asyncio
async def test_reassign_creates_a_new_pending_request_without_returning_a_token(
    approval_app: FastAPI, approval_session: _ApprovalSession
) -> None:
    transport = httpx.ASGITransport(app=approval_app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            f"/v1/approvals/{APPROVAL_A_ID}/reassign",
            headers={"Authorization": TOKEN},
            json={"required_role": "asset_owner"},
        )

    assert response.status_code == 201
    assert response.json()["action"] == "reassign"
    assert response.json()["replacement_approval_id"]
    replacement_query, parameters = approval_session.executions[-1]
    assert replacement_query == str(_INSERT_REASSIGNED_PENDING)
    assert parameters["approval_chain_id"] == str(CHAIN_ID)
    assert parameters["required_role"] == "asset_owner"
    assert len(str(parameters["approval_token_hash"])) == 64
    assert "approval_token" not in response.text


@pytest.mark.asyncio
async def test_reject_does_not_accept_the_database_only_other_reason(
    approval_app: FastAPI, approval_session: _ApprovalSession
) -> None:
    transport = httpx.ASGITransport(app=approval_app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            f"/v1/approvals/{APPROVAL_A_ID}/reject",
            headers={"Authorization": TOKEN},
            json={"reason": "other"},
        )

    assert response.status_code == 422
    assert response.json()["type"] == "urn:resident-os:problem:invalid-request"
    assert not approval_session.executions


@pytest.mark.asyncio
async def test_foreign_approval_is_not_found_and_residents_cannot_act(
    approval_app: FastAPI, approval_session: _ApprovalSession
) -> None:
    transport = httpx.ASGITransport(app=approval_app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        foreign = await client.post(
            f"/v1/approvals/{APPROVAL_B_ID}/approve",
            headers={"Authorization": TOKEN},
        )

    assert foreign.status_code == 404
    query, parameters = approval_session.executions[0]
    assert "approval.org_id = CAST(:org_id AS uuid)" in query
    assert parameters["org_id"] == str(ORG_A_ID)

    approval_app.dependency_overrides[get_request_tenant_scope] = _resident_scope
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        denied = await client.get("/v1/approvals", headers={"Authorization": TOKEN})

    assert denied.status_code == 403
    assert denied.json()["type"] == "urn:resident-os:problem:forbidden"
