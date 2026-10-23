"""Lease fencing, exhaustion, durable claims and cancellation boundaries."""

import asyncio
from collections.abc import Mapping
from typing import Any, cast
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from api import worker


class Result:
    def __init__(
        self, row: dict[str, Any] | None = None, scalar: object = None
    ) -> None:
        self.row, self.scalar = row, scalar

    def mappings(self) -> "Result":
        return self

    def one_or_none(self) -> dict[str, Any] | None:
        return self.row

    def scalar_one_or_none(self) -> object:
        return self.scalar


class Session:
    def __init__(self, *, claim: bool = True, owns_lease: bool = True) -> None:
        self.claim, self.owns_lease = claim, owns_lease
        self.calls: list[tuple[str, dict[str, object]]] = []

    async def execute(self, statement: object, params: Mapping[str, object]) -> Result:
        query = str(statement)
        self.calls.append((query, dict(params)))
        if "WITH candidate" in query:
            return Result(
                {"run_id": uuid4(), "ticket_id": uuid4(), "person_id": uuid4()}
                if self.claim
                else None
            )
        return Result(scalar=uuid4() if self.owns_lease else None)


@pytest.mark.asyncio
async def test_claim_is_locked_tenant_scoped_and_reclaims_expired_work() -> None:
    session, org = Session(), uuid4()
    job = await worker.claim_job(cast(AsyncSession, session), org)
    assert job is not None
    assert "FOR UPDATE SKIP LOCKED" in session.calls[1][0]
    assert "lease_expires_at <= now()" in session.calls[1][0]
    assert "attempt_count < :max_attempts" in session.calls[1][0]
    assert all(params["org_id"] == str(org) for _, params in session.calls)
    assert "attempt_count >= :max_attempts" in session.calls[0][0]


@pytest.mark.asyncio
async def test_stale_worker_cannot_persist_ticket_result() -> None:
    session, org = Session(owns_lease=False), uuid4()
    job = worker.Job(uuid4(), uuid4(), uuid4(), uuid4())

    async def workflow(**kwargs: object) -> dict[str, Any]:
        return {
            "status": "completed",
            "summary": "Ready",
            "facts": {"category": "plumbing"},
        }

    with pytest.raises(worker.LeaseLost):
        await worker.execute_job(cast(AsyncSession, session), org, job, workflow)
    assert len(session.calls) == 1
    assert session.calls[0][1]["lease_id"] == str(job.lease_id)
    assert "lease_expires_at > now()" in session.calls[0][0]


@pytest.mark.asyncio
async def test_success_saves_public_result_and_normalized_ticket() -> None:
    session, org = Session(), uuid4()

    async def workflow(**kwargs: object) -> dict[str, Any]:
        return {
            "status": "abstained",
            "summary": "Evidence missing",
            "facts": {"category": "plumbing", "symptom_summary": "Leaky tap"},
        }

    await worker.execute_job(
        cast(AsyncSession, session),
        org,
        worker.Job(uuid4(), uuid4(), uuid4(), uuid4()),
        workflow,
    )
    assert session.calls[0][1]["status"] == "degraded"
    assert session.calls[1][1]["status"] == "blocked"
    assert session.calls[1][1]["category"] == "plumbing"


@pytest.mark.asyncio
async def test_timeout_cancels_work_before_result_update(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = Session()
    monkeypatch.setattr(worker, "EXECUTION_SECONDS", 0.001)

    async def workflow(**kwargs: object) -> dict[str, Any]:
        await asyncio.sleep(1)
        return {"status": "completed"}

    with pytest.raises(TimeoutError):
        await worker.execute_job(
            cast(AsyncSession, session),
            uuid4(),
            worker.Job(uuid4(), uuid4(), uuid4(), uuid4()),
            workflow,
        )
    assert not session.calls


@pytest.mark.asyncio
async def test_shutdown_preserves_committed_lease_for_restart(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from contextlib import asynccontextmanager
    from collections.abc import AsyncIterator
    from sqlalchemy.ext.asyncio import async_sessionmaker

    sessions: list[Session] = []
    events: list[str] = []

    @asynccontextmanager
    async def tenant_session(
        factory: object, context: object
    ) -> AsyncIterator[AsyncSession]:
        current = Session()
        sessions.append(current)
        try:
            yield cast(AsyncSession, current)
        except BaseException:
            events.append("rollback")
            raise
        else:
            events.append("commit")

    monkeypatch.setattr(worker, "tenant_session", tenant_session)

    async def workflow(**kwargs: object) -> dict[str, Any]:
        raise asyncio.CancelledError

    with pytest.raises(asyncio.CancelledError):
        await worker.process_one(
            cast(async_sessionmaker[AsyncSession], object()), uuid4(), workflow
        )
    assert events == ["commit", "rollback"]
    assert len(sessions) == 2
    assert not sessions[1].calls


@pytest.mark.asyncio
async def test_execution_failure_releases_only_owned_lease_with_safe_retry_code(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from contextlib import asynccontextmanager
    from collections.abc import AsyncIterator
    from sqlalchemy.ext.asyncio import async_sessionmaker

    sessions: list[Session] = []

    @asynccontextmanager
    async def tenant_session(
        factory: object, context: object
    ) -> AsyncIterator[AsyncSession]:
        current = Session()
        sessions.append(current)
        yield cast(AsyncSession, current)

    monkeypatch.setattr(worker, "tenant_session", tenant_session)

    async def workflow(**kwargs: object) -> dict[str, Any]:
        raise RuntimeError("provider private detail")

    assert await worker.process_one(
        cast(async_sessionmaker[AsyncSession], object()), uuid4(), workflow
    )
    assert len(sessions) == 3
    query, params = sessions[2].calls[0]
    assert params["error_code"] == "execution_failed"
    assert "provider private detail" not in str(params)
    assert "lease_id = CAST(:lease_id AS uuid)" in query
    assert "attempt_count >= :max_attempts" in query
