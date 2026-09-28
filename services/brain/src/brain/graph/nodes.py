"""Thin LangGraph adapters around the framework-independent maintenance agents.

The graph owns orchestration dependencies and transitions; the agent modules own
their respective decisions. Raw resident content is deliberately reloaded by a
tenant-scoped repository rather than copied into checkpointed state.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Literal, Protocol

from langgraph.types import RunnableConfig

from brain.agents.auditor import (
    AuditResult,
    AuditorGateway,
    AuditorRequest,
    PolicyAuditStatus,
    audit_dispatch,
)
from brain.agents.diagnostician import (
    DiagnosticianGateway,
    DiagnosticianRequest,
    DiagnosisStatus,
    diagnose,
)
from brain.agents.dispatch import (
    DispatchGateway,
    DispatchRequest,
    DispatchStatus,
    Trade,
    VendorCandidate,
    plan_dispatch,
)
from brain.agents.intake import (
    IntakeFailureKind,
    IntakeGateway,
    IntakeRequest,
    IntakeStatus,
    normalize_intake,
)
from brain.agents.p0_protocol import (
    P0PageRequest,
    P0PagingTransport,
    build_p0_page_plan,
    dispatch_p0_from_orchestrator,
)
from brain.agents.safety import SafetySecondOpinionGateway, assess_safety
from brain.context.envelope import ContextEnvelope
from brain.graph.state import (
    DecisionMode,
    DecisionProposal,
    GuardrailEvent,
    GuardrailKind,
    GuardrailOutcome,
    GuardrailStage,
    RetryRecord,
    RetryStage,
    TicketState,
    TraceEntry,
    TraceOutcome,
    TraceStage,
)
from brain.guardrails.shield import (
    LOCAL_SHIELD_VERSION,
    Shield,
    ShieldAssessment,
    ShieldOutcome,
    ShieldRequest,
    ShieldStage,
)
from brain.policy.precedence import PolicyClaim


@dataclass(frozen=True, slots=True)
class DispatchSnapshot:
    """Operational values that the dispatch agent is permitted to receive."""

    property_region_code: str
    evaluated_at: datetime
    in_house_trades: tuple[Trade, ...] = ()
    vendor_candidates: tuple[VendorCandidate, ...] = ()


@dataclass(frozen=True, slots=True)
class AuditEvidence:
    """Policy-only input that deliberately excludes diagnostic reasoning."""

    policy_context: str
    policy_claims: tuple[PolicyClaim, ...]


class WorkflowInputRepository(Protocol):
    """Read the authorised inputs needed to continue one durable ticket run."""

    async def load_intake_request(self, state: TicketState) -> IntakeRequest:
        """Return the current redacted resident report and submission metadata."""

    async def load_context_envelope(self, state: TicketState) -> ContextEnvelope:
        """Return context assembled by the authorised context-broker boundary."""

    async def load_dispatch_snapshot(self, state: TicketState) -> DispatchSnapshot:
        """Return the current non-authoritative operations snapshot."""

    async def load_audit_evidence(self, state: TicketState) -> AuditEvidence:
        """Return statute, lease, and SOP claims for independent review."""

    async def load_p0_page_request(self, state: TicketState) -> P0PageRequest:
        """Return the minimum ticket reference permitted in a P0 page."""


@dataclass(frozen=True, slots=True)
class DecisionGatePolicy:
    """Current deployment policy: every proposal requires human approval.

    ``TicketState.confidence`` is retained as an auditable observation for the
    future calibration component. It is deliberately not an authority signal
    until that component and its acceptance evidence exist.
    """


@dataclass(frozen=True, slots=True)
class GraphDependencies:
    """Capabilities injected by the orchestration composition root only."""

    inputs: WorkflowInputRepository
    intake_gateway: IntakeGateway
    diagnostician_gateway: DiagnosticianGateway
    dispatch_gateway: DispatchGateway
    auditor_gateway: AuditorGateway
    p0_transport: P0PagingTransport
    demo_mode: bool
    safety_second_opinion_gateway: SafetySecondOpinionGateway | None = None
    decision_gate_policy: DecisionGatePolicy = DecisionGatePolicy()
    shield: Shield = field(default_factory=Shield)


async def safety_node(
    state: TicketState, config: RunnableConfig, *, dependencies: GraphDependencies
) -> dict[str, object]:
    """Run the P0 screen before any ordinary model-backed agent."""

    _require_thread_id(config)
    intake = await dependencies.inputs.load_intake_request(state)
    verdict = await assess_safety(
        intake.resident_report,
        photo_captions=intake.photo_captions,
        second_opinion_gateway=dependencies.safety_second_opinion_gateway,
    )
    if verdict.p0:
        return _completed(state, TraceStage.SAFETY, safety=verdict)

    guardrail_events = await _shield_intake_content(intake, dependencies.shield)
    changes = {
        "safety": verdict,
        "guardrail_events": (*state.guardrail_events, *guardrail_events),
    }
    if any(event.outcome is GuardrailOutcome.BLOCKED for event in guardrail_events):
        return _human_review(state, TraceStage.SAFETY, **changes)
    return _completed(state, TraceStage.SAFETY, **changes)


async def p0_node(
    state: TicketState, config: RunnableConfig, *, dependencies: GraphDependencies
) -> dict[str, object]:
    """Invoke the sole P0 side effect after the graph's deterministic transition."""

    _require_thread_id(config)
    if state.safety is None or not state.safety.p0:
        raise ValueError("P0 node requires a positive safety verdict")
    request = await dependencies.inputs.load_p0_page_request(state)
    plan = build_p0_page_plan(request, state.safety)
    result = await dispatch_p0_from_orchestrator(
        plan, transport=dependencies.p0_transport, demo_mode=dependencies.demo_mode
    )
    return _completed(state, TraceStage.P0, digest_value=_p0_trace_value(result))


async def intake_node(
    state: TicketState, config: RunnableConfig, *, dependencies: GraphDependencies
) -> dict[str, object]:
    """Adapt the plain normalizer result to a typed graph handoff."""

    _require_thread_id(config)
    request = await dependencies.inputs.load_intake_request(state)
    result = await normalize_intake(request, gateway=dependencies.intake_gateway)
    retry = _intake_retry(state, result.repair_attempted, result.failure_kind)
    if result.status is IntakeStatus.COMPLETED:
        return _completed(state, TraceStage.INTAKE, facts=result.facts, retries=retry)
    return _human_review(state, TraceStage.INTAKE, retries=retry)


async def context_node(
    state: TicketState, config: RunnableConfig, *, dependencies: GraphDependencies
) -> dict[str, object]:
    """Attach the brokered, provenance-bearing context envelope."""

    _require_thread_id(config)
    if state.facts is None:
        raise ValueError("context node requires completed intake facts")
    envelope = await dependencies.inputs.load_context_envelope(state)
    return _completed(state, TraceStage.CONTEXT, envelope=envelope)


async def diagnosis_node(
    state: TicketState, config: RunnableConfig, *, dependencies: GraphDependencies
) -> dict[str, object]:
    """Push bounded context into the tool-free diagnostician."""

    _require_thread_id(config)
    request = _diagnostician_request(state)
    result = await diagnose(request, gateway=dependencies.diagnostician_gateway)
    outcome = (
        TraceOutcome.COMPLETED
        if result.status is DiagnosisStatus.COMPLETED
        else TraceOutcome.ABSTAINED
    )
    return _transition(state, TraceStage.DIAGNOSIS, outcome, diagnosis=result)


async def dispatch_node(
    state: TicketState, config: RunnableConfig, *, dependencies: GraphDependencies
) -> dict[str, object]:
    """Push the diagnosis and evidence into the proposal-only dispatch agent."""

    _require_thread_id(config)
    snapshot = await dependencies.inputs.load_dispatch_snapshot(state)
    result = await plan_dispatch(
        _dispatch_request(state, snapshot), gateway=dependencies.dispatch_gateway
    )
    outcome = (
        TraceOutcome.COMPLETED
        if result.status is DispatchStatus.PROPOSED
        else TraceOutcome.HUMAN_REVIEW_REQUIRED
    )
    return _transition(state, TraceStage.DISPATCH, outcome, plan=result)


async def audit_node(
    state: TicketState, config: RunnableConfig, *, dependencies: GraphDependencies
) -> dict[str, object]:
    """Give the independent auditor only a dispatch plan and policy evidence."""

    _require_thread_id(config)
    evidence = await dependencies.inputs.load_audit_evidence(state)
    result = await audit_dispatch(
        _auditor_request(state, evidence), gateway=dependencies.auditor_gateway
    )
    outcome = (
        TraceOutcome.COMPLETED
        if result.status is PolicyAuditStatus.COMPLIANT
        else TraceOutcome.HUMAN_REVIEW_REQUIRED
    )
    return _transition(state, TraceStage.POLICY_AUDIT, outcome, audit_result=result)


async def gate_node(
    state: TicketState, config: RunnableConfig, *, dependencies: GraphDependencies
) -> dict[str, object]:
    """Choose the required approval or escalation path in deterministic code."""

    _require_thread_id(config)
    decision = _decision_for(state, dependencies.decision_gate_policy)
    if decision is None:
        return _human_review(state, TraceStage.DECISION)
    return _completed(state, TraceStage.DECISION, decision=decision)


def approval_node(state: TicketState) -> dict[str, object]:
    """Resume target for an authorised human-approval workflow."""

    return _human_review(state, TraceStage.DECISION)


def escalate_node(state: TicketState) -> dict[str, object]:
    """Record a safe handoff when no autonomous proposal can proceed."""

    return _human_review(state, TraceStage.DECISION)


def route_after_safety(state: TicketState) -> Literal["p0", "context", "escalate"]:
    """Choose the P0 branch before the first normalisation model call."""

    if state.safety is None:
        raise ValueError("safety routing requires a safety verdict")
    if state.safety.p0:
        return "p0"
    if any(
        event.outcome is GuardrailOutcome.BLOCKED for event in state.guardrail_events
    ):
        return "escalate"
    return "context"


def route_after_intake(state: TicketState) -> Literal["context", "escalate"]:
    """Prevent failed normalisation from reaching retrieval or another model."""

    return "context" if state.facts is not None else "escalate"


def route_after_diagnosis(state: TicketState) -> Literal["dispatch", "gate"]:
    """Do not ask dispatch to invent a cause after an explicit abstention."""

    if state.diagnosis is None:
        raise ValueError("diagnosis routing requires a diagnosis result")
    return "dispatch" if state.diagnosis.status is DiagnosisStatus.COMPLETED else "gate"


def route_after_dispatch(state: TicketState) -> Literal["audit", "gate"]:
    """Audit only a concrete proposal; all dispatch failures are escalated."""

    if state.plan is None:
        raise ValueError("dispatch routing requires a dispatch result")
    return "audit" if state.plan.status is DispatchStatus.PROPOSED else "gate"


def route_after_gate(state: TicketState) -> Literal["approve", "escalate"]:
    """Route the current human-authorised decision policy."""

    if state.decision is None:
        return "escalate"
    if state.decision.mode is DecisionMode.APPROVAL_REQUIRED:
        return "approve"
    return "escalate"


def _diagnostician_request(state: TicketState) -> DiagnosticianRequest:
    facts = _require(state.facts, "diagnosis requires intake facts")
    envelope = _require(state.envelope, "diagnosis requires a context envelope")
    return DiagnosticianRequest(
        ticket_facts=facts,
        grounded_context=envelope.render(),
        provenance_ids=_provenance_ids(envelope),
    )


def _dispatch_request(
    state: TicketState, snapshot: DispatchSnapshot
) -> DispatchRequest:
    facts = _require(state.facts, "dispatch requires intake facts")
    envelope = _require(state.envelope, "dispatch requires a context envelope")
    diagnosis = _require(state.diagnosis, "dispatch requires a diagnosis result")
    assessment = _require(
        diagnosis.assessment, "dispatch requires a completed diagnosis assessment"
    )
    return DispatchRequest(
        ticket_facts=facts,
        diagnosis=assessment,
        grounded_context=envelope.render(),
        provenance_ids=_provenance_ids(envelope),
        property_region_code=snapshot.property_region_code,
        evaluated_at=snapshot.evaluated_at,
        in_house_trades=snapshot.in_house_trades,
        vendor_candidates=snapshot.vendor_candidates,
    )


def _auditor_request(state: TicketState, evidence: AuditEvidence) -> AuditorRequest:
    dispatch = _require(state.plan, "audit requires a dispatch result")
    plan = _require(dispatch.plan, "audit requires a proposed dispatch plan")
    return AuditorRequest(
        dispatch_plan=plan,
        policy_context=evidence.policy_context,
        policy_claims=evidence.policy_claims,
    )


def _decision_for(
    state: TicketState, policy: DecisionGatePolicy
) -> DecisionProposal | None:
    del policy
    provenance_ids = _decision_provenance_ids(state)
    if not provenance_ids:
        return None
    if state.plan is None or state.plan.status is not DispatchStatus.PROPOSED:
        return DecisionProposal(
            mode=DecisionMode.ESCALATE,
            rationale="No dispatch proposal is available for an autonomous decision.",
            provenance_ids=provenance_ids,
            unknowns=("A human must resolve the unavailable dispatch proposal.",),
        )
    if (
        state.audit_result is None
        or state.audit_result.status is not PolicyAuditStatus.COMPLIANT
    ):
        return DecisionProposal(
            mode=DecisionMode.ESCALATE,
            rationale="The dispatch proposal did not receive a compliant policy audit.",
            provenance_ids=provenance_ids,
            unknowns=("A human must resolve the policy-audit outcome.",),
        )
    return DecisionProposal(
        mode=DecisionMode.APPROVAL_REQUIRED,
        rationale=(
            "The cited dispatch proposal passed policy audit and requires human "
            "approval before execution."
        ),
        provenance_ids=provenance_ids,
    )


def _decision_provenance_ids(state: TicketState) -> tuple[str, ...]:
    envelope = state.envelope
    if envelope is None:
        return ()
    available = set(_provenance_ids(envelope))
    used: list[str] = []
    if state.plan is not None and state.plan.plan is not None:
        used.extend(state.plan.plan.proposal.provenance_ids)
    audit: AuditResult | None = state.audit_result
    if audit is not None and audit.assessment is not None:
        used.extend(
            provenance_id
            for finding in audit.assessment.findings
            for provenance_id in finding.provenance_ids
        )
    selected = tuple(
        provenance_id
        for provenance_id in dict.fromkeys(used)
        if provenance_id in available
    )
    return selected or _provenance_ids(envelope)


def _provenance_ids(envelope: ContextEnvelope) -> tuple[str, ...]:
    return tuple(
        record.provenance_id for record in (*envelope.citations, *envelope.facts)
    )


def _intake_retry(
    state: TicketState,
    repair_attempted: bool,
    failure_kind: IntakeFailureKind | None,
) -> tuple[RetryRecord, ...]:
    if not repair_attempted:
        return state.retries
    code = (
        failure_kind.value
        if failure_kind is not None
        else IntakeFailureKind.SCHEMA_VALIDATION.value
    )
    records = tuple(
        record for record in state.retries if record.stage is not RetryStage.INTAKE
    )
    return (
        *records,
        RetryRecord(stage=RetryStage.INTAKE, attempts=2, last_failure_code=code),
    )


async def _shield_intake_content(
    intake: IntakeRequest, shield: Shield
) -> tuple[GuardrailEvent, ...]:
    """Screen each raw resident field before it can reach ordinary model work."""

    events: list[GuardrailEvent] = []
    for content in (intake.resident_report, *intake.photo_captions):
        request = ShieldRequest(content=content, stage=ShieldStage.PRE_MODEL)
        assessment = await shield.inspect(request)
        events.append(_shield_event(request, assessment))
        if assessment.outcome is ShieldOutcome.BLOCK:
            break
    return tuple(events)


def _shield_event(
    request: ShieldRequest, assessment: ShieldAssessment
) -> GuardrailEvent:
    """Project a shield result to the persistence-shaped, content-free receipt."""

    if assessment.outcome is ShieldOutcome.BLOCK:
        outcome = GuardrailOutcome.BLOCKED
        reason_code = next(
            reason_code
            for finding in assessment.findings
            if finding.outcome is ShieldOutcome.BLOCK
            for reason_code in finding.reason_codes
        )
    elif assessment.degradations:
        outcome = GuardrailOutcome.DEGRADED
        reason_code = f"managed_provider_{assessment.degradations[0].kind.value}"
    else:
        outcome = GuardrailOutcome.PASSED
        reason_code = "content_safety_passed"
    return GuardrailEvent(
        kind=GuardrailKind.CONTENT_SAFETY,
        stage=GuardrailStage(request.stage.value),
        outcome=outcome,
        rule_version=LOCAL_SHIELD_VERSION,
        content_digest=assessment.content_digest,
        reason_code=reason_code,
    )


def _completed(
    state: TicketState,
    stage: TraceStage,
    *,
    digest_value: object | None = None,
    **changes: object,
) -> dict[str, object]:
    return _transition(
        state,
        stage,
        TraceOutcome.COMPLETED,
        digest_value=digest_value,
        **changes,
    )


def _human_review(
    state: TicketState, stage: TraceStage, **changes: object
) -> dict[str, object]:
    return _transition(state, stage, TraceOutcome.HUMAN_REVIEW_REQUIRED, **changes)


def _transition(
    state: TicketState,
    stage: TraceStage,
    outcome: TraceOutcome,
    *,
    digest_value: object | None = None,
    **changes: object,
) -> dict[str, object]:
    input_digest = _digest(
        {
            "org_id": str(state.org_id),
            "ticket_id": str(state.ticket_id),
            "run_id": str(state.run_id),
            "stage": stage.value,
            "trace_sequence": len(state.trace),
        }
    )
    output_digest = _digest(digest_value if digest_value is not None else changes)
    trace = (*state.trace,)
    trace += (
        TraceEntry(
            sequence=len(trace) + 1,
            stage=stage,
            outcome=outcome,
            input_digest=input_digest,
            output_digest=output_digest,
        ),
    )
    payload = {
        field_name: getattr(state, field_name)
        for field_name in TicketState.model_fields
    }
    payload.update(changes)
    payload["trace"] = trace
    validated = TicketState.model_validate(payload)
    return {
        field_name: getattr(validated, field_name)
        for field_name in TicketState.model_fields
    }


def _digest(value: object) -> str:
    serialized = json.dumps(
        value,
        default=_json_default,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    )
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def _json_default(value: object) -> object:
    model_dump = getattr(value, "model_dump", None)
    if callable(model_dump):
        return model_dump(mode="json")
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, Mapping):
        return dict(value)
    return str(value)


def _p0_trace_value(result: object) -> dict[str, object]:
    receipts = getattr(result, "receipts")
    return {"delivery_statuses": tuple(receipt.status.value for receipt in receipts)}


def _require[T](value: T | None, message: str) -> T:
    if value is None:
        raise ValueError(message)
    return value


def _require_thread_id(config: RunnableConfig) -> None:
    configurable = config.get("configurable", {})
    thread_id = (
        configurable.get("thread_id") if isinstance(configurable, dict) else None
    )
    if not isinstance(thread_id, str) or not thread_id.strip():
        raise ValueError(
            "LangGraph execution requires a non-blank configurable.thread_id"
        )
