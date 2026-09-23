"""Deterministic, fail-safe P0 screening before any ordinary agent work.

The deterministic screen runs first and a qualifying signal returns immediately.
The optional small-model second opinion can only add an escalation when the
deterministic screen is clear; it can never suppress a deterministic P0 verdict.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Sequence
from enum import Enum
from typing import Protocol

from pydantic import BaseModel, ConfigDict, Field, model_validator

from brain.gateway.client import (
    RenderedPrompt,
    TaskClass,
    load_builtin_prompt,
)


class SafetyCategory(str, Enum):
    """Life-safety categories that require the deterministic P0 path."""

    GAS = "gas"
    FIRE = "fire"
    FLOOD = "flood"
    ELECTRICAL = "electrical"
    CARBON_MONOXIDE = "carbon_monoxide"
    NO_HEAT = "no_heat"
    SEWAGE = "sewage"


class SignalSource(str, Enum):
    """The untrusted input source in which a deterministic signal appeared."""

    RESIDENT_REPORT = "resident_report"
    PHOTO_CAPTION = "photo_caption"


class ModelOpinionStatus(str, Enum):
    """Whether a small-model second opinion was consulted for this ticket."""

    SKIPPED_DETERMINISTIC_P0 = "skipped_deterministic_p0"
    COMPLETED = "completed"
    UNAVAILABLE = "unavailable"


class SafetySignal(BaseModel):
    """A non-sensitive deterministic match; it retains no resident text."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    category: SafetyCategory
    source: SignalSource
    source_index: int = Field(ge=0)
    pattern_id: str = Field(min_length=1, max_length=80)


class SafetySecondOpinion(BaseModel):
    """The constrained small-model response used only to add a P0 escalation."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    p0: bool
    categories: tuple[SafetyCategory, ...]

    @model_validator(mode="after")
    def _require_categories_to_match_p0(self) -> SafetySecondOpinion:
        if self.p0 != bool(self.categories):
            raise ValueError("p0 must be true exactly when categories are present")
        if len(self.categories) != len(set(self.categories)):
            raise ValueError("categories must not contain duplicates")
        return self


class SafetyVerdict(BaseModel):
    """Structured handoff from safety screening to the P0 or standard workflow."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    p0: bool
    categories: tuple[SafetyCategory, ...]
    deterministic_signals: tuple[SafetySignal, ...]
    model_categories: tuple[SafetyCategory, ...]
    model_opinion_status: ModelOpinionStatus

    @model_validator(mode="after")
    def _validate_combined_or_logic(self) -> SafetyVerdict:
        deterministic_categories = {
            signal.category for signal in self.deterministic_signals
        }
        expected_categories = deterministic_categories | set(self.model_categories)
        if self.p0 != bool(expected_categories):
            raise ValueError("p0 must be the OR of deterministic and model signals")
        if set(self.categories) != expected_categories:
            raise ValueError(
                "categories must contain every deterministic or model category"
            )
        if len(self.categories) != len(set(self.categories)):
            raise ValueError("categories must not contain duplicates")
        if len(self.model_categories) != len(set(self.model_categories)):
            raise ValueError("model_categories must not contain duplicates")
        if deterministic_categories and (
            self.model_opinion_status is not ModelOpinionStatus.SKIPPED_DETERMINISTIC_P0
        ):
            raise ValueError("deterministic P0 must skip the model second opinion")
        return self


class SafetySecondOpinionGateway(Protocol):
    """The narrow gateway capability needed by the safety sentinel."""

    async def complete(
        self,
        task: TaskClass,
        prompt: RenderedPrompt,
        schema: type[SafetySecondOpinion],
    ) -> SafetySecondOpinion:
        """Return a schema-validated safety opinion through the central gateway."""


class _CompiledSafetyPattern:
    def __init__(
        self, category: SafetyCategory, pattern_id: str, expression: str
    ) -> None:
        self.category = category
        self.pattern_id = pattern_id
        self.expression = re.compile(expression, re.IGNORECASE | re.VERBOSE)


_SAFETY_PATTERNS: tuple[_CompiledSafetyPattern, ...] = (
    _CompiledSafetyPattern(
        SafetyCategory.GAS,
        "gas_odor_or_leak",
        r"""
        \b(?:
            (?:smell(?:s|ed|ing)?|odor|odour|fumes?)\s+(?:of\s+|like\s+)?
                (?:(?:natural\s+|propane\s+)?gas)|
            (?:natural\s+|propane\s+)?gas\s+(?:leak|leaking|odor|odour|smell|fumes?)|
            rotten[-\s]?eggs?(?:\s+(?:smell|odor|odour|scent))?|
            sulfur(?:ous)?\s+(?:smell|odor|odour)|
            hissing\s+(?:near|from|by|at|around)\s+(?:the\s+)?
                (?:gas\s+(?:line|pipe|meter|stove|oven)|stove|oven|furnace|boiler|gas\s+appliance)|
            (?:gas\s+(?:line|pipe|meter|valve)|(?:gas|propane)\s+tank)\s+
                (?:is\s+)?(?:leaking|hissing|damaged|broken)
        )\b
        """,
    ),
    _CompiledSafetyPattern(
        SafetyCategory.FIRE,
        "fire_or_smoke",
        r"""
        \b(?:
            fire|flames?|
            smoke\s+(?:(?:is\s+)?(?:coming|filling|inside|in|from|through)|
                (?:alarm|detector)\s+(?:is\s+)?(?:going\s+off|alarming|beeping))|
            (?:smoke\s+)?(?:alarm|detector)\s+(?:is\s+)?(?:going\s+off|alarming)|
            (?:smell(?:s|ed|ing)?|odor|odour)\s+(?:of\s+|like\s+)?
                (?:something\s+)?(?:burning|smoke)|
            burning\s+(?:smell|odor|odour|wires?|plastic|outlet|appliance|wall|ceiling)|
            (?:stove|oven|appliance)\s+(?:is\s+)?smoking
        )\b
        """,
    ),
    _CompiledSafetyPattern(
        SafetyCategory.FLOOD,
        "flood_or_major_water_release",
        r"""
        \b(?:
            flood(?:ing|ed)?|
            (?:water|pipe)\s+(?:is\s+)?(?:pouring|gushing|spraying|rushing|running\s+everywhere)|
            (?:burst|burst(?:ed)?|broke(?:n)?)\s+(?:water\s+)?pipe|
            (?:water\s+)?pipe\s+(?:burst|broke|is\s+broken)|
            (?:ceiling|wall)\s+(?:(?:is\s+)?(?:collapsing|pouring|leaking|dripping)|
                has\s+water\s+(?:pouring|leaking))|
            water\s+(?:is\s+)?(?:leaking|coming|pouring|dripping)\s+
                (?:through|from)\s+(?:the\s+)?(?:ceiling|wall|light|fixture)|
            (?:apartment|unit|bathroom|kitchen|basement)\s+(?:is\s+)?(?:flooding|flooded)|
            (?:major|huge|uncontrolled|serious)\s+(?:water\s+)?leak|
            (?:water\s+)?leak\s+(?:won'?t\s+stop|is\s+out\s+of\s+control)
        )\b
        """,
    ),
    _CompiledSafetyPattern(
        SafetyCategory.ELECTRICAL,
        "electrical_shock_or_arc",
        r"""
        \b(?:
            sparks?|sparking|arcing|electrical\s+(?:arc|fire|shock)|
            (?:outlet|socket|plug|breaker|panel|fuse\s+box|wires?|cord|switch|light\s+fixture)\s+
                (?:is\s+)?(?:smoking|burning|sparking|arcing|hot|melting|buzzing)|
            (?:outlet|socket|plug|switch|light\s+fixture)\s+
                (?:gave|gives)\s+(?:me\s+)?(?:an?\s+)?(?:electric(?:al)?\s+)?shock|
            (?:outlet|socket|plug|switch|light\s+fixture)\s+(?:shocked|zapped)\s+me|
            (?:got|received|felt)\s+(?:an?\s+)?electric(?:al)?\s+shock|
            (?:exposed|bare|frayed)\s+(?:electrical\s+)?(?:wire|wires|cord)|
            (?:wire|wires|cord)\s+(?:is\s+)?(?:exposed|bare|frayed)|
            (?:downed|fallen)\s+(?:live\s+)?power\s+line|
            power\s+line\s+(?:is\s+)?(?:down|fallen|sparking)
        )\b
        """,
    ),
    _CompiledSafetyPattern(
        SafetyCategory.CARBON_MONOXIDE,
        "carbon_monoxide_alarm",
        r"""
        \b(?:
            carbon[-\s]?monoxide(?:\s+(?:alarm|detector|monitor))?|
            c\.?\s*o\.?\s+(?:alarm|detector|monitor)(?:\s+(?:is\s+)?
                (?:beeping|chirping|going\s+off|alarming|sounding))?
        )\b
        """,
    ),
    _CompiledSafetyPattern(
        SafetyCategory.NO_HEAT,
        "loss_of_heat",
        r"""
        \b(?:
            no\s+(?:heat|heating|central\s+heat)|
            (?:heat|heating|heater|furnace|boiler|radiator|radiators|hvac)\s+(?:is\s+)?
                (?:not\s+working|broken|out|off|gone|stopped(?:\s+working)?|failed|dead|cold)|
            (?:heat|heating)\s+(?:went|has\s+gone)\s+out|
            (?:heat|heating|heater|furnace|boiler)\s+(?:won'?t|doesn'?t|didn'?t)\s+
                (?:turn\s+on|work)|
            (?:no\s+)?(?:hot\s+air|warm\s+air)\s+(?:is\s+)?(?:coming|blowing)|
            (?:apartment|unit|home)\s+(?:is\s+)?(?:freezing|frigid|ice\s+cold)
        )\b
        """,
    ),
    _CompiledSafetyPattern(
        SafetyCategory.SEWAGE,
        "sewage_backup_or_overflow",
        r"""
        \b(?:
            (?:raw\s+)?sewage(?:\s+(?:backup|backing\s+up|overflow(?:ing|ed)?|coming\s+up))?|
            sewer(?:\s+(?:line|water))?\s+(?:backup|backing\s+up|overflow(?:ing|ed)?|coming\s+up)|
            toilet\s+(?:is\s+)?(?:overflow(?:ing|ed)?|backing\s+up|bubbling|gurgling)|
            (?:waste\s*water|black\s+water|fecal\s+water)\s+(?:is\s+)?
                (?:backing\s+up|overflow(?:ing|ed)?|coming\s+up)|
            (?:multiple|all)(?:\s+the)?\s+(?:drains?|toilets?)\s+(?:are\s+)?
                (?:backing\s+up|overflow(?:ing|ed)?|bubbling)|
            water\s+(?:is\s+)?(?:coming\s+)?(?:up|out)\s+(?:from|through)\s+
                (?:the\s+)?(?:toilet|drain|shower|tub)
        )\b
        """,
    ),
)
_CATEGORY_ORDER = {category: index for index, category in enumerate(SafetyCategory)}


def screen_deterministic_safety(
    resident_report: str, *, photo_captions: Sequence[str] = ()
) -> tuple[SafetySignal, ...]:
    """Return every P0 regex signal from report text and optional photo captions.

    This pure function does not call a model or retain the original input text.
    A single signal is sufficient for the caller to enter the P0 path.
    """

    _require_text(resident_report, "resident_report")
    captions = _validated_captions(photo_captions)
    inputs = ((SignalSource.RESIDENT_REPORT, 0, resident_report),) + tuple(
        (SignalSource.PHOTO_CAPTION, index, caption)
        for index, caption in enumerate(captions, start=1)
    )
    signals: list[SafetySignal] = []
    for source, source_index, value in inputs:
        for pattern in _SAFETY_PATTERNS:
            if pattern.expression.search(value) is not None:
                signals.append(
                    SafetySignal(
                        category=pattern.category,
                        source=source,
                        source_index=source_index,
                        pattern_id=pattern.pattern_id,
                    )
                )
    return tuple(signals)


async def assess_safety(
    resident_report: str,
    *,
    photo_captions: Sequence[str] = (),
    second_opinion_gateway: SafetySecondOpinionGateway | None = None,
) -> SafetyVerdict:
    """Combine deterministic and optional model signals using fail-safe OR logic.

    If the deterministic screen finds a P0 signal this returns before model work,
    leaving the orchestrator free to page the approved human path immediately.
    Gateway failures leave a rules-only verdict; they can never erase a matching
    deterministic signal.
    """

    signals = screen_deterministic_safety(
        resident_report, photo_captions=photo_captions
    )
    deterministic_categories = _ordered_categories(
        signal.category for signal in signals
    )
    if deterministic_categories:
        return SafetyVerdict(
            p0=True,
            categories=deterministic_categories,
            deterministic_signals=signals,
            model_categories=(),
            model_opinion_status=ModelOpinionStatus.SKIPPED_DETERMINISTIC_P0,
        )
    if second_opinion_gateway is None:
        return _rules_only_verdict(signals)

    prompt = load_builtin_prompt("safety-second-opinion").render(
        {
            "resident_report": resident_report,
            "photo_captions": tuple(photo_captions),
        },
        schema=SafetySecondOpinion,
    )
    try:
        opinion = await second_opinion_gateway.complete(
            TaskClass.SAFETY_SECOND_OPINION,
            prompt,
            SafetySecondOpinion,
        )
    except Exception:
        return _rules_only_verdict(signals)

    model_categories = _ordered_categories(opinion.categories)
    return SafetyVerdict(
        p0=bool(model_categories),
        categories=model_categories,
        deterministic_signals=signals,
        model_categories=model_categories,
        model_opinion_status=ModelOpinionStatus.COMPLETED,
    )


def _rules_only_verdict(signals: tuple[SafetySignal, ...]) -> SafetyVerdict:
    return SafetyVerdict(
        p0=False,
        categories=(),
        deterministic_signals=signals,
        model_categories=(),
        model_opinion_status=ModelOpinionStatus.UNAVAILABLE,
    )


def _ordered_categories(
    categories: Iterable[SafetyCategory],
) -> tuple[SafetyCategory, ...]:
    return tuple(sorted(set(categories), key=_CATEGORY_ORDER.__getitem__))


def _validated_captions(photo_captions: Sequence[str]) -> tuple[str, ...]:
    if isinstance(photo_captions, (str, bytes)):
        raise ValueError("photo_captions must be a sequence of strings")
    captions = tuple(photo_captions)
    for index, caption in enumerate(captions, start=1):
        _require_text(caption, f"photo_captions[{index}]")
    return captions


def _require_text(value: str, field_name: str) -> None:
    if not isinstance(value, str):
        raise ValueError(f"{field_name} must be a string")
