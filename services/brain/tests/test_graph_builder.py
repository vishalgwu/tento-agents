"""End-to-end regression coverage for the durable maintenance graph."""

from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
from typing import cast
from uuid import UUID

import pytest
from langgraph.checkpoint.memory import MemorySaver
from langgraph.types import RunnableConfig
from pydantic import BaseModel

from brain.agents.auditor import (
    AuditFindingVerdict,
    AuditorGateway,
    PolicyAuditAssessment,
    PolicyAuditFinding,
)
from brain.agents.diagnostician import (
    DiagnosticAssessment,
    DiagnosticianGateway,
    RecommendedAction,
)
from brain.agents.dispatch import (
    DispatchFulfillment,
    DispatchGateway,
    DispatchProposal,
    ResponsibleParty,
    Trade,
)
from brain.agents.intake import IntakeGateway, IntakeRequest, TicketFacts, TicketIntent
from brain.agents.p0_protocol import P0Channel, P0PageRequest, P0PagingTransport
from brain.context.envelope import (
    ContextEnvelope,
    ProvenanceInput,
    assemble_context_envelope,
)
from brain.gateway.client import RenderedPrompt, TaskClass
from brain.graph.builder import (
    MAX_GRAPH_STEPS,
    MaintenanceGraph,
    TicketStateCheckpointSerializer,
    build_maintenance_graph,
)
from brain.graph.nodes import (
    AuditEvidence,
    DecisionGatePolicy,
    DispatchSnapshot,
    GraphDependencies,
    WorkflowInputRepository,
)
from brain.graph.state import DecisionMode, TicketState, TraceOutcome, TraceStage
from brain.policy.precedence import PolicyClaim
from brain.retrieval.ingest import Authority


_ORG_ID = UUID("00000000-0000-0000-0000-000000000001")
_TICKET_ID = UUID("00000000-0000-0000-0000-000000000002")
_RUN_ID = UUID("00000000-0000-0000-0000-000000000003")
_NOW = datetime(2026, 9, 26, 12, 0, tzinfo=timezone.utc)


def _envelope() -> ContextEnvelope:
    return assemble_context_envelope(
        citations=(
            ProvenanceInput(
                source="Lease",
                version="2026-01",
                effective_from=date(2026, 1, 1),
                effective_to=None,
                section="Repairs",
                text="Owner repairs plumbing defects reported by the resident.",
            ),
        )
    )


class _Inputs:
    def __init__(self, report: str) -> None:
        self._report = report
        self.envelope = _envelope()
        self.context_calls = 0
        self.p0_request_calls = 0

    async def load_intake_request(self, state: TicketState) -> IntakeRequest:
        return IntakeRequest(resident_report=self._report)

    async def load_context_envelope(self, state: TicketState) -> ContextEnvelope:
        self.context_calls += 1
        return self.envelope

    async def load_dispatch_snapshot(self, state: TicketState) -> DispatchSnapshot:
        return DispatchSnapshot(
            property_region_code="US-NY",
            evaluated_at=_NOW,
            in_house_trades=(Trade.PLUMBING,),
        )

    async def load_audit_evidence(self, state: TicketState) -> AuditEvidence:
        return AuditEvidence(
            policy_context=self.envelope.render(),
            policy_claims=(
                PolicyClaim(
                    claim_id="lease-repair",
                    policy_key="repair",
                    outcome="owner_responsible",
                    authority=Authority.LEASE,
                    provenance_ids=("[C1]",),
                ),
            ),
        )

    async def load_p0_page_request(self, state: TicketState) -> P0PageRequest:
        self.p0_request_calls += 1
        return P0PageRequest(
            org_id=state.org_id,
            ticket_id=state.ticket_id,
            ticket_number="T-2026-0001",
        )


class _Gateway:
    def __init__(
        self, *, audit_verdict: AuditFindingVerdict = AuditFindingVerdict.COMPLIANT
    ) -> None:
        self.calls: list[TaskClass] = []
        self._audit_verdict = audit_verdict

    async def complete(
        self,
        task: TaskClass,
        prompt: RenderedPrompt,
        schema: type[BaseModel],
    ) -> BaseModel:
        self.calls.append(task)
        if schema is TicketFacts:
            return TicketFacts(
                intent=TicketIntent.MAINTENANCE,
                category="plumbing",
                symptom_summary="Kitchen sink backs up after dishwasher use.",
                affected_asset="kitchen sink drain",
            )
        if schema is DiagnosticAssessment:
            return DiagnosticAssessment(
                likely_cause="A drain restriction is likely.",
                cause_provenance_ids=("[C1]",),
                recommended_actions=(
                    RecommendedAction(
                        action="Inspect the kitchen drain.",
                        rationale="The cited policy context supports an inspection.",
                        provenance_ids=("[C1]",),
                    ),
                ),
            )
        if schema is DispatchProposal:
            return DispatchProposal(
                trade=Trade.PLUMBING,
                fulfillment=DispatchFulfillment.IN_HOUSE,
                scope_summary="Inspect the kitchen sink drain.",
                responsible_party=ResponsibleParty.OWNER,
                provenance_ids=("[C1]",),
            )
        if schema is PolicyAuditAssessment:
            return PolicyAuditAssessment(
                findings=(
                    PolicyAuditFinding(
                        policy_key="repair",
                        verdict=self._audit_verdict,
                        rationale="The cited proposal received this policy finding.",
                        provenance_ids=("[C1]",),
                    ),
                ),
            )
        raise AssertionError(f"unexpected graph schema: {schema}")


class _Transport:
    def __init__(self) -> None:
        self.calls: list[P0Channel] = []

    async def send_p0_page(
        self,
        *,
        channel: P0Channel,
        message: str,
        idempotency_key: str,
    ) -> str:
        self.calls.append(channel)
        return f"receipt-{channel.value}"


def _dependencies(
    inputs: _Inputs,
    gateway: _Gateway,
    transport: _Transport,
    *,
    gate_policy: DecisionGatePolicy = DecisionGatePolicy(),
) -> GraphDependencies:
    return GraphDependencies(
        inputs=cast(WorkflowInputRepository, inputs),
        intake_gateway=cast(IntakeGateway, gateway),
        diagnostician_gateway=cast(DiagnosticianGateway, gateway),
        dispatch_gateway=cast(DispatchGateway, gateway),
        auditor_gateway=cast(AuditorGateway, gateway),
        p0_transport=cast(P0PagingTransport, transport),
        demo_mode=True,
        decision_gate_policy=gate_policy,
    )


def _graph(dependencies: GraphDependencies) -> MaintenanceGraph:
    return build_maintenance_graph(
        dependencies,
        checkpointer=MemorySaver(serde=TicketStateCheckpointSerializer()),
    )


def _state(*, confidence: Decimal | None = None) -> TicketState:
    return TicketState(
        org_id=_ORG_ID,
        ticket_id=_TICKET_ID,
        run_id=_RUN_ID,
        confidence=confidence,
    )


def _config(thread_id: str) -> RunnableConfig:
    return {"configurable": {"thread_id": thread_id}}


@pytest.mark.asyncio
async def test_p0_path_pages_before_any_normalization_or_model_work() -> None:
    inputs = _Inputs("I smell gas by the stove.")
    gateway = _Gateway()
    transport = _Transport()

    result = await _graph(_dependencies(inputs, gateway, transport)).ainvoke(
        _state(), _config("p0-ticket")
    )

    assert result.safety is not None and result.safety.p0
    assert result.facts is None
    assert gateway.calls == []
    assert inputs.context_calls == 0
    assert inputs.p0_request_calls == 1
    assert transport.calls == []
    assert tuple(entry.stage for entry in result.trace) == (
        TraceStage.SAFETY,
        TraceStage.P0,
    )


@pytest.mark.asyncio
async def test_approval_path_pauses_and_resumes_from_a_strict_checkpoint() -> None:
    inputs = _Inputs("Kitchen sink backs up after dishwasher use.")
    gateway = _Gateway()
    graph = _graph(_dependencies(inputs, gateway, _Transport()))

    paused = await graph.ainvoke(
        _state(confidence=Decimal("0.95")), _config("approval")
    )
    checkpoint = await graph.aget_state(_config("approval"))
    completed = await graph.ainvoke(None, _config("approval"))

    assert paused.decision is not None
    assert paused.decision.mode is DecisionMode.APPROVAL_REQUIRED
    assert checkpoint.next == ("approval",)
    assert completed.trace[-1].outcome is TraceOutcome.HUMAN_REVIEW_REQUIRED
    assert isinstance(completed.trace, tuple)
    assert completed.safety is not None
    assert isinstance(completed.safety.categories, tuple)
    assert gateway.calls == [
        TaskClass.INTAKE_NORMALIZATION,
        TaskClass.DIAGNOSIS,
        TaskClass.DISPATCH_PLANNING,
        TaskClass.POLICY_AUDIT,
    ]


@pytest.mark.asyncio
async def test_explicit_policy_can_select_the_non_executing_auto_route() -> None:
    inputs = _Inputs("Kitchen sink backs up after dishwasher use.")
    graph = _graph(
        _dependencies(
            inputs,
            _Gateway(),
            _Transport(),
            gate_policy=DecisionGatePolicy(
                automatic_confidence_threshold=Decimal("0.90"),
                automatic_decisions_enabled=True,
            ),
        )
    )

    result = await graph.ainvoke(_state(confidence=Decimal("0.95")), _config("auto"))

    assert result.decision is not None
    assert result.decision.mode is DecisionMode.AUTO
    assert result.trace[-1].outcome is TraceOutcome.COMPLETED


@pytest.mark.asyncio
async def test_audit_conflict_selects_the_human_escalation_route() -> None:
    graph = _graph(
        _dependencies(
            _Inputs("Kitchen sink backs up after dishwasher use."),
            _Gateway(audit_verdict=AuditFindingVerdict.CONFLICT),
            _Transport(),
        )
    )

    result = await graph.ainvoke(_state(), _config("escalate"))

    assert result.decision is not None
    assert result.decision.mode is DecisionMode.ESCALATE
    assert result.trace[-1].outcome is TraceOutcome.HUMAN_REVIEW_REQUIRED


@pytest.mark.asyncio
async def test_callers_cannot_override_the_hard_step_cap() -> None:
    graph = _graph(
        _dependencies(_Inputs("Routine sink backup."), _Gateway(), _Transport())
    )
    config = _config("capped")
    config["recursion_limit"] = MAX_GRAPH_STEPS + 1

    with pytest.raises(ValueError, match=f"recursion_limit={MAX_GRAPH_STEPS}"):
        await graph.ainvoke(_state(), config)
