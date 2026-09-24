"""Regression coverage for proposal-only dispatch and deterministic vendors."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import cast
from uuid import UUID

import pytest

from brain.agents.diagnostician import DiagnosticAssessment, RecommendedAction
from brain.agents.dispatch import (
    DispatchFailureKind,
    DispatchFulfillment,
    DispatchProposal,
    DispatchRequest,
    DispatchStatus,
    PartsAvailability,
    ResponsibleParty,
    ServiceWindow,
    Trade,
    VendorCandidate,
    VendorEligibility,
    VendorIneligibilityReason,
    evaluate_vendor_candidates,
    plan_dispatch,
)
from brain.agents.intake import AccessWindow, TicketFacts, TicketIntent
from brain.gateway.client import (
    GatewayError,
    RenderedPrompt,
    SchemaValidationError,
    TaskClass,
)


_EVALUATED_AT = datetime(2026, 9, 23, 9, tzinfo=UTC)
_PREFERRED_WINDOW = ServiceWindow(
    start=datetime(2026, 9, 24, 10, tzinfo=UTC),
    end=datetime(2026, 9, 24, 12, tzinfo=UTC),
)


class _DispatchGateway:
    def __init__(self, result: DispatchProposal | Exception) -> None:
        self._result = result
        self.calls: list[tuple[TaskClass, RenderedPrompt, type[DispatchProposal]]] = []

    async def complete(
        self,
        task: TaskClass,
        prompt: RenderedPrompt,
        schema: type[DispatchProposal],
    ) -> DispatchProposal:
        self.calls.append((task, prompt, schema))
        if isinstance(self._result, Exception):
            raise self._result
        return self._result


def _facts(
    *, preferred_window: ServiceWindow | None = _PREFERRED_WINDOW
) -> TicketFacts:
    return TicketFacts(
        intent=TicketIntent.MAINTENANCE,
        category="plumbing",
        symptom_summary="Kitchen sink backs up when the dishwasher drains.",
        affected_asset="kitchen sink drain",
        access_permission=True,
        pets_present=False,
        preferred_access_window=(
            AccessWindow(start=preferred_window.start, end=preferred_window.end)
            if preferred_window is not None
            else None
        ),
    )


def _diagnosis() -> DiagnosticAssessment:
    return DiagnosticAssessment(
        likely_cause="The kitchen sink drain may have a partial blockage.",
        cause_provenance_ids=("[C1]",),
        recommended_actions=(
            RecommendedAction(
                action="Inspect the kitchen sink trap and branch drain.",
                rationale="The reported backup is consistent with a drain restriction.",
                provenance_ids=("[C1]",),
            ),
        ),
    )


def _candidate(
    vendor_id: str,
    *,
    trade: Trade = Trade.PLUMBING,
    active: bool = True,
    region_codes: tuple[str, ...] = ("US-VA-ARLINGTON",),
    insurance_expires_on: date | None = date(2027, 1, 1),
    acceptance_rate: Decimal = Decimal("0.80"),
    first_time_fix_rate: Decimal = Decimal("0.80"),
    available_windows: tuple[ServiceWindow, ...] = (_PREFERRED_WINDOW,),
    parts_availability: PartsAvailability = PartsAvailability.READY,
    estimated_cost_cents: int | None = 20000,
) -> VendorCandidate:
    return VendorCandidate(
        vendor_id=UUID(vendor_id),
        trade=trade,
        active=active,
        service_region_codes=region_codes,
        insurance_expires_on=insurance_expires_on,
        acceptance_rate=acceptance_rate,
        first_time_fix_rate=first_time_fix_rate,
        available_windows=available_windows,
        parts_availability=parts_availability,
        estimated_cost_cents=estimated_cost_cents,
    )


def _request(
    *,
    candidates: tuple[VendorCandidate, ...] = (),
    in_house_trades: tuple[Trade, ...] = (),
    provenance_ids: tuple[str, ...] = ("[C1]", "[F1]"),
) -> DispatchRequest:
    return DispatchRequest(
        ticket_facts=_facts(),
        diagnosis=_diagnosis(),
        grounded_context=(
            "[C1] Dishwasher-linked backups can indicate a drain restriction.\n"
            "[F1] Unit 4B has a kitchen sink drain asset."
        ),
        provenance_ids=provenance_ids,
        property_region_code=" us-va-arlington ",
        evaluated_at=_EVALUATED_AT,
        in_house_trades=in_house_trades,
        vendor_candidates=candidates,
    )


def _proposal(*, fulfillment: DispatchFulfillment) -> DispatchProposal:
    return DispatchProposal(
        trade=Trade.PLUMBING,
        fulfillment=fulfillment,
        scope_summary="Assess the reported kitchen sink drain backup.",
        parts_hint=("P-trap assembly",),
        responsible_party=ResponsibleParty.UNDETERMINED,
        provenance_ids=("[C1]", "[F1]"),
    )


@pytest.mark.asyncio
async def test_vendor_selection_excludes_expired_and_out_of_area_candidates() -> None:
    expired = _candidate(
        "00000000-0000-0000-0000-000000000001",
        insurance_expires_on=date(2026, 9, 22),
        acceptance_rate=Decimal("1.00"),
        first_time_fix_rate=Decimal("1.00"),
        estimated_cost_cents=1,
    )
    outside_area = _candidate(
        "00000000-0000-0000-0000-000000000002",
        region_codes=("US-MD-MONTGOMERY",),
        acceptance_rate=Decimal("1.00"),
        first_time_fix_rate=Decimal("1.00"),
        estimated_cost_cents=1,
    )
    lower_scored = _candidate(
        "00000000-0000-0000-0000-000000000003",
        acceptance_rate=Decimal("0.80"),
        first_time_fix_rate=Decimal("0.80"),
        parts_availability=PartsAvailability.ORDER_REQUIRED,
        estimated_cost_cents=30000,
    )
    winner = _candidate(
        "00000000-0000-0000-0000-000000000004",
        acceptance_rate=Decimal("0.60"),
        first_time_fix_rate=Decimal("0.90"),
        parts_availability=PartsAvailability.READY,
        estimated_cost_cents=10000,
    )
    gateway = _DispatchGateway(_proposal(fulfillment=DispatchFulfillment.VENDOR))

    result = await plan_dispatch(
        _request(candidates=(expired, outside_area, lower_scored, winner)),
        gateway=gateway,
    )

    assert result.status is DispatchStatus.PROPOSED
    assert result.plan is not None
    assert result.plan.selected_vendor_id == winner.vendor_id
    evaluations = {item.vendor_id: item for item in result.plan.vendor_evaluations}
    assert evaluations[expired.vendor_id].eligibility is VendorEligibility.INELIGIBLE
    assert (
        VendorIneligibilityReason.EXPIRED_INSURANCE
        in evaluations[expired.vendor_id].ineligibility_reasons
    )
    assert (
        evaluations[outside_area.vendor_id].eligibility is VendorEligibility.INELIGIBLE
    )
    assert (
        VendorIneligibilityReason.OUTSIDE_SERVICE_AREA
        in evaluations[outside_area.vendor_id].ineligibility_reasons
    )
    winner_evaluation = evaluations[winner.vendor_id]
    assert winner_evaluation.score is not None
    assert winner_evaluation.score.total == Decimal("83.00")
    assert gateway.calls[0][0] is TaskClass.DISPATCH_PLANNING
    assert str(expired.vendor_id) not in gateway.calls[0][1].dynamic_suffix
    assert "cannot create a work order" in gateway.calls[0][1].static_prefix


@pytest.mark.asyncio
async def test_in_house_proposal_never_selects_or_evaluates_a_vendor() -> None:
    gateway = _DispatchGateway(_proposal(fulfillment=DispatchFulfillment.IN_HOUSE))
    candidate = _candidate("00000000-0000-0000-0000-000000000001")

    result = await plan_dispatch(
        _request(candidates=(candidate,), in_house_trades=(Trade.PLUMBING,)),
        gateway=gateway,
    )

    assert result.status is DispatchStatus.PROPOSED
    assert result.plan is not None
    assert result.plan.selected_vendor_id is None
    assert result.plan.proposed_window is None
    assert result.plan.vendor_evaluations == ()


@pytest.mark.asyncio
async def test_dispatch_withholds_proposal_for_missing_evidence_or_invalid_routes() -> (
    None
):
    empty_evidence_gateway = _DispatchGateway(
        _proposal(fulfillment=DispatchFulfillment.VENDOR)
    )
    no_evidence_result = await plan_dispatch(
        _request(provenance_ids=()), gateway=empty_evidence_gateway
    )
    unavailable_in_house_gateway = _DispatchGateway(
        _proposal(fulfillment=DispatchFulfillment.IN_HOUSE)
    )
    unavailable_in_house_result = await plan_dispatch(
        _request(), gateway=unavailable_in_house_gateway
    )
    unsupported_citation = _proposal(fulfillment=DispatchFulfillment.VENDOR).model_copy(
        update={"provenance_ids": ("[C9]",)}
    )
    unsupported_citation_gateway = _DispatchGateway(unsupported_citation)
    unsupported_citation_result = await plan_dispatch(
        _request(), gateway=unsupported_citation_gateway
    )

    assert no_evidence_result.failure_kind is DispatchFailureKind.INSUFFICIENT_EVIDENCE
    assert empty_evidence_gateway.calls == []
    assert (
        unavailable_in_house_result.failure_kind
        is DispatchFailureKind.IN_HOUSE_TRADE_UNAVAILABLE
    )
    assert (
        unsupported_citation_result.failure_kind
        is DispatchFailureKind.UNSUPPORTED_CITATION
    )


@pytest.mark.asyncio
async def test_dispatch_routes_provider_and_schema_failures_to_human_review() -> None:
    schema_gateway = _DispatchGateway(
        SchemaValidationError(
            "schema invalid",
            response_text='{"trade":42}',
            validation_errors=(),
        )
    )
    provider_gateway = _DispatchGateway(GatewayError("gateway unavailable"))

    schema_result = await plan_dispatch(_request(), gateway=schema_gateway)
    provider_result = await plan_dispatch(_request(), gateway=provider_gateway)

    assert schema_result.failure_kind is DispatchFailureKind.SCHEMA_VALIDATION
    assert provider_result.failure_kind is DispatchFailureKind.PROVIDER_UNAVAILABLE


def test_vendor_ties_and_window_constraints_are_deterministic() -> None:
    first = _candidate("00000000-0000-0000-0000-000000000001")
    second = _candidate("00000000-0000-0000-0000-000000000002")
    no_overlap = _candidate(
        "00000000-0000-0000-0000-000000000003",
        available_windows=(
            ServiceWindow(
                start=_PREFERRED_WINDOW.end + timedelta(hours=1),
                end=_PREFERRED_WINDOW.end + timedelta(hours=3),
            ),
        ),
    )

    evaluations = evaluate_vendor_candidates(
        _request(candidates=(second, no_overlap, first)), trade=Trade.PLUMBING
    )

    assert [item.vendor_id for item in evaluations] == [
        first.vendor_id,
        second.vendor_id,
        no_overlap.vendor_id,
    ]
    assert evaluations[2].eligibility is VendorEligibility.INELIGIBLE
    assert evaluations[2].ineligibility_reasons == (
        VendorIneligibilityReason.NO_MATCHING_WINDOW,
    )
    assert evaluations[0].score == evaluations[1].score


@pytest.mark.asyncio
async def test_dispatch_uses_vendor_id_as_the_stable_tie_breaker_and_abstains_when_none_qualify() -> (
    None
):
    first = _candidate("00000000-0000-0000-0000-000000000001")
    second = _candidate("00000000-0000-0000-0000-000000000002")
    tie_gateway = _DispatchGateway(_proposal(fulfillment=DispatchFulfillment.VENDOR))
    tie_result = await plan_dispatch(
        _request(candidates=(second, first)), gateway=tie_gateway
    )
    expired = _candidate(
        "00000000-0000-0000-0000-000000000003",
        insurance_expires_on=date(2026, 9, 22),
    )
    outside_area = _candidate(
        "00000000-0000-0000-0000-000000000004",
        region_codes=("US-MD-MONTGOMERY",),
    )
    no_vendor_gateway = _DispatchGateway(
        _proposal(fulfillment=DispatchFulfillment.VENDOR)
    )
    no_vendor_result = await plan_dispatch(
        _request(candidates=(expired, outside_area)), gateway=no_vendor_gateway
    )

    assert tie_result.plan is not None
    assert tie_result.plan.selected_vendor_id == first.vendor_id
    assert no_vendor_result.status is DispatchStatus.HUMAN_REVIEW_REQUIRED
    assert no_vendor_result.failure_kind is DispatchFailureKind.NO_ELIGIBLE_VENDOR


def test_dispatch_input_rejects_naive_times_and_duplicate_vendor_snapshots() -> None:
    candidate = _candidate("00000000-0000-0000-0000-000000000001")
    with pytest.raises(ValueError, match="timezone"):
        DispatchRequest(
            ticket_facts=_facts(),
            diagnosis=_diagnosis(),
            grounded_context="[C1] grounded.",
            provenance_ids=("[C1]",),
            property_region_code="US-VA-ARLINGTON",
            evaluated_at=datetime(2026, 9, 23, 9),
        )
    with pytest.raises(ValueError, match="duplicate vendor"):
        _request(candidates=(candidate, candidate))
    with pytest.raises(ValueError, match="bracketed C or F"):
        DispatchProposal(
            trade=Trade.PLUMBING,
            fulfillment=DispatchFulfillment.VENDOR,
            scope_summary="Assess the drain.",
            responsible_party=ResponsibleParty.UNDETERMINED,
            provenance_ids=cast(tuple[str, ...], ("C1",)),
        )
