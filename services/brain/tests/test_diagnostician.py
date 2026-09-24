"""Regression coverage for the tool-free, grounded diagnostician."""

from __future__ import annotations

from typing import cast

import pytest

from brain.agents.diagnostician import (
    DiagnosticAssessment,
    DiagnosisFailureKind,
    DiagnosticianRequest,
    DiagnosisStatus,
    RecommendedAction,
    diagnose,
)
from brain.agents.intake import TicketFacts, TicketIntent
from brain.gateway.client import (
    GatewayError,
    RenderedPrompt,
    SchemaValidationError,
    TaskClass,
)


class _DiagnosticianGateway:
    def __init__(self, result: DiagnosticAssessment | Exception) -> None:
        self._result = result
        self.calls: list[
            tuple[TaskClass, RenderedPrompt, type[DiagnosticAssessment]]
        ] = []

    async def complete(
        self,
        task: TaskClass,
        prompt: RenderedPrompt,
        schema: type[DiagnosticAssessment],
    ) -> DiagnosticAssessment:
        self.calls.append((task, prompt, schema))
        if isinstance(self._result, Exception):
            raise self._result
        return self._result


def _facts() -> TicketFacts:
    return TicketFacts(
        intent=TicketIntent.MAINTENANCE,
        category="plumbing",
        symptom_summary="Kitchen sink backs up when the dishwasher drains.",
        affected_asset="kitchen sink drain",
        access_permission=True,
        pets_present=False,
    )


def _request(
    *, provenance_ids: tuple[str, ...] = ("[C1]", "[F1]")
) -> DiagnosticianRequest:
    return DiagnosticianRequest(
        ticket_facts=_facts(),
        grounded_context=(
            "[C1] Drain backups after dishwasher discharge can indicate a blocked trap.\n"
            "[F1] Unit 4B has a kitchen sink drain asset."
        ),
        provenance_ids=provenance_ids,
    )


def _assessment(*, citation: str = "[C1]") -> DiagnosticAssessment:
    return DiagnosticAssessment(
        likely_cause="The kitchen sink drain may have a partial blockage.",
        cause_provenance_ids=(citation,),
        recommended_actions=(
            RecommendedAction(
                action="Inspect the kitchen sink trap and branch drain.",
                rationale="The reported dishwasher-linked backup is consistent with a drain restriction.",
                provenance_ids=(citation,),
            ),
        ),
    )


@pytest.mark.asyncio
async def test_diagnostician_uses_only_pushed_context_and_the_central_gateway() -> None:
    gateway = _DiagnosticianGateway(_assessment())

    result = await diagnose(_request(), gateway=gateway)

    assert result.status is DiagnosisStatus.COMPLETED
    assert result.assessment == _assessment()
    assert gateway.calls[0][0] is TaskClass.DIAGNOSIS
    assert gateway.calls[0][2] is DiagnosticAssessment
    dynamic_prompt = gateway.calls[0][1].dynamic_suffix
    assert "dishwasher drains" in dynamic_prompt
    assert "Drain backups after dishwasher discharge" in dynamic_prompt
    assert "[C1]" in dynamic_prompt
    assert "cannot schedule work" in gateway.calls[0][1].static_prefix


@pytest.mark.asyncio
async def test_diagnostician_abstains_without_pushed_evidence_before_a_model_call() -> (
    None
):
    gateway = _DiagnosticianGateway(_assessment())

    result = await diagnose(_request(provenance_ids=()), gateway=gateway)

    assert result.status is DiagnosisStatus.ABSTAINED
    assert result.failure_kind is DiagnosisFailureKind.INSUFFICIENT_EVIDENCE
    assert gateway.calls == []


@pytest.mark.asyncio
async def test_diagnostician_rejects_model_citations_outside_the_pushed_envelope() -> (
    None
):
    gateway = _DiagnosticianGateway(_assessment(citation="[C2]"))

    result = await diagnose(_request(), gateway=gateway)

    assert result.status is DiagnosisStatus.ABSTAINED
    assert result.assessment is None
    assert result.failure_kind is DiagnosisFailureKind.UNSUPPORTED_CITATION
    assert len(gateway.calls) == 1


@pytest.mark.asyncio
async def test_diagnostician_abstains_on_schema_or_provider_failures() -> None:
    schema_failure = SchemaValidationError(
        "schema invalid",
        response_text='{"likely_cause":42}',
        validation_errors=(),
    )
    schema_gateway = _DiagnosticianGateway(schema_failure)
    provider_gateway = _DiagnosticianGateway(GatewayError("gateway unavailable"))

    schema_result = await diagnose(_request(), gateway=schema_gateway)
    provider_result = await diagnose(_request(), gateway=provider_gateway)

    assert schema_result.failure_kind is DiagnosisFailureKind.SCHEMA_VALIDATION
    assert provider_result.failure_kind is DiagnosisFailureKind.PROVIDER_UNAVAILABLE


def test_diagnostician_models_reject_ungrounded_or_mismatched_input() -> None:
    with pytest.raises(ValueError, match="requires at least one provenance"):
        DiagnosticAssessment(
            likely_cause="A blockage is likely.",
            recommended_actions=(
                RecommendedAction(
                    action="Inspect the drain.",
                    rationale="The fixture backs up.",
                    provenance_ids=("[C1]",),
                ),
            ),
        )
    with pytest.raises(ValueError, match="must appear"):
        DiagnosticianRequest(
            ticket_facts=_facts(),
            grounded_context="Evidence is unavailable.",
            provenance_ids=("[C1]",),
        )
    with pytest.raises(ValueError, match="bracketed C or F"):
        RecommendedAction(
            action="Inspect the drain.",
            rationale="The fixture backs up.",
            provenance_ids=cast(tuple[str, ...], ("C1",)),
        )
