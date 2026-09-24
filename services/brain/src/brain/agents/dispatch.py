"""Proposal-only dispatch planning and deterministic vendor selection.

The model sees grounded ticket evidence and may propose only a trade and a
fulfillment route.  Vendor eligibility, ranking, and the proposed service
window are deterministic functions of caller-supplied operational snapshots.
This module has no database, HTTP, filesystem, tool, or orchestration import;
it cannot create a work order, schedule a visit, or contact a vendor.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterable
from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from typing import Final, Protocol
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from brain.agents.diagnostician import DiagnosticAssessment
from brain.agents.intake import AccessWindow, TicketFacts
from brain.gateway.client import (
    RenderedPrompt,
    SchemaValidationError,
    TaskClass,
    load_builtin_prompt,
)


_PROVENANCE_ID_PATTERN: Final = re.compile(r"^\[(?:C|F)[1-9]\d*\]$")
_ZERO: Final = Decimal("0")
_ONE: Final = Decimal("1")
_HUNDRED: Final = Decimal("100")
_ACCEPT_RATE_WEIGHT: Final = Decimal("35")
_FIRST_TIME_FIX_WEIGHT: Final = Decimal("30")
_WINDOW_WEIGHT: Final = Decimal("15")
_PARTS_WEIGHT: Final = Decimal("10")
_COST_WEIGHT: Final = Decimal("10")


class Trade(str, Enum):
    """Frozen ``trade`` vocabulary shared with the database contract."""

    GENERAL_MAINTENANCE = "general_maintenance"
    PLUMBING = "plumbing"
    ELECTRICAL = "electrical"
    HVAC = "hvac"
    APPLIANCE = "appliance"
    PEST_CONTROL = "pest_control"
    RESTORATION = "restoration"
    ROOFING = "roofing"
    LOCKSMITH = "locksmith"
    OTHER = "other"


class DispatchFulfillment(str, Enum):
    """The only fulfillment routes this agent may propose."""

    IN_HOUSE = "in_house"
    VENDOR = "vendor"


class ResponsibleParty(str, Enum):
    """Frozen proposal vocabulary; it does not establish financial liability."""

    OWNER = "owner"
    RESIDENT = "resident"
    VENDOR = "vendor"
    UNDETERMINED = "undetermined"


class PartsAvailability(str, Enum):
    """Snapshot of whether the proposed work's parts can be supplied."""

    READY = "ready"
    ORDER_REQUIRED = "order_required"
    UNKNOWN = "unknown"
    UNAVAILABLE = "unavailable"


_PARTS_SCORE: Final[dict[PartsAvailability, Decimal]] = {
    PartsAvailability.READY: _ONE,
    PartsAvailability.ORDER_REQUIRED: Decimal("0.50"),
    PartsAvailability.UNKNOWN: Decimal("0.25"),
    PartsAvailability.UNAVAILABLE: _ZERO,
}


class ServiceWindow(BaseModel):
    """A timezone-aware service interval used only for a dispatch proposal."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    start: datetime
    end: datetime

    @model_validator(mode="after")
    def _require_ordered_timezone_aware_window(self) -> ServiceWindow:
        if self.start.tzinfo is None or self.start.utcoffset() is None:
            raise ValueError("service window start must include a timezone")
        if self.end.tzinfo is None or self.end.utcoffset() is None:
            raise ValueError("service window end must include a timezone")
        if self.end <= self.start:
            raise ValueError("service window end must be after start")
        return self


class VendorCandidate(BaseModel):
    """The caller-supplied, non-authoritative operational snapshot for one vendor."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    vendor_id: UUID
    trade: Trade
    active: bool
    service_region_codes: tuple[str, ...] = Field(min_length=1, max_length=100)
    insurance_expires_on: date | None = None
    acceptance_rate: Decimal = Field(ge=_ZERO, le=_ONE)
    first_time_fix_rate: Decimal = Field(ge=_ZERO, le=_ONE)
    available_windows: tuple[ServiceWindow, ...] = Field(default=(), max_length=100)
    parts_availability: PartsAvailability
    estimated_cost_cents: int | None = Field(default=None, ge=0)

    @field_validator("service_region_codes")
    @classmethod
    def _normalize_service_regions(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        normalized = tuple(_normalize_region_code(region) for region in value)
        if len(normalized) != len(set(normalized)):
            raise ValueError("service_region_codes must not contain duplicates")
        return normalized

    @field_validator("available_windows")
    @classmethod
    def _require_distinct_windows(
        cls, value: tuple[ServiceWindow, ...]
    ) -> tuple[ServiceWindow, ...]:
        spans = tuple((window.start, window.end) for window in value)
        if len(spans) != len(set(spans)):
            raise ValueError("available_windows must not contain duplicates")
        return value


class DispatchProposal(BaseModel):
    """The model's cited routing proposal, deliberately without a vendor ID."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    trade: Trade
    fulfillment: DispatchFulfillment
    scope_summary: str = Field(min_length=1, max_length=1_000)
    parts_hint: tuple[str, ...] = Field(default=(), max_length=12)
    responsible_party: ResponsibleParty
    provenance_ids: tuple[str, ...] = Field(min_length=1, max_length=16)

    @field_validator("scope_summary")
    @classmethod
    def _require_non_blank_scope(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("scope_summary must not be blank")
        return value

    @field_validator("parts_hint")
    @classmethod
    def _validate_parts_hint(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if any(not part.strip() for part in value):
            raise ValueError("parts_hint must not contain blank entries")
        if len(value) != len(set(value)):
            raise ValueError("parts_hint must not contain duplicates")
        return value

    @field_validator("provenance_ids")
    @classmethod
    def _validate_provenance_ids(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        _validate_provenance_ids(value)
        return value


class DispatchRequest(BaseModel):
    """Everything dispatch needs must be pushed by the authorized caller."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    ticket_facts: TicketFacts
    diagnosis: DiagnosticAssessment
    grounded_context: str = Field(min_length=1, max_length=100_000)
    provenance_ids: tuple[str, ...] = Field(default=(), max_length=100)
    property_region_code: str = Field(min_length=1, max_length=100)
    evaluated_at: datetime
    in_house_trades: tuple[Trade, ...] = Field(default=())
    vendor_candidates: tuple[VendorCandidate, ...] = Field(default=(), max_length=200)

    @field_validator("grounded_context")
    @classmethod
    def _require_non_blank_context(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("grounded_context must be non-blank")
        return value

    @field_validator("provenance_ids")
    @classmethod
    def _validate_pushed_provenance_ids(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        _validate_provenance_ids(value)
        return value

    @field_validator("property_region_code")
    @classmethod
    def _normalize_property_region(cls, value: str) -> str:
        return _normalize_region_code(value)

    @field_validator("evaluated_at")
    @classmethod
    def _require_timezone_aware_evaluation_time(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("evaluated_at must include a timezone")
        return value

    @field_validator("in_house_trades")
    @classmethod
    def _require_distinct_in_house_trades(
        cls, value: tuple[Trade, ...]
    ) -> tuple[Trade, ...]:
        if len(value) != len(set(value)):
            raise ValueError("in_house_trades must not contain duplicates")
        return value

    @model_validator(mode="after")
    def _require_coherent_pushed_evidence_and_vendors(self) -> DispatchRequest:
        missing = [
            provenance_id
            for provenance_id in self.provenance_ids
            if provenance_id not in self.grounded_context
        ]
        if missing:
            raise ValueError("provenance_ids must appear in grounded_context")
        vendor_ids = tuple(candidate.vendor_id for candidate in self.vendor_candidates)
        if len(vendor_ids) != len(set(vendor_ids)):
            raise ValueError("vendor_candidates must not contain duplicate vendor IDs")
        preferred_window = self.ticket_facts.preferred_access_window
        if preferred_window is not None:
            _validate_access_window_timezone(preferred_window)
        return self


class VendorEligibility(str, Enum):
    """Whether a candidate can be considered in a proposal."""

    ELIGIBLE = "eligible"
    INELIGIBLE = "ineligible"


class VendorIneligibilityReason(str, Enum):
    """Hard eligibility gates applied before a vendor score is calculated."""

    INACTIVE = "inactive"
    TRADE_MISMATCH = "trade_mismatch"
    EXPIRED_INSURANCE = "expired_insurance"
    OUTSIDE_SERVICE_AREA = "outside_service_area"
    NO_AVAILABLE_WINDOW = "no_available_window"
    NO_MATCHING_WINDOW = "no_matching_window"


class VendorScore(BaseModel):
    """Auditable normalized components for the fixed 35/30/15/10/10 score."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    acceptance_rate: Decimal = Field(ge=_ZERO, le=_HUNDRED)
    first_time_fix_rate: Decimal = Field(ge=_ZERO, le=_HUNDRED)
    window: Decimal = Field(ge=_ZERO, le=_HUNDRED)
    parts: Decimal = Field(ge=_ZERO, le=_HUNDRED)
    cost_estimate: Decimal = Field(ge=_ZERO, le=_HUNDRED)
    total: Decimal = Field(ge=_ZERO, le=_HUNDRED)


class VendorEvaluation(BaseModel):
    """Eligibility result and score for one candidate; no scheduling occurs."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    vendor_id: UUID
    eligibility: VendorEligibility
    ineligibility_reasons: tuple[VendorIneligibilityReason, ...] = Field(default=())
    proposed_window: ServiceWindow | None = None
    score: VendorScore | None = None

    @model_validator(mode="after")
    def _enforce_eligibility_shape(self) -> VendorEvaluation:
        if self.eligibility is VendorEligibility.ELIGIBLE:
            if (
                self.ineligibility_reasons
                or self.proposed_window is None
                or self.score is None
            ):
                raise ValueError("an eligible vendor requires a window and score only")
        elif self.proposed_window is not None or self.score is not None:
            raise ValueError("an ineligible vendor must not have a window or score")
        return self


class DispatchPlan(BaseModel):
    """A proposal for review, never a work-order or vendor-contact command."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    proposal: DispatchProposal
    selected_vendor_id: UUID | None = None
    proposed_window: ServiceWindow | None = None
    vendor_evaluations: tuple[VendorEvaluation, ...] = Field(default=())

    @model_validator(mode="after")
    def _enforce_fulfillment_shape(self) -> DispatchPlan:
        if self.proposal.fulfillment is DispatchFulfillment.IN_HOUSE:
            if (
                self.selected_vendor_id is not None
                or self.proposed_window is not None
                or self.vendor_evaluations
            ):
                raise ValueError(
                    "an in-house proposal must not include vendor selection"
                )
        elif self.selected_vendor_id is None or self.proposed_window is None:
            raise ValueError("a vendor proposal requires a selected vendor and window")
        return self


class DispatchStatus(str, Enum):
    """Terminal states that may be consumed by the later approval gate."""

    PROPOSED = "proposed"
    HUMAN_REVIEW_REQUIRED = "human_review_required"


class DispatchFailureKind(str, Enum):
    """Why dispatch safely withholds a proposal."""

    INSUFFICIENT_EVIDENCE = "insufficient_evidence"
    SCHEMA_VALIDATION = "schema_validation"
    PROVIDER_UNAVAILABLE = "provider_unavailable"
    UNSUPPORTED_CITATION = "unsupported_citation"
    IN_HOUSE_TRADE_UNAVAILABLE = "in_house_trade_unavailable"
    NO_ELIGIBLE_VENDOR = "no_eligible_vendor"


class DispatchResult(BaseModel):
    """Safe dispatch result with a plan or a typed human-review state."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    status: DispatchStatus
    plan: DispatchPlan | None
    failure_kind: DispatchFailureKind | None = None

    @model_validator(mode="after")
    def _enforce_terminal_shape(self) -> DispatchResult:
        if self.status is DispatchStatus.PROPOSED:
            if self.plan is None or self.failure_kind is not None:
                raise ValueError("a proposed dispatch result requires a plan only")
        elif self.plan is not None or self.failure_kind is None:
            raise ValueError("human review requires a failure kind and no plan")
        return self


class DispatchGateway(Protocol):
    """The only external capability available to the proposal agent."""

    async def complete(
        self,
        task: TaskClass,
        prompt: RenderedPrompt,
        schema: type[DispatchProposal],
    ) -> DispatchProposal:
        """Return one gateway-audited, schema-validated routing proposal."""


async def plan_dispatch(
    request: DispatchRequest,
    *,
    gateway: DispatchGateway,
) -> DispatchResult:
    """Produce a cited routing proposal and deterministically select a vendor.

    The model cannot see vendor candidates and cannot name one.  After it
    chooses the trade and in-house/vendor route, this function filters vendors
    for hard safety/coverage constraints and ranks only eligible candidates.
    No outcome here persists data, creates a work order, schedules a visit, or
    contacts an in-house technician or vendor.
    """

    if not request.provenance_ids:
        return _human_review(DispatchFailureKind.INSUFFICIENT_EVIDENCE)

    prompt = _render_dispatch_prompt(request)
    try:
        proposal = await gateway.complete(
            TaskClass.DISPATCH_PLANNING,
            prompt,
            DispatchProposal,
        )
    except SchemaValidationError:
        return _human_review(DispatchFailureKind.SCHEMA_VALIDATION)
    except Exception:
        return _human_review(DispatchFailureKind.PROVIDER_UNAVAILABLE)

    if not set(proposal.provenance_ids).issubset(set(request.provenance_ids)):
        return _human_review(DispatchFailureKind.UNSUPPORTED_CITATION)

    if proposal.fulfillment is DispatchFulfillment.IN_HOUSE:
        if proposal.trade not in request.in_house_trades:
            return _human_review(DispatchFailureKind.IN_HOUSE_TRADE_UNAVAILABLE)
        return DispatchResult(
            status=DispatchStatus.PROPOSED,
            plan=DispatchPlan(proposal=proposal),
        )

    evaluations = evaluate_vendor_candidates(request, trade=proposal.trade)
    eligible = tuple(
        evaluation
        for evaluation in evaluations
        if evaluation.eligibility is VendorEligibility.ELIGIBLE
    )
    if not eligible:
        return _human_review(DispatchFailureKind.NO_ELIGIBLE_VENDOR)

    winner = min(
        eligible,
        key=lambda evaluation: (
            -_require_score(evaluation).total,
            str(evaluation.vendor_id),
        ),
    )
    return DispatchResult(
        status=DispatchStatus.PROPOSED,
        plan=DispatchPlan(
            proposal=proposal,
            selected_vendor_id=winner.vendor_id,
            proposed_window=winner.proposed_window,
            vendor_evaluations=evaluations,
        ),
    )


def evaluate_vendor_candidates(
    request: DispatchRequest,
    *,
    trade: Trade,
) -> tuple[VendorEvaluation, ...]:
    """Filter and score pushed vendor snapshots without touching persistence."""

    provisional: list[tuple[VendorCandidate, ServiceWindow, Decimal]] = []
    evaluations: dict[UUID, VendorEvaluation] = {}
    preferred_window = _preferred_service_window(
        request.ticket_facts.preferred_access_window
    )

    for candidate in sorted(
        request.vendor_candidates, key=lambda item: str(item.vendor_id)
    ):
        reasons = _ineligibility_reasons(
            candidate,
            request=request,
            trade=trade,
            preferred_window=preferred_window,
        )
        if reasons:
            evaluations[candidate.vendor_id] = VendorEvaluation(
                vendor_id=candidate.vendor_id,
                eligibility=VendorEligibility.INELIGIBLE,
                ineligibility_reasons=reasons,
            )
            continue
        selected_window, window_ratio = _select_window(
            candidate.available_windows,
            evaluated_at=request.evaluated_at,
            preferred_window=preferred_window,
        )
        provisional.append((candidate, selected_window, window_ratio))

    cost_scores = _cost_scores(candidate for candidate, _, _ in provisional)
    for candidate, selected_window, window_ratio in provisional:
        score = VendorScore(
            acceptance_rate=candidate.acceptance_rate * _ACCEPT_RATE_WEIGHT,
            first_time_fix_rate=candidate.first_time_fix_rate * _FIRST_TIME_FIX_WEIGHT,
            window=window_ratio * _WINDOW_WEIGHT,
            parts=_PARTS_SCORE[candidate.parts_availability] * _PARTS_WEIGHT,
            cost_estimate=cost_scores[candidate.vendor_id] * _COST_WEIGHT,
            total=(
                candidate.acceptance_rate * _ACCEPT_RATE_WEIGHT
                + candidate.first_time_fix_rate * _FIRST_TIME_FIX_WEIGHT
                + window_ratio * _WINDOW_WEIGHT
                + _PARTS_SCORE[candidate.parts_availability] * _PARTS_WEIGHT
                + cost_scores[candidate.vendor_id] * _COST_WEIGHT
            ),
        )
        evaluations[candidate.vendor_id] = VendorEvaluation(
            vendor_id=candidate.vendor_id,
            eligibility=VendorEligibility.ELIGIBLE,
            proposed_window=selected_window,
            score=score,
        )

    return tuple(
        evaluations[candidate.vendor_id]
        for candidate in sorted(
            request.vendor_candidates, key=lambda item: str(item.vendor_id)
        )
    )


def _ineligibility_reasons(
    candidate: VendorCandidate,
    *,
    request: DispatchRequest,
    trade: Trade,
    preferred_window: ServiceWindow | None,
) -> tuple[VendorIneligibilityReason, ...]:
    reasons: list[VendorIneligibilityReason] = []
    if not candidate.active:
        reasons.append(VendorIneligibilityReason.INACTIVE)
    if candidate.trade is not trade:
        reasons.append(VendorIneligibilityReason.TRADE_MISMATCH)
    if (
        candidate.insurance_expires_on is None
        or candidate.insurance_expires_on < request.evaluated_at.date()
    ):
        reasons.append(VendorIneligibilityReason.EXPIRED_INSURANCE)
    if request.property_region_code not in candidate.service_region_codes:
        reasons.append(VendorIneligibilityReason.OUTSIDE_SERVICE_AREA)
    future_windows = tuple(
        window
        for window in candidate.available_windows
        if window.end > request.evaluated_at
    )
    if not future_windows:
        reasons.append(VendorIneligibilityReason.NO_AVAILABLE_WINDOW)
    elif preferred_window is not None and not any(
        _overlap_microseconds(window, preferred_window) > 0 for window in future_windows
    ):
        reasons.append(VendorIneligibilityReason.NO_MATCHING_WINDOW)
    return tuple(reasons)


def _select_window(
    windows: tuple[ServiceWindow, ...],
    *,
    evaluated_at: datetime,
    preferred_window: ServiceWindow | None,
) -> tuple[ServiceWindow, Decimal]:
    future_windows = tuple(window for window in windows if window.end > evaluated_at)
    if preferred_window is None:
        return min(future_windows, key=lambda window: (window.start, window.end)), _ONE

    requested_duration = _duration_microseconds(preferred_window)
    ranked = tuple(
        (
            window,
            Decimal(_overlap_microseconds(window, preferred_window))
            / Decimal(requested_duration),
        )
        for window in future_windows
    )
    return min(
        ranked,
        key=lambda item: (-item[1], item[0].start, item[0].end),
    )


def _cost_scores(candidates: Iterable[VendorCandidate]) -> dict[UUID, Decimal]:
    candidate_values = tuple(candidates)
    known_costs = tuple(
        candidate.estimated_cost_cents
        for candidate in candidate_values
        if candidate.estimated_cost_cents is not None
    )
    if not known_costs:
        return {candidate.vendor_id: _ZERO for candidate in candidate_values}
    lowest = min(known_costs)
    highest = max(known_costs)
    if lowest == highest:
        return {
            candidate.vendor_id: _ONE
            if candidate.estimated_cost_cents is not None
            else _ZERO
            for candidate in candidate_values
        }
    return {
        candidate.vendor_id: (
            _ZERO
            if candidate.estimated_cost_cents is None
            else _ONE
            - Decimal(candidate.estimated_cost_cents - lowest)
            / Decimal(highest - lowest)
        )
        for candidate in candidate_values
    }


def _render_dispatch_prompt(request: DispatchRequest) -> RenderedPrompt:
    return load_builtin_prompt("dispatch-planning").render(
        {
            "ticket_facts_json": json.dumps(
                request.ticket_facts.model_dump(mode="json"),
                ensure_ascii=True,
                separators=(",", ":"),
                sort_keys=True,
            ),
            "diagnosis_json": json.dumps(
                request.diagnosis.model_dump(mode="json"),
                ensure_ascii=True,
                separators=(",", ":"),
                sort_keys=True,
            ),
            "grounded_context": request.grounded_context,
            "provenance_ids": request.provenance_ids,
            "in_house_trades": tuple(trade.value for trade in request.in_house_trades),
        },
        schema=DispatchProposal,
    )


def _preferred_service_window(window: AccessWindow | None) -> ServiceWindow | None:
    if window is None:
        return None
    if window.start is None or window.end is None:
        raise ValueError("preferred access windows must include start and end")
    return ServiceWindow(start=window.start, end=window.end)


def _validate_access_window_timezone(window: AccessWindow) -> None:
    if window.start is None or window.end is None:
        raise ValueError("preferred access windows must include start and end")
    if window.start.tzinfo is None or window.start.utcoffset() is None:
        raise ValueError("preferred access window start must include a timezone")
    if window.end.tzinfo is None or window.end.utcoffset() is None:
        raise ValueError("preferred access window end must include a timezone")


def _duration_microseconds(window: ServiceWindow) -> int:
    return int((window.end - window.start).total_seconds() * 1_000_000)


def _overlap_microseconds(left: ServiceWindow, right: ServiceWindow) -> int:
    start = max(left.start, right.start)
    end = min(left.end, right.end)
    if end <= start:
        return 0
    return int((end - start).total_seconds() * 1_000_000)


def _require_score(evaluation: VendorEvaluation) -> VendorScore:
    if evaluation.score is None:
        raise ValueError("eligible vendors must have a score")
    return evaluation.score


def _human_review(failure_kind: DispatchFailureKind) -> DispatchResult:
    return DispatchResult(
        status=DispatchStatus.HUMAN_REVIEW_REQUIRED,
        plan=None,
        failure_kind=failure_kind,
    )


def _normalize_region_code(value: str) -> str:
    normalized = value.strip().upper()
    if not normalized:
        raise ValueError("region codes must not be blank")
    return normalized


def _validate_provenance_ids(value: tuple[str, ...]) -> None:
    if len(value) != len(set(value)):
        raise ValueError("provenance_ids must not contain duplicates")
    if any(_PROVENANCE_ID_PATTERN.fullmatch(item) is None for item in value):
        raise ValueError("provenance_ids must use bracketed C or F identifiers")
