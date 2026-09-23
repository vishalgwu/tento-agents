"""Regression coverage for deterministic P0 screening and safe model escalation."""

from __future__ import annotations

import pytest

from brain.agents.safety import (
    ModelOpinionStatus,
    SafetyCategory,
    SafetySecondOpinion,
    assess_safety,
    screen_deterministic_safety,
)
from brain.gateway.client import GatewayError, RenderedPrompt, TaskClass


class _SecondOpinionGateway:
    def __init__(self, result: SafetySecondOpinion | Exception) -> None:
        self._result = result
        self.calls: list[
            tuple[TaskClass, RenderedPrompt, type[SafetySecondOpinion]]
        ] = []

    async def complete(
        self,
        task: TaskClass,
        prompt: RenderedPrompt,
        schema: type[SafetySecondOpinion],
    ) -> SafetySecondOpinion:
        self.calls.append((task, prompt, schema))
        if isinstance(self._result, Exception):
            raise self._result
        return self._result


@pytest.mark.parametrize(
    ("report", "category"),
    [
        ("There is a strong gas smell by the stove.", SafetyCategory.GAS),
        ("Flames are coming from the breaker panel.", SafetyCategory.FIRE),
        ("A burst pipe is gushing water through the ceiling.", SafetyCategory.FLOOD),
        (
            "The outlet is sparking and I felt an electric shock.",
            SafetyCategory.ELECTRICAL,
        ),
        ("The carbon monoxide alarm is going off.", SafetyCategory.CARBON_MONOXIDE),
        ("We have no heat and the furnace is not working.", SafetyCategory.NO_HEAT),
        ("Raw sewage is backing up into the bathtub.", SafetyCategory.SEWAGE),
    ],
)
def test_deterministic_screen_has_a_recall_oriented_signal_for_each_p0_category(
    report: str, category: SafetyCategory
) -> None:
    signals = screen_deterministic_safety(report)

    assert any(signal.category is category for signal in signals)
    assert all(signal.source_index == 0 for signal in signals)


@pytest.mark.parametrize(
    ("report", "category"),
    [
        ("I smell gas in the kitchen.", SafetyCategory.GAS),
        ("The gas line is leaking.", SafetyCategory.GAS),
        ("There is a rotten egg odor near the boiler.", SafetyCategory.GAS),
        ("Smoke is coming through the ceiling.", SafetyCategory.FIRE),
        ("There is a burning smell from the outlet.", SafetyCategory.FIRE),
        ("The oven is smoking.", SafetyCategory.FIRE),
        ("Water is running everywhere from a pipe.", SafetyCategory.FLOOD),
        ("Water is leaking through the ceiling light.", SafetyCategory.FLOOD),
        ("The bathroom is flooding.", SafetyCategory.FLOOD),
        ("The breaker panel is buzzing and hot.", SafetyCategory.ELECTRICAL),
        ("I got an electrical shock from the outlet.", SafetyCategory.ELECTRICAL),
        ("There are exposed wires in the wall.", SafetyCategory.ELECTRICAL),
        ("The CO monitor is chirping.", SafetyCategory.CARBON_MONOXIDE),
        ("The C.O. detector is sounding.", SafetyCategory.CARBON_MONOXIDE),
        ("The heat went out overnight.", SafetyCategory.NO_HEAT),
        ("No warm air is coming from the vents.", SafetyCategory.NO_HEAT),
        ("The apartment is freezing.", SafetyCategory.NO_HEAT),
        ("The toilet overflowed into the bathroom.", SafetyCategory.SEWAGE),
        ("All the drains are backing up.", SafetyCategory.SEWAGE),
        ("Water is coming up from the shower drain.", SafetyCategory.SEWAGE),
    ],
)
def test_deterministic_screen_captures_high_recall_resident_wording(
    report: str, category: SafetyCategory
) -> None:
    signals = screen_deterministic_safety(report)

    assert any(signal.category is category for signal in signals)


def test_deterministic_screen_inspects_photo_captions_without_retaining_caption_text() -> (
    None
):
    signals = screen_deterministic_safety(
        "The kitchen sink is leaking.",
        photo_captions=("Visible sparks beside the outlet.",),
    )

    assert [(signal.category, signal.source_index) for signal in signals] == [
        (SafetyCategory.ELECTRICAL, 1)
    ]
    assert "Visible sparks" not in repr(signals)


@pytest.mark.asyncio
async def test_deterministic_p0_skips_the_model_and_cannot_be_suppressed() -> None:
    gateway = _SecondOpinionGateway(SafetySecondOpinion(p0=False, categories=()))

    verdict = await assess_safety(
        "The gas leak is hissing near the furnace.", second_opinion_gateway=gateway
    )

    assert verdict.p0 is True
    assert verdict.categories == (SafetyCategory.GAS,)
    assert verdict.model_opinion_status is ModelOpinionStatus.SKIPPED_DETERMINISTIC_P0
    assert gateway.calls == []


@pytest.mark.asyncio
async def test_small_model_second_opinion_can_escalate_a_clear_deterministic_screen() -> (
    None
):
    gateway = _SecondOpinionGateway(
        SafetySecondOpinion(p0=True, categories=(SafetyCategory.CARBON_MONOXIDE,))
    )

    verdict = await assess_safety(
        "My detector keeps chirping and I am not sure why.",
        photo_captions=("A round alarm is mounted on the hallway ceiling.",),
        second_opinion_gateway=gateway,
    )

    assert verdict.p0 is True
    assert verdict.categories == (SafetyCategory.CARBON_MONOXIDE,)
    assert verdict.model_categories == (SafetyCategory.CARBON_MONOXIDE,)
    assert verdict.model_opinion_status is ModelOpinionStatus.COMPLETED
    assert gateway.calls[0][0] is TaskClass.SAFETY_SECOND_OPINION
    assert gateway.calls[0][2] is SafetySecondOpinion
    assert "round alarm" in gateway.calls[0][1].dynamic_suffix


@pytest.mark.asyncio
async def test_model_failure_keeps_the_deterministic_rules_only_result() -> None:
    gateway = _SecondOpinionGateway(GatewayError("provider unavailable"))

    verdict = await assess_safety(
        "There is a small drip under the kitchen sink.", second_opinion_gateway=gateway
    )

    assert verdict.p0 is False
    assert verdict.categories == ()
    assert verdict.model_opinion_status is ModelOpinionStatus.UNAVAILABLE


@pytest.mark.asyncio
async def test_unexpected_second_opinion_failure_keeps_the_rules_only_result() -> None:
    gateway = _SecondOpinionGateway(RuntimeError("unexpected transport failure"))

    verdict = await assess_safety(
        "There is a small drip under the kitchen sink.", second_opinion_gateway=gateway
    )

    assert verdict.p0 is False
    assert verdict.categories == ()
    assert verdict.model_opinion_status is ModelOpinionStatus.UNAVAILABLE


@pytest.mark.parametrize(
    "near_miss",
    [
        "It smells like garbage near the dumpster.",
        "The stove smells when I cook dinner.",
        "There is a small drip under the sink.",
    ],
)
def test_known_near_misses_do_not_trigger_the_deterministic_p0_screen(
    near_miss: str,
) -> None:
    assert screen_deterministic_safety(near_miss) == ()


def test_invalid_model_opinion_cannot_claim_p0_without_a_category() -> None:
    with pytest.raises(ValueError, match="exactly when categories"):
        SafetySecondOpinion(p0=True, categories=())


def test_model_schema_accepts_gateway_json_output() -> None:
    opinion = SafetySecondOpinion.model_validate_json(
        '{"p0":true,"categories":["gas"]}'
    )

    assert opinion == SafetySecondOpinion(p0=True, categories=(SafetyCategory.GAS,))


def test_photo_captions_must_be_a_sequence_of_strings() -> None:
    with pytest.raises(ValueError, match="sequence"):
        screen_deterministic_safety("A routine request.", photo_captions="caption")


def test_pattern_list_covers_exactly_the_defined_p0_categories() -> None:
    categories = {signal.category for signal in screen_deterministic_safety("no heat")}
    assert categories == {SafetyCategory.NO_HEAT}
