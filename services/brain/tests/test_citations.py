"""Regression coverage for deterministic citation verification and repair bounds."""

from __future__ import annotations

from datetime import date

import pytest

from brain.context.envelope import (
    ContextEnvelope,
    ProvenanceInput,
    assemble_context_envelope,
)
from brain.gateway.client import (
    GatewayError,
    RenderedPrompt,
    SchemaValidationError,
    TaskClass,
)
from brain.guardrails.citations import (
    CitationGuardFailureKind,
    CitationGuardStatus,
    CitationRegeneration,
    CitationViolationKind,
    verify_and_repair_citations,
    verify_citations,
)


class _CitationRepairGateway:
    def __init__(self, result: CitationRegeneration | Exception) -> None:
        self._result = result
        self.calls: list[
            tuple[TaskClass, RenderedPrompt, type[CitationRegeneration]]
        ] = []

    async def complete(
        self,
        task: TaskClass,
        prompt: RenderedPrompt,
        schema: type[CitationRegeneration],
    ) -> CitationRegeneration:
        self.calls.append((task, prompt, schema))
        if isinstance(self._result, Exception):
            raise self._result
        return self._result


def _envelope() -> ContextEnvelope:
    return assemble_context_envelope(
        citations=(
            ProvenanceInput(
                source="Lease",
                version="2026-01",
                effective_from=date(2026, 1, 1),
                effective_to=None,
                section="§7.3 Repairs",
                text="Under §7.3, the maximum charge is $1,200 on 2026-09-23.",
            ),
        ),
        facts=(
            ProvenanceInput(
                source="Unit record",
                version="2026-09-01",
                effective_from=date(2026, 9, 1),
                effective_to=None,
                section="Kitchen",
                text="Unit 4B has a kitchen sink drain.",
            ),
        ),
    )


def test_verifier_accepts_exact_figures_with_a_trailing_known_citation() -> None:
    verification = verify_citations(
        "Under §7.3, the maximum charge is $1,200 on 2026-09-23. [C1]",
        envelope=_envelope(),
    )

    assert verification.valid is True
    assert verification.violations == ()


def test_verifier_rejects_unknown_ids_and_uncited_numeric_claims() -> None:
    verification = verify_citations(
        "The repair will cost $1,200. The unit is 4B. [C9]",
        envelope=_envelope(),
    )

    assert verification.valid is False
    assert [
        (item.kind, item.figure, item.citation_id) for item in verification.violations
    ] == [
        (CitationViolationKind.MISSING_CITATION, "$1,200", None),
        (CitationViolationKind.UNKNOWN_CITATION, None, "[C9]"),
        (CitationViolationKind.UNSUPPORTED_FIGURE, "4", "[C9]"),
    ]


def test_verifier_requires_exact_figure_text_in_a_cited_record() -> None:
    verification = verify_citations(
        "The maximum charge is $1,250. [C1]",
        envelope=_envelope(),
    )

    assert verification.valid is False
    assert verification.violations[0].kind is CitationViolationKind.UNSUPPORTED_FIGURE
    assert verification.violations[0].figure == "$1,250"
    assert verification.violations[0].citation_id == "[C1]"


@pytest.mark.asyncio
async def test_guard_skips_the_model_for_a_valid_candidate() -> None:
    gateway = _CitationRepairGateway(CitationRegeneration(revised_text="unused"))
    candidate = "Under §7.3, the maximum charge is $1,200 on 2026-09-23. [C1]"

    result = await verify_and_repair_citations(
        candidate,
        envelope=_envelope(),
        gateway=gateway,
    )

    assert result.status is CitationGuardStatus.VERIFIED
    assert result.safe_text == candidate
    assert result.regeneration_attempted is False
    assert gateway.calls == []


@pytest.mark.asyncio
async def test_guard_performs_one_targeted_repair_then_releases_only_valid_text() -> (
    None
):
    gateway = _CitationRepairGateway(
        CitationRegeneration(
            revised_text="The maximum charge is $1,200. [C1]",
        )
    )

    result = await verify_and_repair_citations(
        "The maximum charge is $1,250. [C1]",
        envelope=_envelope(),
        gateway=gateway,
    )

    assert result.status is CitationGuardStatus.VERIFIED
    assert result.safe_text == "The maximum charge is $1,200. [C1]"
    assert result.regeneration_attempted is True
    assert [call[0] for call in gateway.calls] == [TaskClass.CITATION_REPAIR]
    dynamic_prompt = gateway.calls[0][1].dynamic_suffix
    assert '"unsupported_figure"' in dynamic_prompt
    assert "$1,250" in dynamic_prompt
    assert "Under §7.3" in dynamic_prompt


@pytest.mark.asyncio
async def test_guard_sends_second_invalid_repair_or_repair_failure_to_human_review() -> (
    None
):
    invalid_gateway = _CitationRepairGateway(
        CitationRegeneration(revised_text="The maximum charge is $1,250. [C1]")
    )
    failed_gateway = _CitationRepairGateway(GatewayError("provider unavailable"))

    invalid_result = await verify_and_repair_citations(
        "The maximum charge is $1,250. [C1]",
        envelope=_envelope(),
        gateway=invalid_gateway,
    )
    failed_result = await verify_and_repair_citations(
        "The maximum charge is $1,250. [C1]",
        envelope=_envelope(),
        gateway=failed_gateway,
    )

    assert invalid_result.status is CitationGuardStatus.HUMAN_REVIEW_REQUIRED
    assert invalid_result.safe_text is None
    assert invalid_result.failure_kind is CitationGuardFailureKind.REPAIR_STILL_INVALID
    assert len(invalid_gateway.calls) == 1
    assert (
        failed_result.failure_kind
        is CitationGuardFailureKind.REPAIR_PROVIDER_UNAVAILABLE
    )
    assert len(failed_gateway.calls) == 1


@pytest.mark.asyncio
async def test_guard_routes_a_schema_failure_to_human_review_without_a_second_repair() -> (
    None
):
    gateway = _CitationRepairGateway(
        SchemaValidationError(
            "schema invalid",
            response_text='{"revised_text":42}',
            validation_errors=(),
        )
    )

    result = await verify_and_repair_citations(
        "The maximum charge is $1,250. [C1]",
        envelope=_envelope(),
        gateway=gateway,
    )

    assert result.status is CitationGuardStatus.HUMAN_REVIEW_REQUIRED
    assert result.failure_kind is CitationGuardFailureKind.REPAIR_SCHEMA_VALIDATION
    assert len(gateway.calls) == 1
