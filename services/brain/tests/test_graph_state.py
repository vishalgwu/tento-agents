"""Regression coverage for the framework-independent ticket state contract."""

from __future__ import annotations

import inspect
from datetime import date
from decimal import Decimal
from uuid import UUID

import pytest

from brain.agents.auditor import (
    AuditFindingVerdict,
    AuditResult,
    PolicyAuditAssessment,
    PolicyAuditFinding,
    PolicyAuditStatus,
)
from brain.agents.diagnostician import (
    DiagnosticAssessment,
    DiagnosisResult,
    DiagnosisStatus,
    RecommendedAction,
)
from brain.agents.dispatch import (
    DispatchFulfillment,
    DispatchPlan,
    DispatchProposal,
    DispatchResult,
    DispatchStatus,
    ResponsibleParty,
    Trade,
)
from brain.agents.intake import TicketFacts, TicketIntent
from brain.agents.safety import ModelOpinionStatus, SafetyVerdict
from brain.context.envelope import ProvenanceInput, assemble_context_envelope
from brain.graph import state
from brain.graph.state import (
    DecisionMode,
    DecisionProposal,
    RetryRecord,
    RetryStage,
    TicketState,
    TraceEntry,
    TraceOutcome,
    TraceStage,
)
from brain.policy.precedence import PolicyClaim, resolve_policy_conflicts
from brain.retrieval.ingest import Authority


_DIGEST = "a" * 64
_SECOND_DIGEST = "b" * 64


def _facts() -> TicketFacts:
    return TicketFacts(
        intent=TicketIntent.MAINTENANCE,
        category="plumbing",
        symptom_summary="Kitchen sink backs up after dishwasher use.",
        affected_asset="kitchen sink drain",
    )


def _diagnosis() -> DiagnosisResult:
    return DiagnosisResult(
        status=DiagnosisStatus.COMPLETED,
        assessment=DiagnosticAssessment(
            likely_cause="The drain may have a partial blockage.",
            cause_provenance_ids=("[C1]",),
            recommended_actions=(
                RecommendedAction(
                    action="Inspect the drain.",
                    rationale="The report is consistent with a drain restriction.",
                    provenance_ids=("[C1]",),
                ),
            ),
        ),
    )


def _plan() -> DispatchResult:
    return DispatchResult(
        status=DispatchStatus.PROPOSED,
        plan=DispatchPlan(
            proposal=DispatchProposal(
                trade=Trade.PLUMBING,
                fulfillment=DispatchFulfillment.IN_HOUSE,
                scope_summary="Assess the kitchen drain backup.",
                responsible_party=ResponsibleParty.UNDETERMINED,
                provenance_ids=("[C1]",),
            )
        ),
    )


def _audit_result() -> AuditResult:
    resolutions = resolve_policy_conflicts(
        (
            PolicyClaim(
                claim_id="statute",
                policy_key="charge",
                outcome="legal_review_required",
                authority=Authority.STATUTE,
                provenance_ids=("[C1]",),
            ),
        )
    )
    return AuditResult(
        status=PolicyAuditStatus.COMPLIANT,
        assessment=PolicyAuditAssessment(
            findings=(
                PolicyAuditFinding(
                    policy_key="charge",
                    verdict=AuditFindingVerdict.COMPLIANT,
                    rationale="No charge is proposed.",
                    provenance_ids=("[C1]",),
                ),
            )
        ),
        policy_resolutions=resolutions,
    )


def test_ticket_state_carries_typed_handoffs_and_digest_only_trace() -> None:
    envelope = assemble_context_envelope(
        citations=(
            ProvenanceInput(
                source="Statute",
                version="2026-01",
                effective_from=date(2026, 1, 1),
                effective_to=None,
                section="Repairs",
                text="The source requires legal review before a charge decision.",
            ),
        )
    )
    state_value = TicketState(
        org_id=UUID("00000000-0000-0000-0000-000000000001"),
        ticket_id=UUID("00000000-0000-0000-0000-000000000002"),
        run_id=UUID("00000000-0000-0000-0000-000000000003"),
        safety=SafetyVerdict(
            p0=False,
            categories=(),
            deterministic_signals=(),
            model_categories=(),
            model_opinion_status=ModelOpinionStatus.UNAVAILABLE,
        ),
        facts=_facts(),
        envelope=envelope,
        diagnosis=_diagnosis(),
        plan=_plan(),
        audit_result=_audit_result(),
        decision=DecisionProposal(
            mode=DecisionMode.AUTO,
            rationale="The plan is policy-compliant and cited.",
            provenance_ids=("[C1]",),
        ),
        confidence=Decimal("0.80"),
        retries=(
            RetryRecord(
                stage=RetryStage.INTAKE,
                attempts=1,
                last_failure_code="schema_validation",
            ),
        ),
        trace=(
            TraceEntry(
                sequence=1,
                stage=TraceStage.INTAKE,
                outcome=TraceOutcome.STARTED,
                input_digest=_DIGEST,
            ),
            TraceEntry(
                sequence=2,
                stage=TraceStage.INTAKE,
                outcome=TraceOutcome.COMPLETED,
                input_digest=_DIGEST,
                output_digest=_SECOND_DIGEST,
            ),
        ),
    )

    assert state_value.facts == _facts()
    assert state_value.envelope == envelope
    assert state_value.diagnosis == _diagnosis()
    assert state_value.plan == _plan()
    assert state_value.audit_result == _audit_result()
    assert state_value.decision is not None
    assert state_value.trace[1].output_digest == _SECOND_DIGEST
    assert "import langgraph" not in inspect.getsource(state).casefold()


def test_state_rejects_untrusted_trace_data_duplicate_retries_and_unsafe_auto_mode() -> (
    None
):
    with pytest.raises(ValueError, match="lowercase SHA-256"):
        TraceEntry(
            sequence=1,
            stage=TraceStage.SAFETY,
            outcome=TraceOutcome.STARTED,
            input_digest=_DIGEST.upper(),
        )
    with pytest.raises(ValueError, match="must not repeat"):
        TicketState(
            org_id=UUID("00000000-0000-0000-0000-000000000001"),
            ticket_id=UUID("00000000-0000-0000-0000-000000000002"),
            run_id=UUID("00000000-0000-0000-0000-000000000003"),
            retries=(
                RetryRecord(
                    stage=RetryStage.DISPATCH,
                    attempts=1,
                    last_failure_code="provider_unavailable",
                ),
                RetryRecord(
                    stage=RetryStage.DISPATCH,
                    attempts=2,
                    last_failure_code="provider_unavailable",
                ),
            ),
        )
    with pytest.raises(ValueError, match="proposed dispatch plan"):
        TicketState(
            org_id=UUID("00000000-0000-0000-0000-000000000001"),
            ticket_id=UUID("00000000-0000-0000-0000-000000000002"),
            run_id=UUID("00000000-0000-0000-0000-000000000003"),
            decision=DecisionProposal(
                mode=DecisionMode.AUTO,
                rationale="No evidence supports an automatic decision.",
                provenance_ids=("[C1]",),
            ),
        )
    with pytest.raises(ValueError, match="strictly increasing"):
        TicketState(
            org_id=UUID("00000000-0000-0000-0000-000000000001"),
            ticket_id=UUID("00000000-0000-0000-0000-000000000002"),
            run_id=UUID("00000000-0000-0000-0000-000000000003"),
            trace=(
                TraceEntry(
                    sequence=2,
                    stage=TraceStage.CONTEXT,
                    outcome=TraceOutcome.STARTED,
                    input_digest=_DIGEST,
                ),
                TraceEntry(
                    sequence=1,
                    stage=TraceStage.CONTEXT,
                    outcome=TraceOutcome.STARTED,
                    input_digest=_DIGEST,
                ),
            ),
        )
