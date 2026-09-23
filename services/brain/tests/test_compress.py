"""Regression coverage for citation-preserving extractive compression."""

from __future__ import annotations

import pytest

from brain.context.compress import (
    ExtractiveSource,
    select_extractive_sentences,
)


def test_selection_returns_an_exact_query_relevant_source_substring_with_offsets() -> (
    None
):
    source_text = (
        "The owner pays for normal wear and tear. "
        "The qualified reviewer must verify the executed lease."
    )
    source = ExtractiveSource(
        source_id="LEASE-VA-2025",
        text=source_text,
        source_start=100,
    )

    selections = select_extractive_sentences(
        query="Who pays for normal wear?",
        sources=(source,),
    )

    assert len(selections) == 1
    selection = selections[0]
    assert selection.text == "The owner pays for normal wear and tear."
    assert selection.source_start == 100
    assert selection.source_end == 140
    assert (
        source_text[
            selection.source_start - source.source_start : selection.source_end
            - source.source_start
        ]
        == selection.text
    )


def test_selection_ranks_sentences_by_query_support_without_rewriting_them() -> None:
    source = ExtractiveSource(
        source_id="SOP-PLM-04",
        text=(
            "Record whether water is actively escaping. "
            "After two failed drain-clearing attempts, replace the P-trap assembly. "
            "Escalate incomplete evidence to the maintenance lead."
        ),
    )

    selections = select_extractive_sentences(
        query="When should a P-trap be replaced after failed drain clearing?",
        sources=(source,),
        max_sentences=2,
    )

    assert [selection.text for selection in selections] == [
        "After two failed drain-clearing attempts, replace the P-trap assembly."
    ]
    assert all(selection.text in source.text for selection in selections)


def test_markdown_list_item_is_preserved_as_one_exact_extractive_selection() -> None:
    source = ExtractiveSource(
        source_id="SOP-ELEC-01",
        text=(
            "- Do not ask a resident to reset a breaker or open a panel.\n"
            "- Route smoke or sparks to the emergency procedure."
        ),
    )

    selections = select_extractive_sentences(
        query="Can I reset the electrical breaker myself?",
        sources=(source,),
    )

    assert [selection.text for selection in selections] == [
        "- Do not ask a resident to reset a breaker or open a panel."
    ]


def test_zero_lexical_support_returns_no_policy_text() -> None:
    selections = select_extractive_sentences(
        query="Can I pay rent with cryptocurrency?",
        sources=(
            ExtractiveSource(
                source_id="SOP-HVAC-01",
                text="Collect ordinary heating and cooling maintenance facts.",
            ),
        ),
    )

    assert selections == ()


def test_selection_ties_use_source_order_then_source_position() -> None:
    first_source = ExtractiveSource(
        source_id="DOC-1",
        text="Water leak one. Water leak two.",
    )
    second_source = ExtractiveSource(
        source_id="DOC-2",
        text="Water leak three.",
    )

    selections = select_extractive_sentences(
        query="water leak",
        sources=(first_source, second_source),
        max_sentences=3,
    )

    assert [selection.text for selection in selections] == [
        "Water leak one.",
        "Water leak two.",
        "Water leak three.",
    ]


def test_invalid_input_fails_loudly() -> None:
    source = ExtractiveSource(source_id="DOC-1", text="A valid source sentence.")

    with pytest.raises(ValueError, match="query"):
        select_extractive_sentences(query=" ", sources=(source,))
    with pytest.raises(ValueError, match="max_sentences"):
        select_extractive_sentences(query="valid", sources=(source,), max_sentences=0)
    with pytest.raises(ValueError, match="source_start"):
        ExtractiveSource(source_id="DOC-2", text="Source", source_start=-1)
