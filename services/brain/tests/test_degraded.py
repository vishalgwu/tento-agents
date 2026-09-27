"""Regression coverage for the no-model rules-only maintenance fallback."""

from __future__ import annotations

from uuid import uuid4

import pytest

from brain.agents.p0_protocol import P0Channel, P0DeliveryStatus
from brain.degraded import (
    DegradedTicketStatus,
    RulesOnlyRequest,
    TicketPriority,
    category_default_sla,
    fixed_acknowledgement,
    run_rules_only,
)


class _P0Transport:
    def __init__(self) -> None:
        self.calls: list[P0Channel] = []

    async def send_p0_page(
        self,
        *,
        channel: P0Channel,
        message: str,
        idempotency_key: str,
    ) -> str:
        assert "Open the approved operations console immediately." in message
        assert len(idempotency_key) == 64
        self.calls.append(channel)
        return f"provider-{channel.value}"


def _request(**changes: object) -> RulesOnlyRequest:
    payload: dict[str, object] = {
        "org_id": uuid4(),
        "ticket_id": uuid4(),
        "ticket_number": "T-2026-0042",
        "resident_report": "The kitchen sink drains slowly after meals.",
        "category": "plumbing",
    }
    payload.update(changes)
    return RulesOnlyRequest.model_validate(payload)


@pytest.mark.asyncio
async def test_rules_only_acknowledges_and_escalates_without_executing() -> None:
    transport = _P0Transport()

    result = await run_rules_only(
        _request(resident_report="The refrigerator is not cooling consistently."),
        p0_transport=transport,
        demo_mode=False,
    )

    assert result.ticket_status is DegradedTicketStatus.ESCALATED
    assert result.decision_mode == "escalate"
    assert result.execution_permitted is False
    assert result.priority is TicketPriority.P2
    assert result.default_sla_minutes == 72 * 60
    assert result.acknowledgement == fixed_acknowledgement("T-2026-0042")
    assert result.p0_delivery_statuses == ()
    assert transport.calls == []
    assert "refrigerator" not in result.model_dump_json()


@pytest.mark.asyncio
async def test_gas_signal_pages_every_on_call_channel_without_a_model() -> None:
    transport = _P0Transport()

    result = await run_rules_only(
        _request(resident_report="There is a strong gas smell near the stove."),
        p0_transport=transport,
        demo_mode=False,
    )

    assert result.priority is TicketPriority.P0
    assert result.default_sla_minutes == 0
    assert result.safety.p0 is True
    assert transport.calls == [P0Channel.PUSH, P0Channel.SMS, P0Channel.VOICE]
    assert result.p0_delivery_statuses == (
        P0DeliveryStatus.DELIVERED,
        P0DeliveryStatus.DELIVERED,
        P0DeliveryStatus.DELIVERED,
    )


@pytest.mark.asyncio
async def test_photo_caption_safety_signal_is_still_paged_in_demo_mode() -> None:
    transport = _P0Transport()

    result = await run_rules_only(
        _request(
            resident_report="The kitchen fixture needs a repair.",
            photo_captions=("Smoke is coming from the breaker panel.",),
            category="electrical",
        ),
        p0_transport=transport,
        demo_mode=True,
    )

    assert result.priority is TicketPriority.P0
    assert transport.calls == []
    assert result.p0_delivery_statuses == (
        P0DeliveryStatus.SUPPRESSED_DEMO,
        P0DeliveryStatus.SUPPRESSED_DEMO,
        P0DeliveryStatus.SUPPRESSED_DEMO,
    )


def test_category_defaults_are_deterministic_and_unknown_categories_are_conservative() -> (
    None
):
    assert category_default_sla("HVAC") == (TicketPriority.P1, 24 * 60)
    assert category_default_sla("general maintenance") == (
        TicketPriority.P3,
        5 * 24 * 60,
    )
    assert category_default_sla("unclassified concern") == (TicketPriority.P2, 72 * 60)
