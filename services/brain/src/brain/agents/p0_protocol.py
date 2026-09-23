"""Deterministic P0 human paging with no model dependency.

Only the orchestrator may call :func:`dispatch_p0_from_orchestrator`, after a
``SafetyVerdict`` has selected the P0 path.  The protocol sends push, SMS, and
voice pages concurrently and deliberately contains no quiet-hours branch.
"""

from __future__ import annotations

import asyncio
import hashlib
from collections.abc import Sequence
from dataclasses import dataclass
from enum import Enum
from typing import Final, Protocol
from uuid import UUID

from brain.agents.safety import SafetyCategory, SafetyVerdict


class P0Channel(str, Enum):
    """Every independent channel used for immediate life-safety paging."""

    PUSH = "push"
    SMS = "sms"
    VOICE = "voice"


class P0DeliveryStatus(str, Enum):
    """A channel-level receipt state that is safe to persist in an audit log."""

    DELIVERED = "delivered"
    SUPPRESSED_DEMO = "suppressed_demo"
    FAILED = "failed"


P0_CHANNELS: tuple[P0Channel, ...] = (
    P0Channel.PUSH,
    P0Channel.SMS,
    P0Channel.VOICE,
)
P0_PAGE_TEMPLATE: Final[str] = (
    "P0 MAINTENANCE SAFETY ALERT\n"
    "Ticket: {ticket_number}\n"
    "Signals: {category_labels}\n"
    "Open the approved operations console immediately."
)
_CATEGORY_ORDER: Final = {
    category: index for index, category in enumerate(SafetyCategory)
}


@dataclass(frozen=True, slots=True)
class P0PageRequest:
    """Minimum safe data needed to route a P0 page to the approved human path."""

    org_id: UUID
    ticket_id: UUID
    ticket_number: str

    def __post_init__(self) -> None:
        if (
            not isinstance(self.ticket_number, str)
            or not self.ticket_number
            or self.ticket_number != self.ticket_number.strip()
            or len(self.ticket_number) > 80
            or any(not character.isprintable() for character in self.ticket_number)
        ):
            raise ValueError(
                "ticket_number must be a non-blank, single-line reference of at most 80 characters"
            )


@dataclass(frozen=True, slots=True)
class P0PagePlan:
    """A deterministic page command with a fixed message and three channels."""

    request: P0PageRequest
    categories: tuple[SafetyCategory, ...]
    message: str
    idempotency_key: str
    channels: tuple[P0Channel, ...] = P0_CHANNELS

    def __post_init__(self) -> None:
        if not self.categories:
            raise ValueError("a P0 page requires at least one safety category")
        if any(
            not isinstance(category, SafetyCategory) for category in self.categories
        ):
            raise ValueError("P0 page categories must be safety categories")
        if len(self.categories) != len(set(self.categories)):
            raise ValueError("P0 page categories must not contain duplicates")
        if self.categories != _ordered_categories(self.categories):
            raise ValueError("P0 page categories must use the fixed safety order")
        if self.channels != P0_CHANNELS:
            raise ValueError("a P0 page must use push, SMS, and voice together")
        if self.message != _fixed_page_message(self.request, self.categories):
            raise ValueError("a P0 page must use the fixed message template")
        if self.idempotency_key != _page_idempotency_key(self.request, self.categories):
            raise ValueError("P0 idempotency_key must match the fixed page payload")


@dataclass(frozen=True, slots=True)
class P0DeliveryReceipt:
    """One non-sensitive transport receipt for an append-only execution record."""

    channel: P0Channel
    status: P0DeliveryStatus
    provider_receipt: str | None = None
    error_kind: str | None = None

    def __post_init__(self) -> None:
        if self.status is P0DeliveryStatus.DELIVERED:
            if not self.provider_receipt:
                raise ValueError("a delivered P0 page requires a provider receipt")
            if self.error_kind is not None:
                raise ValueError("a delivered P0 page cannot contain an error kind")
        elif self.status is P0DeliveryStatus.FAILED:
            if not self.error_kind:
                raise ValueError("a failed P0 page requires a non-sensitive error kind")
            if self.provider_receipt is not None:
                raise ValueError("a failed P0 page cannot contain a provider receipt")
        elif self.status is P0DeliveryStatus.SUPPRESSED_DEMO:
            if self.provider_receipt is not None or self.error_kind is not None:
                raise ValueError("a demo-suppressed P0 page has no transport outcome")
        else:
            raise ValueError("P0 delivery status must be recognised")


@dataclass(frozen=True, slots=True)
class P0DispatchResult:
    """Complete page result; each channel is attempted even if another fails."""

    plan: P0PagePlan
    receipts: tuple[P0DeliveryReceipt, ...]

    def __post_init__(self) -> None:
        if tuple(receipt.channel for receipt in self.receipts) != self.plan.channels:
            raise ValueError("P0 receipts must cover every channel in plan order")


class P0PagingTransport(Protocol):
    """An approved on-call transport supplied by the orchestrator boundary."""

    async def send_p0_page(
        self,
        *,
        channel: P0Channel,
        message: str,
        idempotency_key: str,
    ) -> str:
        """Send one channel page and return the provider's opaque receipt ID."""


def build_p0_page_plan(request: P0PageRequest, verdict: SafetyVerdict) -> P0PagePlan:
    """Create the fixed all-channel page for a positive safety verdict.

    No source report text, resident identity, or model explanation enters the
    message.  The on-call human opens the authorised operations view using the
    ticket reference, where tenant-scoped information can be accessed safely.
    """

    if not verdict.p0:
        raise ValueError("cannot create a P0 page for a non-P0 safety verdict")
    categories = _ordered_categories(verdict.categories)
    message = _fixed_page_message(request, categories)
    idempotency_key = _page_idempotency_key(request, categories)
    return P0PagePlan(
        request=request,
        categories=categories,
        message=message,
        idempotency_key=idempotency_key,
    )


async def dispatch_p0_from_orchestrator(
    plan: P0PagePlan,
    *,
    transport: P0PagingTransport,
    demo_mode: bool,
) -> P0DispatchResult:
    """Dispatch all P0 channels concurrently, with demo transport suppression.

    This is intentionally the only side-effecting operation in the P0 module;
    callers must be the orchestrator after the deterministic safety transition.
    Quiet hours, user preferences, and model output do not participate in P0
    delivery.  A failing channel is recorded but never prevents the other two
    channels from being attempted.
    """

    if demo_mode:
        return P0DispatchResult(
            plan=plan,
            receipts=tuple(
                P0DeliveryReceipt(
                    channel=channel,
                    status=P0DeliveryStatus.SUPPRESSED_DEMO,
                )
                for channel in plan.channels
            ),
        )

    outcomes = await asyncio.gather(
        *(
            transport.send_p0_page(
                channel=channel,
                message=plan.message,
                idempotency_key=plan.idempotency_key,
            )
            for channel in plan.channels
        ),
        return_exceptions=True,
    )
    receipts = tuple(
        _receipt_for_outcome(channel, outcome)
        for channel, outcome in zip(plan.channels, outcomes, strict=True)
    )
    return P0DispatchResult(plan=plan, receipts=receipts)


def _receipt_for_outcome(channel: P0Channel, outcome: object) -> P0DeliveryReceipt:
    if isinstance(outcome, BaseException):
        return P0DeliveryReceipt(
            channel=channel,
            status=P0DeliveryStatus.FAILED,
            error_kind=type(outcome).__name__,
        )
    if not isinstance(outcome, str):
        return P0DeliveryReceipt(
            channel=channel,
            status=P0DeliveryStatus.FAILED,
            error_kind="InvalidProviderReceipt",
        )
    if not outcome.strip():
        return P0DeliveryReceipt(
            channel=channel,
            status=P0DeliveryStatus.FAILED,
            error_kind="EmptyProviderReceipt",
        )
    return P0DeliveryReceipt(
        channel=channel,
        status=P0DeliveryStatus.DELIVERED,
        provider_receipt=outcome,
    )


def _ordered_categories(
    categories: Sequence[SafetyCategory],
) -> tuple[SafetyCategory, ...]:
    return tuple(sorted(categories, key=_CATEGORY_ORDER.__getitem__))


def _fixed_page_message(
    request: P0PageRequest, categories: Sequence[SafetyCategory]
) -> str:
    return P0_PAGE_TEMPLATE.format(
        ticket_number=request.ticket_number,
        category_labels=", ".join(
            category.value.replace("_", " ") for category in categories
        ),
    )


def _page_idempotency_key(
    request: P0PageRequest, categories: Sequence[SafetyCategory]
) -> str:
    payload = "\x1f".join(
        (
            str(request.org_id),
            str(request.ticket_id),
            request.ticket_number,
            *(category.value for category in categories),
        )
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()
