"""Whole-block context budgeting with a real production tokenizer.

The budgeter keeps source-bearing blocks intact: a policy record is either
included verbatim or omitted. It never slices a text value to make it fit, and
it rejects an oversized current ticket rather than silently altering the record
that an agent is asked to reason about.
"""

from __future__ import annotations

import importlib
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from enum import Enum
from types import MappingProxyType
from typing import Final, Protocol


class ContextSlot(str, Enum):
    """The fixed allocation for one model context window."""

    SYSTEM_SCHEMA = "system_schema"
    POLICY = "policy"
    UNIT_ASSET_FACTS = "unit_asset_facts"
    SIMILAR_CASES = "similar_cases"
    CONVERSATION_SUMMARY = "conversation_summary"
    CURRENT_TICKET = "current_ticket"
    OUTPUT_RESERVE = "output_reserve"


SLOT_TOKEN_CAPS: Final[Mapping[ContextSlot, int]] = {
    ContextSlot.SYSTEM_SCHEMA: 1_000,
    ContextSlot.POLICY: 1_600,
    ContextSlot.UNIT_ASSET_FACTS: 700,
    ContextSlot.SIMILAR_CASES: 1_300,
    ContextSlot.CONVERSATION_SUMMARY: 500,
    ContextSlot.CURRENT_TICKET: 600,
    ContextSlot.OUTPUT_RESERVE: 2_300,
}
TOTAL_TOKEN_CAP: Final = 8_000
DEFAULT_TOKENIZER_ENCODING: Final = "o200k_base"
_SLOT_HEADINGS: Final[Mapping[ContextSlot, str]] = {
    ContextSlot.SYSTEM_SCHEMA: "## System and schema",
    ContextSlot.POLICY: "## Policy",
    ContextSlot.UNIT_ASSET_FACTS: "## Unit and asset facts",
    ContextSlot.SIMILAR_CASES: "## Similar cases",
    ContextSlot.CONVERSATION_SUMMARY: "## Conversation summary",
    ContextSlot.CURRENT_TICKET: "## Current ticket",
}
_INPUT_SLOTS: Final = (
    ContextSlot.SYSTEM_SCHEMA,
    ContextSlot.POLICY,
    ContextSlot.UNIT_ASSET_FACTS,
    ContextSlot.SIMILAR_CASES,
    ContextSlot.CONVERSATION_SUMMARY,
    ContextSlot.CURRENT_TICKET,
)


class ContextBudgetError(ValueError):
    """Raised when context cannot be represented within its explicit slot cap."""


class TokenizerUnavailableError(RuntimeError):
    """Raised when the required tokenizer installation is missing or invalid."""


class Tokenizer(Protocol):
    """The minimal real-token counting surface used by the budgeter."""

    def count(self, text: str) -> int:
        """Return the number of model tokens in ``text``."""


@dataclass(slots=True)
class TiktokenTokenizer:
    """Count tokens with the pinned ``tiktoken`` encoder used in production."""

    encoding_name: str = DEFAULT_TOKENIZER_ENCODING
    _encoding: object | None = field(default=None, init=False, repr=False)

    def __post_init__(self) -> None:
        _require_non_blank(self.encoding_name, "encoding_name")

    def count(self, text: str) -> int:
        """Return ``o200k_base`` tokens without permitting special-token syntax."""

        _require_text(text, "text")
        encoding = self._get_encoding()
        encode = getattr(encoding, "encode", None)
        if not callable(encode):
            raise TokenizerUnavailableError("tiktoken encoding does not expose encode")
        token_ids = encode(text, disallowed_special=())
        if not isinstance(token_ids, list) or not all(
            type(token_id) is int for token_id in token_ids
        ):
            raise TokenizerUnavailableError(
                "tiktoken encoding returned invalid token IDs"
            )
        return len(token_ids)

    def _get_encoding(self) -> object:
        if self._encoding is not None:
            return self._encoding
        try:
            package = importlib.import_module("tiktoken")
        except ImportError as error:
            raise TokenizerUnavailableError(
                "tiktoken is required for context budget enforcement"
            ) from error
        get_encoding = getattr(package, "get_encoding", None)
        if not callable(get_encoding):
            raise TokenizerUnavailableError("tiktoken.get_encoding is unavailable")
        try:
            self._encoding = get_encoding(self.encoding_name)
        except Exception as error:
            raise TokenizerUnavailableError(
                "tiktoken could not load "
                f"{self.encoding_name!r}; prewarm the encoding cache or configure egress"
            ) from error
        return self._encoding


@dataclass(frozen=True, slots=True)
class ContextFragment:
    """One indivisible, pre-ranked source-bearing context block."""

    text: str

    def __post_init__(self) -> None:
        _require_non_blank(self.text, "text")


@dataclass(frozen=True, slots=True)
class KeyValueFact:
    """A unit or asset fact rendered as a readable key-value line, never JSON."""

    key: str
    value: str
    provenance_id: str | None = None

    def __post_init__(self) -> None:
        _require_non_blank(self.key, "key")
        _require_non_blank(self.value, "value")
        if self.provenance_id is not None:
            _require_non_blank(self.provenance_id, "provenance_id")

    def render(self) -> str:
        """Render a single auditable key-value line."""

        prefix = f"{self.provenance_id} " if self.provenance_id is not None else ""
        return f"{prefix}{self.key}: {self.value}"


@dataclass(frozen=True, slots=True)
class ContextBudgetRequest:
    """Pre-ranked inputs for the fixed 8,000-token model context budget."""

    system_schema: str
    current_ticket: str
    policy: Sequence[ContextFragment] = ()
    unit_asset_facts: Sequence[KeyValueFact] = ()
    similar_cases: Sequence[ContextFragment] = ()
    conversation_summary: Sequence[ContextFragment] = ()

    def __post_init__(self) -> None:
        _require_non_blank(self.system_schema, "system_schema")
        _require_non_blank(self.current_ticket, "current_ticket")
        _validate_fragments(self.policy, "policy")
        _validate_facts(self.unit_asset_facts)
        _validate_fragments(self.similar_cases, "similar_cases")
        _validate_fragments(self.conversation_summary, "conversation_summary")
        object.__setattr__(self, "policy", tuple(self.policy))
        object.__setattr__(self, "unit_asset_facts", tuple(self.unit_asset_facts))
        object.__setattr__(self, "similar_cases", tuple(self.similar_cases))
        object.__setattr__(
            self, "conversation_summary", tuple(self.conversation_summary)
        )


@dataclass(frozen=True, slots=True)
class BudgetedSlot:
    """A rendered slot and its explicit selection trace."""

    slot: ContextSlot
    token_cap: int
    token_count: int
    text: str
    included_blocks: tuple[str, ...]
    omitted_blocks: tuple[str, ...]

    def __post_init__(self) -> None:
        if self.token_cap != SLOT_TOKEN_CAPS[self.slot]:
            raise ValueError("token_cap must match the fixed allocation for its slot")
        if type(self.token_count) is not int or self.token_count < 0:
            raise ValueError("token_count must be a non-negative integer")
        if self.token_count > self.token_cap:
            raise ValueError("token_count must not exceed token_cap")
        if self.slot is ContextSlot.OUTPUT_RESERVE and self.text:
            raise ValueError("output reserve does not contain input text")


@dataclass(frozen=True, slots=True)
class ContextBudget:
    """The complete, auditable allocation for an 8,000-token request window."""

    slots: Mapping[ContextSlot, BudgetedSlot]

    def __post_init__(self) -> None:
        slots = dict(self.slots)
        if set(slots) != set(ContextSlot):
            raise ValueError("context budget must include every fixed slot")
        if any(slot.slot is not slot_key for slot_key, slot in slots.items()):
            raise ValueError("budget slot keys must match their rendered slot")
        if sum(slot.token_cap for slot in slots.values()) != TOTAL_TOKEN_CAP:
            raise ValueError("context budget caps must total 8,000 tokens")
        object.__setattr__(self, "slots", MappingProxyType(slots))

    @property
    def input_token_count(self) -> int:
        """Return the actual input tokens selected for this request."""

        return sum(self.slots[slot].token_count for slot in _INPUT_SLOTS)

    @property
    def output_reserve(self) -> int:
        """Return the protected completion allowance."""

        return self.slots[ContextSlot.OUTPUT_RESERVE].token_cap

    def render(self) -> str:
        """Join only selected input slots in their fixed model-context order."""

        return "".join(
            self.slots[slot].text for slot in _INPUT_SLOTS if self.slots[slot].text
        )


@dataclass(slots=True)
class ContextBudgeter:
    """Select whole blocks under fixed caps using a real model tokenizer."""

    tokenizer: Tokenizer = field(default_factory=TiktokenTokenizer)
    _static_token_cache: dict[str, int] = field(default_factory=dict, init=False)

    def __post_init__(self) -> None:
        if not callable(getattr(self.tokenizer, "count", None)):
            raise ValueError("tokenizer must provide a count method")

    def build(self, request: ContextBudgetRequest) -> ContextBudget:
        """Build a bounded prompt context without truncating any source block."""

        system_text = _render_required_slot(
            ContextSlot.SYSTEM_SCHEMA, request.system_schema
        )
        system_count = self._count_static(system_text)
        _require_within_cap(ContextSlot.SYSTEM_SCHEMA, system_count)

        current_ticket_text = _render_required_slot(
            ContextSlot.CURRENT_TICKET, request.current_ticket
        )
        current_ticket_count = self._count(current_ticket_text)
        if current_ticket_count > SLOT_TOKEN_CAPS[ContextSlot.CURRENT_TICKET]:
            raise ContextBudgetError(
                "current_ticket exceeds its 600-token cap and must not be truncated"
            )

        slots: dict[ContextSlot, BudgetedSlot] = {
            ContextSlot.SYSTEM_SCHEMA: BudgetedSlot(
                slot=ContextSlot.SYSTEM_SCHEMA,
                token_cap=SLOT_TOKEN_CAPS[ContextSlot.SYSTEM_SCHEMA],
                token_count=system_count,
                text=system_text,
                included_blocks=(request.system_schema,),
                omitted_blocks=(),
            ),
            ContextSlot.POLICY: self._fit_fragments(
                ContextSlot.POLICY,
                tuple(fragment.text for fragment in request.policy),
            ),
            ContextSlot.UNIT_ASSET_FACTS: self._fit_fragments(
                ContextSlot.UNIT_ASSET_FACTS,
                tuple(fact.render() for fact in request.unit_asset_facts),
            ),
            ContextSlot.SIMILAR_CASES: self._fit_fragments(
                ContextSlot.SIMILAR_CASES,
                tuple(fragment.text for fragment in request.similar_cases),
            ),
            ContextSlot.CONVERSATION_SUMMARY: self._fit_fragments(
                ContextSlot.CONVERSATION_SUMMARY,
                tuple(fragment.text for fragment in request.conversation_summary),
            ),
            ContextSlot.CURRENT_TICKET: BudgetedSlot(
                slot=ContextSlot.CURRENT_TICKET,
                token_cap=SLOT_TOKEN_CAPS[ContextSlot.CURRENT_TICKET],
                token_count=current_ticket_count,
                text=current_ticket_text,
                included_blocks=(request.current_ticket,),
                omitted_blocks=(),
            ),
            ContextSlot.OUTPUT_RESERVE: BudgetedSlot(
                slot=ContextSlot.OUTPUT_RESERVE,
                token_cap=SLOT_TOKEN_CAPS[ContextSlot.OUTPUT_RESERVE],
                token_count=0,
                text="",
                included_blocks=(),
                omitted_blocks=(),
            ),
        }
        return ContextBudget(slots=slots)

    def _count_static(self, text: str) -> int:
        """Count static system/schema text once per distinct rendered value."""

        if text not in self._static_token_cache:
            self._static_token_cache[text] = self._count(text)
        return self._static_token_cache[text]

    def _count(self, text: str) -> int:
        token_count = self.tokenizer.count(text)
        if type(token_count) is not int or token_count < 0:
            raise ContextBudgetError("tokenizer must return a non-negative integer")
        return token_count

    def _fit_fragments(
        self, slot: ContextSlot, fragments: Sequence[str]
    ) -> BudgetedSlot:
        """Greedily keep pre-ranked whole blocks only when the full slot still fits."""

        if not fragments:
            return BudgetedSlot(
                slot=slot,
                token_cap=SLOT_TOKEN_CAPS[slot],
                token_count=0,
                text="",
                included_blocks=(),
                omitted_blocks=(),
            )
        included: list[str] = []
        omitted: list[str] = []
        for fragment in fragments:
            candidate = _render_optional_slot(slot, (*included, fragment))
            if self._count(candidate) <= SLOT_TOKEN_CAPS[slot]:
                included.append(fragment)
            else:
                omitted.append(fragment)
        text = _render_optional_slot(slot, included)
        return BudgetedSlot(
            slot=slot,
            token_cap=SLOT_TOKEN_CAPS[slot],
            token_count=self._count(text) if text else 0,
            text=text,
            included_blocks=tuple(included),
            omitted_blocks=tuple(omitted),
        )


def _render_required_slot(slot: ContextSlot, text: str) -> str:
    return f"{_slot_prefix(slot)}{_SLOT_HEADINGS[slot]}\n\n{text}"


def _render_optional_slot(slot: ContextSlot, fragments: Sequence[str]) -> str:
    if not fragments:
        return ""
    return f"{_slot_prefix(slot)}{_SLOT_HEADINGS[slot]}\n\n" + "\n\n".join(fragments)


def _slot_prefix(slot: ContextSlot) -> str:
    """Render each non-first slot with its own counted context separator."""

    return "" if slot is ContextSlot.SYSTEM_SCHEMA else "\n\n"


def _require_within_cap(slot: ContextSlot, token_count: int) -> None:
    if token_count > SLOT_TOKEN_CAPS[slot]:
        raise ContextBudgetError(
            f"{slot.value} exceeds its {SLOT_TOKEN_CAPS[slot]}-token cap"
        )


def _validate_fragments(values: Sequence[ContextFragment], field_name: str) -> None:
    if isinstance(values, (str, bytes)):
        raise ValueError(f"{field_name} must be a sequence of ContextFragment")
    if any(not isinstance(value, ContextFragment) for value in values):
        raise ValueError(f"{field_name} must contain only ContextFragment values")


def _validate_facts(values: Sequence[KeyValueFact]) -> None:
    if isinstance(values, (str, bytes)):
        raise ValueError("unit_asset_facts must be a sequence of KeyValueFact")
    if any(not isinstance(value, KeyValueFact) for value in values):
        raise ValueError("unit_asset_facts must contain only KeyValueFact values")


def _require_text(value: str, field_name: str) -> None:
    if not isinstance(value, str):
        raise ValueError(f"{field_name} must be a string")


def _require_non_blank(value: str, field_name: str) -> None:
    _require_text(value, field_name)
    if not value.strip():
        raise ValueError(f"{field_name} must be a non-blank string")
