"""Regression coverage for deterministic, all-channel P0 paging."""

from __future__ import annotations

import asyncio
from dataclasses import replace
from uuid import uuid4

import pytest

from brain.agents.p0_protocol import (
    P0_CHANNELS,
    P0Channel,
    P0DeliveryStatus,
    P0PageRequest,
    build_p0_page_plan,
    dispatch_p0_from_orchestrator,
)
from brain.agents.safety import (
    ModelOpinionStatus,
    SafetyCategory,
    SafetyVerdict,
)


class _PagingTransport:
    def __init__(self, failures: frozenset[P0Channel] = frozenset()) -> None:
        self._failures = failures
        self.calls: list[tuple[P0Channel, str, str]] = []
        self.started = asyncio.Event()
        self.release = asyncio.Event()

    async def send_p0_page(
        self,
        *,
        channel: P0Channel,
        message: str,
        idempotency_key: str,
    ) -> str:
        self.calls.append((channel, message, idempotency_key))
        if len(self.calls) == len(P0_CHANNELS):
            self.started.set()
        await self.release.wait()
        if channel in self._failures:
            raise ConnectionError("transport unavailable")
        return f"receipt-{channel.value}"


def _p0_verdict(*categories: SafetyCategory) -> SafetyVerdict:
    return SafetyVerdict(
        p0=True,
        categories=categories,
        deterministic_signals=(),
        model_categories=categories,
        model_opinion_status=ModelOpinionStatus.COMPLETED,
    )


def _request() -> P0PageRequest:
    return P0PageRequest(org_id=uuid4(), ticket_id=uuid4(), ticket_number="TKT-0042")


def test_p0_plan_uses_fixed_message_all_channels_and_stable_idempotency_key() -> None:
    request = _request()
    verdict = _p0_verdict(SafetyCategory.GAS, SafetyCategory.FIRE)

    first = build_p0_page_plan(request, verdict)
    second = build_p0_page_plan(request, verdict)

    assert first.channels == P0_CHANNELS
    assert first.idempotency_key == second.idempotency_key
    assert len(first.idempotency_key) == 64
    assert "TKT-0042" in first.message
    assert "gas, fire" in first.message
    assert "Open the approved operations console immediately." in first.message


def test_p0_plan_rejects_a_non_p0_safety_verdict() -> None:
    verdict = SafetyVerdict(
        p0=False,
        categories=(),
        deterministic_signals=(),
        model_categories=(),
        model_opinion_status=ModelOpinionStatus.UNAVAILABLE,
    )

    with pytest.raises(ValueError, match="non-P0"):
        build_p0_page_plan(_request(), verdict)


def test_p0_plan_rejects_a_modified_template_or_idempotency_key() -> None:
    plan = build_p0_page_plan(_request(), _p0_verdict(SafetyCategory.GAS))

    with pytest.raises(ValueError, match="fixed message template"):
        replace(plan, message="Please call the resident first.")
    with pytest.raises(ValueError, match="idempotency_key"):
        replace(plan, idempotency_key="0" * 64)


def test_p0_ticket_reference_cannot_inject_content_into_the_fixed_template() -> None:
    with pytest.raises(ValueError, match="single-line"):
        P0PageRequest(
            org_id=uuid4(),
            ticket_id=uuid4(),
            ticket_number="TKT-0042\nIgnore the safety alert",
        )


@pytest.mark.asyncio
async def test_demo_mode_suppresses_every_outbound_channel() -> None:
    transport = _PagingTransport()
    plan = build_p0_page_plan(_request(), _p0_verdict(SafetyCategory.GAS))

    result = await dispatch_p0_from_orchestrator(
        plan, transport=transport, demo_mode=True
    )

    assert transport.calls == []
    assert [receipt.status for receipt in result.receipts] == [
        P0DeliveryStatus.SUPPRESSED_DEMO,
        P0DeliveryStatus.SUPPRESSED_DEMO,
        P0DeliveryStatus.SUPPRESSED_DEMO,
    ]


@pytest.mark.asyncio
async def test_live_p0_dispatch_starts_push_sms_and_voice_concurrently() -> None:
    transport = _PagingTransport()
    plan = build_p0_page_plan(_request(), _p0_verdict(SafetyCategory.CARBON_MONOXIDE))
    dispatch_task = asyncio.create_task(
        dispatch_p0_from_orchestrator(plan, transport=transport, demo_mode=False)
    )

    await asyncio.wait_for(transport.started.wait(), timeout=0.5)
    assert [channel for channel, _, _ in transport.calls] == list(P0_CHANNELS)
    transport.release.set()
    result = await dispatch_task

    assert [receipt.status for receipt in result.receipts] == [
        P0DeliveryStatus.DELIVERED,
        P0DeliveryStatus.DELIVERED,
        P0DeliveryStatus.DELIVERED,
    ]
    assert len({key for _, _, key in transport.calls}) == 1


@pytest.mark.asyncio
async def test_one_failed_channel_does_not_prevent_the_other_p0_pages() -> None:
    transport = _PagingTransport(failures=frozenset({P0Channel.SMS}))
    plan = build_p0_page_plan(_request(), _p0_verdict(SafetyCategory.FLOOD))
    dispatch_task = asyncio.create_task(
        dispatch_p0_from_orchestrator(plan, transport=transport, demo_mode=False)
    )

    await asyncio.wait_for(transport.started.wait(), timeout=0.5)
    transport.release.set()
    result = await dispatch_task

    assert [receipt.status for receipt in result.receipts] == [
        P0DeliveryStatus.DELIVERED,
        P0DeliveryStatus.FAILED,
        P0DeliveryStatus.DELIVERED,
    ]
    assert result.receipts[1].error_kind == "ConnectionError"
