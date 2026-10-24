"""Run-specific processing authorizes before opening worker capabilities."""

from __future__ import annotations

from types import SimpleNamespace
from typing import cast
from unittest.mock import AsyncMock, Mock
from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from api.deps.tenancy import TenantScope
from api.routers import processing
from api import worker


def scope() -> TenantScope:
    person = uuid4()
    return TenantScope(
        org_id=uuid4(), person_id=person, subject_id=person, role="resident"
    )


def session(*, authorized: bool) -> AsyncSession:
    rows = SimpleNamespace(
        mappings=lambda: SimpleNamespace(
            one_or_none=lambda: {"id": uuid4()} if authorized else None
        )
    )
    return cast(AsyncSession, SimpleNamespace(execute=AsyncMock(return_value=rows)))


@pytest.mark.asyncio
async def test_foreign_run_never_opens_worker_database(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    create = Mock()
    monkeypatch.setattr(processing, "create_database_engine", create)
    with pytest.raises(HTTPException) as error:
        await processing.process_run(uuid4(), scope(), session(authorized=False))
    assert error.value.status_code == 404
    create.assert_not_called()


@pytest.mark.asyncio
async def test_missing_worker_config_fails_safely_after_owner_check(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("WORKER_DATABASE_URL", raising=False)
    create = Mock()
    monkeypatch.setattr(processing, "create_database_engine", create)
    with pytest.raises(HTTPException) as error:
        await processing.process_run(uuid4(), scope(), session(authorized=True))
    assert error.value.status_code == 503
    create.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize("processed", [True, False])
async def test_processing_awaits_exact_owned_run_and_disposes_engine(
    monkeypatch: pytest.MonkeyPatch, processed: bool
) -> None:
    monkeypatch.setenv("WORKER_DATABASE_URL", "postgresql+asyncpg://test-placeholder")
    engine = SimpleNamespace(dispose=AsyncMock())
    factory = object()
    monkeypatch.setattr(processing, "create_database_engine", lambda value: engine)
    monkeypatch.setattr(processing, "create_session_factory", lambda value: factory)
    execute = AsyncMock(return_value=processed)
    monkeypatch.setattr(processing, "process_one", execute)
    run, resident = uuid4(), scope()
    request_session = session(authorized=True)
    result = await processing.process_run(run, resident, request_session)
    assert result.run_id == run and result.processed is processed
    execute.assert_awaited_once_with(
        factory, resident.org_id, processing.execute_maintenance, run_id=run
    )
    engine.dispose.assert_awaited_once()
    arguments = request_session.execute.call_args.args[1]  # type: ignore[attr-defined]
    assert arguments["person_id"] == str(resident.person_id)
    assert arguments["is_staff"] is False


@pytest.mark.asyncio
async def test_processing_failure_redacts_exception_and_disposes_engine(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("WORKER_DATABASE_URL", "postgresql+asyncpg://test-placeholder")
    engine = SimpleNamespace(dispose=AsyncMock())
    monkeypatch.setattr(processing, "create_database_engine", lambda value: engine)
    monkeypatch.setattr(processing, "create_session_factory", lambda value: object())
    monkeypatch.setattr(
        processing,
        "process_one",
        AsyncMock(side_effect=RuntimeError("private database details")),
    )
    with pytest.raises(HTTPException) as error:
        await processing.process_run(uuid4(), scope(), session(authorized=True))
    assert error.value.status_code == 503
    assert "private" not in str(error.value.detail)
    engine.dispose.assert_awaited_once()


@pytest.mark.asyncio
async def test_selected_run_filters_claim_and_exhaustion_queries() -> None:
    result = SimpleNamespace(mappings=lambda: SimpleNamespace(one_or_none=lambda: None))
    execute = AsyncMock(return_value=result)
    database = cast(AsyncSession, SimpleNamespace(execute=execute))
    org, run = uuid4(), uuid4()
    assert await worker.claim_job(database, org, run_id=run) is None
    assert execute.await_count == 2
    for call in execute.await_args_list:
        query, parameters = call.args
        assert "CAST(:requested_run_id AS uuid) IS NULL" in str(query)
        assert "= CAST(:requested_run_id AS uuid)" in str(query)
        assert parameters["requested_run_id"] == str(run)
        assert parameters["org_id"] == str(org)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "secret,authorization",
    [
        ("", None),
        ("test-cron-placeholder", None),
        ("test-cron-placeholder", "Bearer wrong-placeholder"),
    ],
)
async def test_recovery_requires_exact_configured_secret_before_worker_access(
    monkeypatch: pytest.MonkeyPatch, secret: str, authorization: str | None
) -> None:
    from starlette.requests import Request

    monkeypatch.setenv("CRON_SECRET", secret)
    create = Mock()
    monkeypatch.setattr(processing, "create_database_engine", create)
    headers = [(b"authorization", authorization.encode())] if authorization else []
    request = Request({"type": "http", "headers": headers})
    with pytest.raises(HTTPException) as error:
        await processing.recover_run(request)
    assert error.value.status_code == 401
    create.assert_not_called()


@pytest.mark.asyncio
async def test_recovery_runs_exactly_one_job_for_allowlisted_org(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from starlette.requests import Request

    org = uuid4()
    monkeypatch.setenv("CRON_SECRET", "test-cron-placeholder")
    monkeypatch.setenv("WORKER_DATABASE_URL", "postgresql+asyncpg://test-placeholder")
    monkeypatch.setenv("WORKER_ORG_ID", str(org))
    engine = SimpleNamespace(dispose=AsyncMock())
    factory = object()
    monkeypatch.setattr(processing, "create_database_engine", lambda value: engine)
    monkeypatch.setattr(processing, "create_session_factory", lambda value: factory)
    execute = AsyncMock(return_value=True)
    monkeypatch.setattr(processing, "process_one", execute)
    result = await processing.recover_run(
        Request(
            {
                "type": "http",
                "headers": [(b"authorization", b"Bearer test-cron-placeholder")],
            }
        )
    )
    assert result.processed
    execute.assert_awaited_once_with(factory, org, processing.execute_maintenance)
    engine.dispose.assert_awaited_once()


@pytest.mark.asyncio
async def test_recovery_missing_allowlisted_org_fails_safely(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from starlette.requests import Request

    monkeypatch.setenv("CRON_SECRET", "test-cron-placeholder")
    monkeypatch.setenv("WORKER_DATABASE_URL", "postgresql+asyncpg://test-placeholder")
    monkeypatch.delenv("WORKER_ORG_ID", raising=False)
    with pytest.raises(HTTPException) as error:
        await processing.recover_run(
            Request(
                {
                    "type": "http",
                    "headers": [(b"authorization", b"Bearer test-cron-placeholder")],
                }
            )
        )
    assert error.value.status_code == 503


@pytest.mark.asyncio
async def test_recovery_route_is_registered_and_denies_anonymous_calls_without_database(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import httpx
    from api.main import create_app

    monkeypatch.setenv("CRON_SECRET", "test-cron-placeholder")
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=create_app()), base_url="http://test"
    ) as client:
        response = await client.get("/internal/worker/recover")
    assert response.status_code == 401
