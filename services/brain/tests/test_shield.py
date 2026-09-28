"""Regression coverage for the local-first, bounded content-safety shield."""

from __future__ import annotations

import asyncio
from time import monotonic
from typing import cast

import pytest

from brain.guardrails.shield import (
    DEFAULT_FAIL_CLOSED_DEGRADATION_STAGES,
    DEFAULT_MANAGED_PROVIDER_TIMEOUT_SECONDS,
    DEGRADATION_INTERLOCK_NAME,
    Shield,
    ShieldDegradationKind,
    ShieldDegradation,
    ShieldFinding,
    ShieldOutcome,
    ShieldProvider,
    ShieldRequest,
    ShieldStage,
)


class _Provider:
    def __init__(
        self, name: str, result: ShieldFinding | Exception, *, delay: float = 0.0
    ) -> None:
        self.name = name
        self._result = result
        self._delay = delay
        self.calls = 0

    async def inspect(self, request: ShieldRequest) -> ShieldFinding:
        del request
        self.calls += 1
        if self._delay:
            await asyncio.sleep(self._delay)
        if isinstance(self._result, Exception):
            raise self._result
        return self._result


def _request(content: str = "The kitchen sink is leaking.") -> ShieldRequest:
    return ShieldRequest(content=content, stage=ShieldStage.PRE_MODEL)


def _allow(provider: str) -> ShieldFinding:
    return ShieldFinding(provider=provider, outcome=ShieldOutcome.ALLOW)


def _block(provider: str, reason: str = "managed_policy_block") -> ShieldFinding:
    return ShieldFinding(
        provider=provider,
        outcome=ShieldOutcome.BLOCK,
        reason_codes=(reason,),
    )


@pytest.mark.asyncio
async def test_local_shield_always_runs_and_blocks_before_managed_disclosure() -> None:
    managed = _Provider("managed", _allow("managed"))

    assessment = await Shield((managed,)).inspect(
        _request("I am going to bring a gun to the leasing office.")
    )

    assert assessment.outcome is ShieldOutcome.BLOCK
    assert assessment.findings[0].provider == "local"
    assert assessment.findings[0].reason_codes == ("imminent_weapon_threat",)
    assert managed.calls == 0


@pytest.mark.asyncio
async def test_any_managed_block_wins_over_local_and_peer_allows() -> None:
    allow = _Provider("first", _allow("first"))
    block = _Provider("second", _block("second"))

    assessment = await Shield((allow, block)).inspect(_request())

    assert assessment.outcome is ShieldOutcome.BLOCK
    assert [finding.provider for finding in assessment.findings] == [
        "local",
        "first",
        "second",
    ]
    assert assessment.findings[-1].reason_codes == ("managed_policy_block",)


@pytest.mark.asyncio
async def test_timeout_is_logged_as_degradation_without_failing_the_request(
    caplog: pytest.LogCaptureFixture,
) -> None:
    slow = _Provider("slow", _allow("slow"), delay=1.0)
    started = monotonic()

    assessment = await Shield((slow,)).inspect(_request())

    assert monotonic() - started < 0.75
    assert DEFAULT_MANAGED_PROVIDER_TIMEOUT_SECONDS == 0.25
    assert assessment.outcome is ShieldOutcome.ALLOW
    assert assessment.degradations[0].provider == "slow"
    assert assessment.degradations[0].kind is ShieldDegradationKind.TIMEOUT
    assert (
        "shield_provider_degraded provider=slow kind=timeout stage=pre_model"
        in caplog.text
    )
    assert "The kitchen sink is leaking" not in caplog.text


@pytest.mark.asyncio
async def test_degraded_pre_send_fails_closed_without_failing_the_request() -> None:
    slow = _Provider("slow", _allow("slow"), delay=1.0)

    assessment = await Shield((slow,)).inspect(
        ShieldRequest(content="Safe resident-facing copy.", stage=ShieldStage.PRE_SEND)
    )

    assert ShieldStage.PRE_SEND in DEFAULT_FAIL_CLOSED_DEGRADATION_STAGES
    assert assessment.outcome is ShieldOutcome.BLOCK
    assert assessment.degradations[0].kind is ShieldDegradationKind.TIMEOUT
    assert assessment.findings[-1] == ShieldFinding(
        provider=DEGRADATION_INTERLOCK_NAME,
        outcome=ShieldOutcome.BLOCK,
        reason_codes=("managed_provider_degraded",),
    )


@pytest.mark.asyncio
async def test_degradation_policy_can_be_explicitly_configured_per_stage() -> None:
    slow = _Provider("slow", _allow("slow"), delay=1.0)

    assessment = await Shield(
        (slow,), fail_closed_on_degradation_stages=frozenset()
    ).inspect(
        ShieldRequest(content="Safe resident-facing copy.", stage=ShieldStage.PRE_SEND)
    )

    assert assessment.outcome is ShieldOutcome.ALLOW
    assert assessment.degradations[0].kind is ShieldDegradationKind.TIMEOUT


@pytest.mark.asyncio
async def test_provider_failure_degrades_without_exposing_content(
    caplog: pytest.LogCaptureFixture,
) -> None:
    failed = _Provider("managed", ConnectionError("provider unavailable"))

    assessment = await Shield((failed,)).inspect(_request("private resident text"))

    assert assessment.outcome is ShieldOutcome.ALLOW
    assert assessment.degradations == (
        ShieldDegradation(
            provider="managed", kind=ShieldDegradationKind.PROVIDER_FAILURE
        ),
    )
    assert "private resident text" not in caplog.text


@pytest.mark.asyncio
async def test_managed_providers_run_concurrently_under_one_timeout_window() -> None:
    first = _Provider("first", _allow("first"), delay=1.0)
    second = _Provider("second", _allow("second"), delay=1.0)
    started = monotonic()

    assessment = await Shield((first, second)).inspect(_request())

    assert monotonic() - started < 0.45
    assert assessment.outcome is ShieldOutcome.ALLOW
    assert [degradation.provider for degradation in assessment.degradations] == [
        "first",
        "second",
    ]


def test_invalid_managed_configuration_and_response_are_safe() -> None:
    with pytest.raises(ValueError, match="cannot replace the local shield"):
        Shield((_Provider("local", _allow("local")),))
    with pytest.raises(ValueError, match="must be unique"):
        Shield(
            (
                _Provider("managed", _allow("managed")),
                _Provider("managed", _allow("managed")),
            )
        )


@pytest.mark.asyncio
async def test_invalid_managed_response_becomes_a_logged_degradation() -> None:
    class _MalformedProvider:
        name = "malformed"

        async def inspect(self, request: ShieldRequest) -> object:
            del request
            return object()

    assessment = await Shield((cast(ShieldProvider, _MalformedProvider()),)).inspect(
        _request()
    )

    assert assessment.outcome is ShieldOutcome.ALLOW
    assert assessment.degradations[0].kind is ShieldDegradationKind.INVALID_RESPONSE


@pytest.mark.asyncio
async def test_cancellation_propagates_instead_of_becoming_a_degradation() -> None:
    started = asyncio.Event()
    release = asyncio.Event()

    class _BlockingProvider:
        name = "blocking"

        async def inspect(self, request: ShieldRequest) -> ShieldFinding:
            del request
            started.set()
            await release.wait()
            return _allow(self.name)

    task = asyncio.create_task(Shield((_BlockingProvider(),)).inspect(_request()))
    await asyncio.wait_for(started.wait(), timeout=0.1)
    task.cancel()

    with pytest.raises(asyncio.CancelledError):
        await task


def test_request_and_finding_do_not_accept_unsafe_or_inconsistent_shapes() -> None:
    with pytest.raises(ValueError, match="non-blank"):
        _request("   ")
    with pytest.raises(ValueError, match="block finding"):
        ShieldFinding(provider="local", outcome=ShieldOutcome.BLOCK)
    with pytest.raises(ValueError, match="allow finding"):
        ShieldFinding(
            provider="local",
            outcome=ShieldOutcome.ALLOW,
            reason_codes=("unexpected",),
        )
