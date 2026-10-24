"""Durable tenant-scoped maintenance worker: python -m api.worker.

Jobs are claimed in a short transaction. A bounded execution transaction writes
agent receipts and the result together only while its fencing lease still owns
the job. Process loss leaves a lease that another worker can reclaim.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any
from uuid import UUID, uuid4, uuid5

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from api.db import (
    TenantContext,
    create_database_engine,
    create_session_factory,
    tenant_session,
)

_LOG = logging.getLogger("resident_os.worker")
MAX_ATTEMPTS = 3
LEASE_SECONDS = 300
EXECUTION_SECONDS = 180

_EXHAUSTED = text("""
    UPDATE public.agent_runs
    SET status = 'failed', completed_at = now(), lease_id = NULL,
        lease_expires_at = NULL, last_error_code = 'attempts_exhausted'
    WHERE org_id = CAST(:org_id AS uuid) AND attempt_count >= :max_attempts
      AND (CAST(:requested_run_id AS uuid) IS NULL OR id = CAST(:requested_run_id AS uuid))
      AND (status = 'queued' OR (status = 'running' AND lease_expires_at <= now()))
""")
_CLAIM = text("""
    WITH candidate AS (
        SELECT run.id FROM public.agent_runs AS run
        WHERE run.org_id = CAST(:org_id AS uuid)
          AND (CAST(:requested_run_id AS uuid) IS NULL OR run.id = CAST(:requested_run_id AS uuid))
          AND run.attempt_count < :max_attempts
          AND (run.status = 'queued' OR (run.status = 'running' AND run.lease_expires_at <= now()))
        ORDER BY run.created_at, run.id
        FOR UPDATE SKIP LOCKED LIMIT 1
    )
    UPDATE public.agent_runs AS run
    SET status = 'running', started_at = COALESCE(run.started_at, now()),
        lease_id = CAST(:lease_id AS uuid),
        lease_expires_at = now() + (:lease_seconds * interval '1 second'),
        attempt_count = run.attempt_count + 1, last_error_code = NULL
    FROM candidate, public.tickets AS ticket
    WHERE run.org_id = CAST(:org_id AS uuid) AND run.id = candidate.id
      AND ticket.org_id = run.org_id AND ticket.id = run.ticket_id
    RETURNING run.id AS run_id, run.ticket_id, ticket.reporter_person_id AS person_id
""")
_FINISH = text("""
    UPDATE public.agent_runs
    SET status = CAST(:status AS agent_run_status), result_json = CAST(:result AS jsonb),
        completed_at = now(), lease_id = NULL, lease_expires_at = NULL, last_error_code = NULL
    WHERE org_id = CAST(:org_id AS uuid) AND id = CAST(:run_id AS uuid)
      AND lease_id = CAST(:lease_id AS uuid) AND status = 'running' AND lease_expires_at > now()
    RETURNING id
""")
_FAIL = text("""
    UPDATE public.agent_runs
    SET status = CASE WHEN attempt_count >= :max_attempts THEN 'failed'::agent_run_status ELSE 'queued'::agent_run_status END,
        completed_at = CASE WHEN attempt_count >= :max_attempts THEN now() ELSE NULL END,
        last_error_code = :error_code, lease_id = NULL, lease_expires_at = NULL
    WHERE org_id = CAST(:org_id AS uuid) AND id = CAST(:run_id AS uuid)
      AND lease_id = CAST(:lease_id AS uuid) AND status = 'running'
""")


@dataclass(frozen=True)
class Job:
    run_id: UUID
    ticket_id: UUID
    person_id: UUID | None
    lease_id: UUID


class LeaseLost(RuntimeError):
    """An obsolete worker must roll back every result and receipt."""


Workflow = Callable[..., Awaitable[dict[str, Any]]]


async def claim_job(
    session: AsyncSession, org_id: UUID, *, run_id: UUID | None = None
) -> Job | None:
    lease_id = uuid4()
    parameters = {
        "org_id": str(org_id),
        "lease_id": str(lease_id),
        "max_attempts": MAX_ATTEMPTS,
        "lease_seconds": LEASE_SECONDS,
        "requested_run_id": str(run_id) if run_id is not None else None,
    }
    await session.execute(_EXHAUSTED, parameters)
    claimed = await session.execute(_CLAIM, parameters)
    row = claimed.mappings().one_or_none()
    if row is None:
        return None
    return Job(
        run_id=row["run_id"],
        ticket_id=row["ticket_id"],
        person_id=row["person_id"],
        lease_id=lease_id,
    )


async def execute_job(
    session: AsyncSession, org_id: UUID, job: Job, workflow: Workflow
) -> None:
    async with asyncio.timeout(EXECUTION_SECONDS):
        result = await workflow(
            session=session,
            org_id=org_id,
            person_id=job.person_id,
            ticket_id=job.ticket_id,
            run_id=job.run_id,
        )
    if result.get("status") not in {"completed", "abstained", "emergency"}:
        raise ValueError("workflow returned an invalid terminal status")
    finished = await session.execute(
        _FINISH,
        {
            "org_id": str(org_id),
            "run_id": str(job.run_id),
            "lease_id": str(job.lease_id),
            "status": "degraded" if result["status"] == "abstained" else "completed",
            "result": json.dumps(result),
        },
    )
    if finished.scalar_one_or_none() is None:
        raise LeaseLost("maintenance lease no longer belongs to this worker")
    if result["status"] == "completed":
        from brain.agents.dispatch import DispatchFulfillment, DispatchPlan
        from brain.graph.state import DecisionMode, DecisionProposal

        plan = DispatchPlan.model_validate_json(json.dumps(result.get("plan")))
        decision = DecisionProposal.model_validate_json(
            json.dumps(result.get("decision"))
        )
        if (
            plan.proposal.fulfillment is not DispatchFulfillment.IN_HOUSE
            or decision.mode is not DecisionMode.AUTO
        ):
            raise ValueError("only validated in-house work orders are supported")
        order_id = uuid5(job.run_id, "internal-work-order")
        await session.execute(
            text("""
            INSERT INTO public.work_orders (id,org_id,ticket_id,trade,status,decision_id)
            VALUES (CAST(:id AS uuid),CAST(:org_id AS uuid),CAST(:ticket_id AS uuid),CAST(:trade AS trade),'proposed',CAST(:decision_id AS uuid))
            ON CONFLICT(id) DO NOTHING
        """),
            {
                "id": str(order_id),
                "org_id": str(org_id),
                "ticket_id": str(job.ticket_id),
                "trade": plan.proposal.trade.value,
                "decision_id": str(uuid5(job.run_id, "decision")),
            },
        )
        result["work_order"] = {
            "id": str(order_id),
            "status": "proposed",
            "trade": plan.proposal.trade.value,
            "scope_summary": plan.proposal.scope_summary,
        }
        await session.execute(
            text("""
            UPDATE public.agent_runs SET result_json=CAST(:result AS jsonb)
            WHERE org_id=CAST(:org_id AS uuid) AND id=CAST(:run_id AS uuid)
        """),
            {
                "org_id": str(org_id),
                "run_id": str(job.run_id),
                "result": json.dumps(result),
            },
        )
    facts = result.get("facts") or {}
    if not isinstance(facts, dict):
        raise ValueError("workflow facts must be a JSON object")
    await session.execute(
        text("""
        UPDATE public.tickets
        SET status = CAST(:status AS ticket_status),
            priority = CASE WHEN :emergency THEN 'p0'::priority ELSE priority END,
            category = :category, symptom_summary = :symptom_summary, acknowledged_at = COALESCE(acknowledged_at, now())
        WHERE org_id = CAST(:org_id AS uuid) AND id = CAST(:ticket_id AS uuid)
    """),
        {
            "org_id": str(org_id),
            "ticket_id": str(job.ticket_id),
            "status": "blocked"
            if result["status"] == "abstained"
            else "escalated"
            if result["status"] == "emergency"
            else "ready",
            "emergency": result["status"] == "emergency",
            "category": facts.get("category"),
            "symptom_summary": facts.get("symptom_summary"),
        },
    )


async def process_one(
    session_factory: async_sessionmaker[AsyncSession],
    org_id: UUID,
    workflow: Workflow,
    *,
    run_id: UUID | None = None,
) -> bool:
    context = TenantContext(org_id=org_id, role="operations_admin")
    async with tenant_session(session_factory, context) as session:
        job = await claim_job(session, org_id, run_id=run_id)
    if job is None:
        return False
    try:
        async with tenant_session(session_factory, context) as session:
            await execute_job(session, org_id, job, workflow)
    except asyncio.CancelledError:
        # Leave the committed lease for recovery; never hide shutdown cancellation.
        raise
    except LeaseLost:
        _LOG.warning("job_lease_lost org=%s run=%s", org_id, job.run_id)
    except Exception as error:
        code = (
            "execution_timeout"
            if isinstance(error, TimeoutError)
            else "execution_failed"
        )
        async with tenant_session(session_factory, context) as session:
            await session.execute(
                _FAIL,
                {
                    "org_id": str(org_id),
                    "run_id": str(job.run_id),
                    "lease_id": str(job.lease_id),
                    "max_attempts": MAX_ATTEMPTS,
                    "error_code": code,
                },
            )
        _LOG.warning("job_failed org=%s run=%s code=%s", org_id, job.run_id, code)
    return True


async def main() -> None:
    from brain.production import execute_maintenance

    org_id = UUID(os.environ["WORKER_ORG_ID"])

    engine = create_database_engine(os.environ["WORKER_DATABASE_URL"])

    factory = create_session_factory(engine)
    try:
        while True:
            if not await process_one(factory, org_id, execute_maintenance):
                await asyncio.sleep(2)
    finally:
        await engine.dispose()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(main())
