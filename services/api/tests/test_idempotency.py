from __future__ import annotations

from unittest.mock import AsyncMock
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, Response
from fastapi.testclient import TestClient
import pytest
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint

from api.deps.tenancy import TenantScope
from api.middleware.errors import (
    ProblemDetailsMiddleware,
    ProblemType,
    install_problem_handlers,
)
from api.middleware.idempotency import (
    CachedResponse,
    ConflictingIdempotencyRecord,
    IdempotencyMiddleware,
    NewIdempotencyRecord,
    PostgresIdempotencyStore,
    ReplayedIdempotencyRecord,
    capture_response,
)


class _RequestStateMiddleware(BaseHTTPMiddleware):
    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        request.state.tenant_scope = TenantScope(
            org_id=uuid4(),
            person_id=uuid4(),
            subject_id=uuid4(),
            role="property_manager",
        )
        request.state.db_session = AsyncMock(spec=AsyncSession)
        return await call_next(request)


class _InMemoryStore(PostgresIdempotencyStore):
    def __init__(self) -> None:
        self.lookup: object = NewIdempotencyRecord(uuid4())
        self.completed: list[CachedResponse] = []
        self.released = 0

    async def begin(self, _session: AsyncSession, _request: object) -> object:
        return self.lookup

    async def complete(
        self,
        _session: AsyncSession,
        _request: object,
        _record_id: object,
        response: CachedResponse,
    ) -> None:
        self.completed.append(response)

    async def release(
        self, _session: AsyncSession, _request: object, _record_id: object
    ) -> None:
        self.released += 1


def _app(store: _InMemoryStore, call_count: list[int]) -> FastAPI:
    app = FastAPI()
    app.state.idempotency_store = store
    install_problem_handlers(app)
    app.add_middleware(IdempotencyMiddleware)
    app.add_middleware(_RequestStateMiddleware)
    app.add_middleware(ProblemDetailsMiddleware)

    @app.post("/v1/mutate")
    async def mutate() -> dict[str, int]:
        call_count[0] += 1
        return {"calls": call_count[0]}

    return app


def test_mutation_requires_exactly_one_idempotency_key() -> None:
    store = _InMemoryStore()
    calls = [0]
    response = TestClient(_app(store, calls)).post("/v1/mutate")

    assert response.status_code == 400
    assert response.json()["type"] == ProblemType.idempotency_key_required.uri
    assert calls == [0]


def test_completed_request_replays_cached_response_without_rerunning_route() -> None:
    store = _InMemoryStore()
    calls = [0]
    client = TestClient(_app(store, calls))

    first = client.post("/v1/mutate", headers={"Idempotency-Key": "retry-key"})
    assert first.status_code == 200
    assert calls == [1]
    assert len(store.completed) == 1

    store.lookup = ReplayedIdempotencyRecord(store.completed[0])
    replay = client.post("/v1/mutate", headers={"Idempotency-Key": "retry-key"})

    assert replay.status_code == 200
    assert replay.json() == {"calls": 1}
    assert replay.headers["Idempotency-Replayed"] == "true"
    assert calls == [1]


def test_key_reused_for_different_request_returns_stable_conflict() -> None:
    store = _InMemoryStore()
    store.lookup = ConflictingIdempotencyRecord()

    response = TestClient(_app(store, [0])).post(
        "/v1/mutate",
        headers={"Idempotency-Key": "retry-key"},
    )

    assert response.status_code == 409
    assert response.json()["type"] == ProblemType.idempotency_key_reused.uri


def test_server_error_releases_the_idempotency_reservation() -> None:
    store = _InMemoryStore()
    app = _app(store, [0])

    @app.post("/v1/failing-mutate")
    async def failing_mutate() -> Response:
        return Response(status_code=500)

    response = TestClient(app).post(
        "/v1/failing-mutate",
        headers={"Idempotency-Key": "retry-key"},
    )

    assert response.status_code == 500
    assert store.completed == []
    assert store.released == 1


@pytest.mark.asyncio
async def test_capture_response_preserves_safe_body_and_drops_cookie() -> None:
    response, cached = await capture_response(
        JSONResponse({"ticket_number": 42}, headers={"Set-Cookie": "session=secret"})
    )

    assert cached.status_code == 200
    assert cached.body == b'{"ticket_number":42}'
    assert "set-cookie" not in {key.lower() for key in cached.headers}
    assert response.body == cached.body
