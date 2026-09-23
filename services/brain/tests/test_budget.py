"""Regression coverage for fixed, tokenizer-enforced context allocations."""

from __future__ import annotations

import re

import pytest

from brain.context.budget import (
    SLOT_TOKEN_CAPS,
    TOTAL_TOKEN_CAP,
    ContextBudgetError,
    ContextBudgetRequest,
    ContextBudgeter,
    ContextFragment,
    ContextSlot,
    KeyValueFact,
    TiktokenTokenizer,
)


class CountingTokenizer:
    """Deterministic test tokenizer that records full-text counting calls."""

    def __init__(self) -> None:
        self.calls_by_text: dict[str, int] = {}

    def count(self, text: str) -> int:
        self.calls_by_text[text] = self.calls_by_text.get(text, 0) + 1
        return len(re.findall(r"\S+", text))


def _request(**overrides: object) -> ContextBudgetRequest:
    values: dict[str, object] = {
        "system_schema": "Follow grounded maintenance rules.",
        "current_ticket": "Kitchen sink backs up after dishwashing.",
        "policy": (
            ContextFragment(
                "[C1] Clear the drain before escalating a routine blockage."
            ),
        ),
        "unit_asset_facts": (
            KeyValueFact("unit", "4B", provenance_id="[F1]"),
            KeyValueFact("asset", "kitchen sink"),
        ),
        "similar_cases": (
            ContextFragment("[C2] Prior case: a blocked P-trap was replaced."),
        ),
        "conversation_summary": (
            ContextFragment("Resident reports the issue began this morning."),
        ),
    }
    values.update(overrides)
    return ContextBudgetRequest(**values)  # type: ignore[arg-type]


def test_budget_has_the_required_fixed_8000_token_allocation() -> None:
    budget = ContextBudgeter(tokenizer=CountingTokenizer()).build(_request())

    assert sum(SLOT_TOKEN_CAPS.values()) == TOTAL_TOKEN_CAP == 8_000
    assert set(budget.slots) == set(ContextSlot)
    assert budget.output_reserve == 2_300
    assert budget.input_token_count + budget.output_reserve <= TOTAL_TOKEN_CAP
    assert all(slot.token_count <= slot.token_cap for slot in budget.slots.values())


def test_static_system_schema_token_count_is_cached_between_requests() -> None:
    tokenizer = CountingTokenizer()
    budgeter = ContextBudgeter(tokenizer=tokenizer)
    request = _request()

    budgeter.build(request)
    budgeter.build(request)

    static_text = "## System and schema\n\nFollow grounded maintenance rules."
    assert tokenizer.calls_by_text[static_text] == 1


def test_slot_counts_include_every_separator_in_the_final_rendered_context() -> None:
    tokenizer = CountingTokenizer()
    budget = ContextBudgeter(tokenizer=tokenizer).build(_request())

    assert budget.input_token_count == tokenizer.count(budget.render())


def test_unit_and_asset_facts_are_rendered_as_key_value_lines_not_json() -> None:
    budget = ContextBudgeter(tokenizer=CountingTokenizer()).build(_request())
    facts = budget.slots[ContextSlot.UNIT_ASSET_FACTS].text

    assert "[F1] unit: 4B" in facts
    assert "asset: kitchen sink" in facts
    assert '"unit"' not in facts
    assert "{" not in facts


def test_policy_blocks_are_omitted_whole_when_the_slot_cap_is_exceeded() -> None:
    too_large_policy = ContextFragment("policy " * 1_700)
    retained_policy = ContextFragment("[C2] A later concise policy block.")
    budget = ContextBudgeter(tokenizer=CountingTokenizer()).build(
        _request(policy=(too_large_policy, retained_policy))
    )
    policy_slot = budget.slots[ContextSlot.POLICY]

    assert policy_slot.included_blocks == (retained_policy.text,)
    assert policy_slot.omitted_blocks == (too_large_policy.text,)
    assert too_large_policy.text not in policy_slot.text
    assert policy_slot.token_count <= 1_600


def test_oversized_static_or_current_ticket_text_fails_instead_of_truncating() -> None:
    budgeter = ContextBudgeter(tokenizer=CountingTokenizer())

    with pytest.raises(ContextBudgetError, match="system_schema"):
        budgeter.build(_request(system_schema="system " * 1_100))
    with pytest.raises(ContextBudgetError, match="must not be truncated"):
        budgeter.build(_request(current_ticket="ticket " * 700))


def test_production_tokenizer_counts_tokens_with_pinned_tiktoken_encoder() -> None:
    tokenizer = TiktokenTokenizer()

    assert tokenizer.count("Owner pays for normal wear and tear.") > 0
