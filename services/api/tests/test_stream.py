"""Contract tests for the safe finite workflow SSE snapshot."""

from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import UTC, datetime
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
from api.routers.stream import _GET_RUN, _GET_STEPS, router


ORG_A_ID = UUID("00000000-0000-4000-8000-0000000000a1")
ORG_B_ID = UUID("00000000-0000-4000-8000-0000000000b2")
PERSON_ID = UUID("00000000-0000-4000-8000-0000000000a3")
RUN_A_ID = UUID("00000000-0000-4000-8000-0000000000a4")
RUN_B_ID = UUID("00000000-0000-4000-8000-0000000000b4")
TOKEN = "Bearer stream-test-token"


class _Mappings:
    def __init__(self, rows: list[dict[str, object]]) -> None:
        self._rows = rows

    def all(self) -> list[dict[str, object]]:
        return self._rows

    def one_or_none(self) -> dict[str, object] | None:
        if len(self._rows) > 1:
            raise AssertionError("stream query returned more than one run")
        return self._rows[0] if self._rows else None


class _Result:
    def __init__(self, rows: list[dict[str, object]]) -> None:
        self._mappings = _Mappings(rows)

    def mappings(self) -> _Mappings:
        return self._mappings


class _StreamSession:
    def __init__(self) -> None:
        self.executions: list[tuple[str, dict[str, object]]] = []
        now = datetime(2026, 9, 26, 14, 0, tzinfo=UTC)
        self._run = {
            "id": RUN_A_ID,
            "org_id": ORG_A_ID,
            "status": "running",
            "occurred_at": now,
        }
        self._steps = [
            {
                "sequence_number": 1,
                "component_name": "screen_safety",
                "status": "completed",
                "occurred_at": now,
                "error_code": None,
            },
            {
                "sequence_number": 2,
                "component_name": "normalize_intake",
                "status": "running",
                "occurred_at": now,
                "error_code": None,
            },
        ]

    async def execute(
        self, statement: object, parameters: Mapping[str, object]
    ) -> _Result:
        query = str(statement)
        bound = dict(parameters)
        self.executions.append((query, bound))
        is_org_a_run = bound["org_id"] == str(ORG_A_ID) and bound["run_id"] == str(
            RUN_A_ID
        )
        if "FROM public.agent_runs AS run" in query:
            return _Result([self._run] if is_org_a_run else [])
        if "FROM public.agent_steps AS step" in query:
            return _Result(self._steps if is_org_a_run else [])
        raise AssertionError(f"Unexpected stream SQL: {query}")


async def _scope(
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


@pytest.fixture
def stream_session() -> _StreamSession:
    return _StreamSession()


@pytest.fixture
def stream_app(stream_session: _StreamSession) -> FastAPI:
    app = FastAPI()
    install_problem_handlers(app)
    app.include_router(router)

    async def session() -> AsyncSession:
        return cast(AsyncSession, stream_session)

    app.dependency_overrides[get_request_tenant_scope] = _scope
    app.dependency_overrides[get_request_session] = session
    return app


@pytest.mark.asyncio
async def test_stream_first_emits_the_complete_hollow_timeline(
    stream_app: FastAPI, stream_session: _StreamSession
) -> None:
    transport = httpx.ASGITransport(app=stream_app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(
            f"/v1/runs/{RUN_A_ID}/stream", headers={"Authorization": TOKEN}
        )

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert response.headers["cache-control"] == "no-cache"
    events = [event for event in response.text.split("\n\n") if event]
    assert events[0].startswith(f"id: timeline:{RUN_A_ID}\nevent: timeline.ready\n")
    timeline = json.loads(events[0].split("data: ", 1)[1])
    assert [item["stage"] for item in timeline["steps"]] == [
        "safety",
        "intake",
        "context",
        "diagnosis",
        "dispatch",
        "policy_audit",
        "decision",
    ]
    assert {item["status"] for item in timeline["steps"]} == {"pending"}
    assert "event: step.finished" in events[1]
    assert '"stage":"safety"' in events[1]
    assert "event: step.started" in events[2]
    assert "input_digest" not in response.text
    assert "output_digest" not in response.text
    assert str(ORG_A_ID) not in response.text

    assert [
        str(_GET_RUN) in query or str(_GET_STEPS) in query
        for query, _ in stream_session.executions
    ] == [
        True,
        True,
    ]
    for query, parameters in stream_session.executions:
        assert "org_id = CAST(:org_id AS uuid)" in query
        assert parameters["org_id"] == str(ORG_A_ID)


@pytest.mark.asyncio
async def test_stream_hides_a_foreign_run_as_not_found(
    stream_app: FastAPI, stream_session: _StreamSession
) -> None:
    transport = httpx.ASGITransport(app=stream_app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(
            f"/v1/runs/{RUN_B_ID}/stream", headers={"Authorization": TOKEN}
        )

    assert response.status_code == 404
    assert response.json()["type"] == "urn:resident-os:problem:not-found"
    assert len(stream_session.executions) == 1
    query, parameters = stream_session.executions[0]
    assert "run.org_id = CAST(:org_id AS uuid)" in query
    assert parameters == {"org_id": str(ORG_A_ID), "run_id": str(RUN_B_ID)}
