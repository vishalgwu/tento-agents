"""Safe server-sent snapshots of tenant-scoped workflow progress."""

from __future__ import annotations

import json
import re
from collections.abc import AsyncIterator, Mapping
from datetime import datetime
from typing import Annotated, cast
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from api.deps.tenancy import (
    TenantScope,
    get_request_session,
    get_request_tenant_scope,
)


router = APIRouter(prefix="/v1/runs", tags=["runs"])

_TIMELINE_STAGES = (
    "safety",
    "p0",
    "intake",
    "context",
    "diagnosis",
    "dispatch",
    "policy_audit",
    "decision",
)
_COMPONENT_STAGE_NAMES = {
    "screen_safety": "safety",
    "page_p0": "p0",
    "normalize_intake": "intake",
    "assemble_context": "context",
    "run_diagnosis": "diagnosis",
    "plan_dispatch": "dispatch",
    "audit_policy": "policy_audit",
    "apply_gate": "decision",
    "approval": "decision",
    "route_escalation": "decision",
}
_SAFE_FAILURE_CODE = re.compile(r"^[a-z][a-z0-9_]{0,79}$")

# The request middleware owns the RLS transaction.  Load the finite safe
# projection before returning StreamingResponse so that it never outlives that
# transaction or a connection-pool tenant context.
_GET_RUN = text(
    """
    SELECT run.id, run.status::text AS status,
           COALESCE(run.started_at, run.created_at) AS occurred_at
    FROM public.agent_runs AS run
    WHERE run.org_id = CAST(:org_id AS uuid)
      AND run.id = CAST(:run_id AS uuid)
    """
)
_GET_STEPS = text(
    """
    SELECT step.sequence_number, step.component_name, step.status::text AS status,
           COALESCE(step.completed_at, step.started_at, step.created_at) AS occurred_at,
           step.error_code
    FROM public.agent_steps AS step
    WHERE step.org_id = CAST(:org_id AS uuid)
      AND step.agent_run_id = CAST(:run_id AS uuid)
    ORDER BY step.sequence_number ASC
    """
)
_GET_GUARDRAILS = text(
    """
    SELECT event.id, event.kind::text AS kind, event.outcome::text AS outcome,
           event.occurred_at
    FROM public.guardrail_events AS event
    WHERE event.org_id = CAST(:org_id AS uuid)
      AND event.agent_run_id = CAST(:run_id AS uuid)
    ORDER BY event.occurred_at ASC, event.id ASC
    """
)


@router.get("/{run_id}/stream", response_class=StreamingResponse)
async def stream_run(
    run_id: UUID,
    scope: Annotated[TenantScope, Depends(get_request_tenant_scope)],
    session: Annotated[AsyncSession, Depends(get_request_session)],
) -> StreamingResponse:
    """Return the current safe trace snapshot for a single visible run.

    See ``docs/events.md`` for the wire contract.  This intentionally does not
    hold a database transaction open while waiting for future worker changes.
    """

    run_result = await session.execute(
        _GET_RUN, {"org_id": str(scope.org_id), "run_id": str(run_id)}
    )
    run = run_result.mappings().one_or_none()
    if run is None:
        # A foreign run is indistinguishable from an absent one.
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)

    step_result = await session.execute(
        _GET_STEPS, {"org_id": str(scope.org_id), "run_id": str(run_id)}
    )
    steps = [
        cast(Mapping[str, object], dict(row)) for row in step_result.mappings().all()
    ]
    guardrail_result = await session.execute(
        _GET_GUARDRAILS, {"org_id": str(scope.org_id), "run_id": str(run_id)}
    )
    guardrails = [
        cast(Mapping[str, object], dict(row))
        for row in guardrail_result.mappings().all()
    ]
    return StreamingResponse(
        _snapshot_events(run_id, dict(run), steps, guardrails),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


async def _snapshot_events(
    run_id: UUID,
    run: Mapping[str, object],
    steps: list[Mapping[str, object]],
    guardrails: list[Mapping[str, object]],
) -> AsyncIterator[str]:
    """Yield the deterministic, replay-safe event sequence for one snapshot."""

    run_status = str(run["status"])
    occurred_at = _timestamp(run["occurred_at"])
    yield _sse_event(
        event_id=f"timeline:{run_id}",
        event_name="timeline.ready",
        payload={
            "run_id": str(run_id),
            "occurred_at": occurred_at,
            "run_status": run_status,
            "steps": [
                {"sequence": index, "stage": stage, "status": "pending"}
                for index, stage in enumerate(_TIMELINE_STAGES, start=1)
            ],
        },
    )

    emitted_failure = False
    for step in steps:
        sequence = _integer(step["sequence_number"])
        step_status = str(step["status"])
        stage = _COMPONENT_STAGE_NAMES.get(str(step["component_name"]), "unknown")
        if step_status == "failed":
            emitted_failure = True
            yield _sse_event(
                event_id=f"step:{run_id}:{sequence}",
                event_name="run.failed",
                payload={
                    "run_id": str(run_id),
                    "occurred_at": _timestamp(step["occurred_at"]),
                    "failure_code": _failure_code(step.get("error_code")),
                },
            )
            continue
        yield _sse_event(
            event_id=f"step:{run_id}:{sequence}",
            event_name="step.started" if step_status == "running" else "step.finished",
            payload={
                "run_id": str(run_id),
                "occurred_at": _timestamp(step["occurred_at"]),
                "sequence": sequence,
                "stage": stage,
                "status": step_status,
            },
        )

    for guardrail in guardrails:
        guardrail_id = guardrail["id"]
        if not isinstance(guardrail_id, UUID):
            raise TypeError("guardrail event identifiers must be UUIDs")
        yield _sse_event(
            event_id=f"guardrail:{run_id}:{guardrail_id}",
            event_name="guardrail.hit",
            payload={
                "run_id": str(run_id),
                "occurred_at": _timestamp(guardrail["occurred_at"]),
                "kind": _guardrail_value(guardrail["kind"], field_name="kind"),
                "outcome": _guardrail_value(guardrail["outcome"], field_name="outcome"),
            },
        )

    if run_status == "failed" and not emitted_failure:
        yield _sse_event(
            event_id=f"run:{run_id}:failed",
            event_name="run.failed",
            payload={
                "run_id": str(run_id),
                "occurred_at": occurred_at,
                "failure_code": "run_failed",
            },
        )


def _sse_event(*, event_id: str, event_name: str, payload: Mapping[str, object]) -> str:
    """Encode one compact SSE event without allowing multiline injection."""

    data = json.dumps(payload, separators=(",", ":"), sort_keys=True)
    return f"id: {event_id}\nevent: {event_name}\ndata: {data}\n\n"


def _timestamp(value: object) -> str:
    """Render database timestamps as RFC 3339 UTC strings."""

    if not isinstance(value, datetime):
        raise TypeError("stream event timestamps must be datetimes")
    return value.isoformat().replace("+00:00", "Z")


def _failure_code(value: object) -> str:
    """Do not leak database or provider failure detail into the event stream."""

    if isinstance(value, str) and _SAFE_FAILURE_CODE.fullmatch(value) is not None:
        return value
    return "step_failed"


def _integer(value: object) -> int:
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    raise TypeError("stream event sequence numbers must be integers")


def _guardrail_value(value: object, *, field_name: str) -> str:
    """Project database enums without ever exposing a free-form audit field."""

    allowed = (
        {
            "tenant_authorisation",
            "rate_limit",
            "payload_size",
            "pii_redaction",
            "prompt_injection",
            "content_safety",
            "schema_validation",
            "citation_verification",
            "numeric_sanity",
            "policy_compliance",
            "fair_housing",
            "output_pii",
            "grant_scope",
            "idempotency",
            "cost_budget",
            "latency_budget",
        }
        if field_name == "kind"
        else {"passed", "blocked", "escalated", "degraded"}
    )
    if not isinstance(value, str) or value not in allowed:
        raise ValueError(f"unknown guardrail {field_name}")
    return value
