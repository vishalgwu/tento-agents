"""Model-free ticket triage used when every model provider is unavailable.

The caller persists the ticket and obtains its number before entering this
mode.  This module then uses only deterministic safety rules, creates no work
order, and marks every result for human escalation.
"""

from __future__ import annotations

import re
from enum import Enum
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from brain.agents.p0_protocol import (
    P0DeliveryStatus,
    P0PageRequest,
    P0PagingTransport,
    build_p0_page_plan,
    dispatch_p0_from_orchestrator,
)
from brain.agents.safety import (
    ModelOpinionStatus,
    SafetyVerdict,
    screen_deterministic_safety,
)


class TicketPriority(str, Enum):
    """The frozen priority vocabulary used by rules-only triage."""

    P0 = "p0"
    P1 = "p1"
    P2 = "p2"
    P3 = "p3"


class DegradedTicketStatus(str, Enum):
    """Rules-only tickets always require an authorised human follow-up."""

    ESCALATED = "escalated"


_ACKNOWLEDGEMENT_TEMPLATE = (
    "Your maintenance request has been recorded as ticket {ticket_number}. "
    "It has been escalated for human review. If there is immediate danger, call "
    "emergency services."
)
_CATEGORY_DEFAULTS: dict[str, tuple[TicketPriority, int]] = {
    "hvac": (TicketPriority.P1, 24 * 60),
    "electrical": (TicketPriority.P1, 24 * 60),
    "restoration": (TicketPriority.P1, 24 * 60),
    "plumbing": (TicketPriority.P2, 72 * 60),
    "appliance": (TicketPriority.P2, 72 * 60),
    "pest_control": (TicketPriority.P2, 72 * 60),
    "general_maintenance": (TicketPriority.P3, 5 * 24 * 60),
    "locksmith": (TicketPriority.P2, 72 * 60),
    "roofing": (TicketPriority.P2, 72 * 60),
}
_DEFAULT_CATEGORY: str = "other"
_DEFAULT_SLA_MINUTES: int = 72 * 60


class RulesOnlyRequest(BaseModel):
    """Persisted ticket facts permitted in the no-model fallback path."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    org_id: UUID
    ticket_id: UUID
    ticket_number: str = Field(min_length=1, max_length=80)
    resident_report: str = Field(min_length=1, max_length=50_000)
    photo_captions: tuple[str, ...] = Field(default=(), max_length=32)
    category: str | None = Field(default=None, max_length=80)

    @field_validator("ticket_number")
    @classmethod
    def _validate_ticket_number(cls, value: str) -> str:
        if value != value.strip() or any(
            not character.isprintable() for character in value
        ):
            raise ValueError("ticket_number must be a non-blank, single-line reference")
        return value

    @field_validator("resident_report")
    @classmethod
    def _validate_report(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("resident_report must be non-blank")
        return value

    @field_validator("photo_captions")
    @classmethod
    def _validate_captions(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if any(not caption.strip() or len(caption) > 4_000 for caption in value):
            raise ValueError(
                "photo captions must be non-blank strings of at most 4,000 characters"
            )
        return value


class RulesOnlyResult(BaseModel):
    """Safe, non-autonomous output from the model-provider outage path."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    ticket_number: str
    ticket_status: DegradedTicketStatus
    decision_mode: str
    execution_permitted: bool
    normalized_category: str
    priority: TicketPriority
    default_sla_minutes: int = Field(ge=0)
    acknowledgement: str
    safety: SafetyVerdict
    p0_delivery_statuses: tuple[P0DeliveryStatus, ...] = ()

    @model_validator(mode="after")
    def _enforce_non_autonomous_outcome(self) -> RulesOnlyResult:
        if self.ticket_status is not DegradedTicketStatus.ESCALATED:
            raise ValueError("rules-only tickets must be escalated")
        if self.decision_mode != "escalate" or self.execution_permitted:
            raise ValueError("rules-only mode cannot authorise execution")
        if self.acknowledgement != fixed_acknowledgement(self.ticket_number):
            raise ValueError("rules-only acknowledgement must use the fixed template")
        if self.priority is TicketPriority.P0:
            if not self.safety.p0 or self.default_sla_minutes != 0:
                raise ValueError(
                    "P0 requires deterministic safety and immediate handling"
                )
        elif self.safety.p0:
            raise ValueError("a deterministic P0 signal requires P0 priority")
        if self.safety.p0 != bool(self.p0_delivery_statuses):
            raise ValueError("P0 delivery statuses must be present exactly for P0")
        return self


async def run_rules_only(
    request: RulesOnlyRequest,
    *,
    p0_transport: P0PagingTransport,
    demo_mode: bool,
) -> RulesOnlyResult:
    """Safely acknowledge and escalate a ticket without any model dependency."""

    safety = _deterministic_safety_verdict(request)
    p0_delivery_statuses: tuple[P0DeliveryStatus, ...] = ()
    if safety.p0:
        p0_result = await dispatch_p0_from_orchestrator(
            build_p0_page_plan(
                P0PageRequest(
                    org_id=request.org_id,
                    ticket_id=request.ticket_id,
                    ticket_number=request.ticket_number,
                ),
                safety,
            ),
            transport=p0_transport,
            demo_mode=demo_mode,
        )
        p0_delivery_statuses = tuple(receipt.status for receipt in p0_result.receipts)
        priority = TicketPriority.P0
        default_sla_minutes = 0
    else:
        priority, default_sla_minutes = category_default_sla(request.category)
    return RulesOnlyResult(
        ticket_number=request.ticket_number,
        ticket_status=DegradedTicketStatus.ESCALATED,
        decision_mode="escalate",
        execution_permitted=False,
        normalized_category=normalize_category(request.category),
        priority=priority,
        default_sla_minutes=default_sla_minutes,
        acknowledgement=fixed_acknowledgement(request.ticket_number),
        safety=safety,
        p0_delivery_statuses=p0_delivery_statuses,
    )


def category_default_sla(category: str | None) -> tuple[TicketPriority, int]:
    """Return an operational default, never a substitute for controlling law."""

    return _CATEGORY_DEFAULTS.get(
        normalize_category(category), (TicketPriority.P2, _DEFAULT_SLA_MINUTES)
    )


def fixed_acknowledgement(ticket_number: str) -> str:
    """Render the only resident-facing copy available in rules-only mode."""

    return _ACKNOWLEDGEMENT_TEMPLATE.format(ticket_number=ticket_number)


def normalize_category(category: str | None) -> str:
    """Normalize a display/category hint without treating it as evidence."""

    if category is None:
        return _DEFAULT_CATEGORY
    normalized = re.sub(r"[^a-z0-9]+", "_", category.casefold()).strip("_")
    return normalized or _DEFAULT_CATEGORY


def _deterministic_safety_verdict(request: RulesOnlyRequest) -> SafetyVerdict:
    signals = screen_deterministic_safety(
        request.resident_report, photo_captions=request.photo_captions
    )
    categories = tuple(dict.fromkeys(signal.category for signal in signals))
    return SafetyVerdict(
        p0=bool(categories),
        categories=categories,
        deterministic_signals=signals,
        model_categories=(),
        model_opinion_status=(
            ModelOpinionStatus.SKIPPED_DETERMINISTIC_P0
            if categories
            else ModelOpinionStatus.UNAVAILABLE
        ),
    )
