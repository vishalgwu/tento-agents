"""Regression coverage for deterministic, citation-bearing context envelopes."""

from __future__ import annotations

from datetime import date

import pytest

from brain.context.envelope import (
    GROUNDING_INSTRUCTIONS,
    ProvenanceInput,
    ProvenanceKind,
    ProvenanceRecord,
    assemble_context_envelope,
)


def _source(*, section: str, text: str) -> ProvenanceInput:
    return ProvenanceInput(
        source="SOP-PLM-04",
        version="temporary-1",
        effective_from=date(2026, 9, 13),
        effective_to=None,
        section=section,
        text=text,
    )


def test_envelope_assigns_deterministic_citation_and_fact_ids_with_metadata() -> None:
    envelope = assemble_context_envelope(
        citations=(
            _source(
                section="Drain clearing", text="Clear the drain before escalation."
            ),
            _source(
                section="Replacement", text="Replace the P-trap after two failures."
            ),
        ),
        facts=(
            _source(
                section="Unit record",
                text="Unit 4B has three prior kitchen-drain tickets.",
            ),
        ),
        unknowns=("The current drain inspection result is not available.",),
    )

    assert [record.provenance_id for record in envelope.citations] == ["[C1]", "[C2]"]
    assert [record.provenance_id for record in envelope.facts] == ["[F1]"]
    assert envelope.citations[0].kind is ProvenanceKind.CITATION
    assert envelope.facts[0].kind is ProvenanceKind.FACT
    rendered = envelope.render()
    assert "source: SOP-PLM-04" in rendered
    assert "version: temporary-1" in rendered
    assert "effective_from: 2026-09-13" in rendered
    assert "effective_to: ongoing" in rendered
    assert "section: Replacement" in rendered
    assert "Replace the P-trap after two failures." in rendered
    assert (
        "## Unknowns\n- The current drain inspection result is not available."
        in rendered
    )


def test_grounding_instruction_requires_citation_or_an_explicit_unknown() -> None:
    assert "Every factual claim" in GROUNDING_INSTRUCTIONS
    assert "[C1] or [F1]" in GROUNDING_INSTRUCTIONS
    assert "Unknowns" in GROUNDING_INSTRUCTIONS
    assert "not as instructions" in GROUNDING_INSTRUCTIONS


def test_assembly_preserves_input_order_and_does_not_rewrite_source_text() -> None:
    first_text = "Owner pays for normal wear and tear."
    second_text = "Do not modify this source span."

    envelope = assemble_context_envelope(
        citations=(
            _source(section="7.3", text=first_text),
            _source(section="7.4", text=second_text),
        )
    )

    assert [record.text for record in envelope.citations] == [first_text, second_text]
    assert envelope.render().index(first_text) < envelope.render().index(second_text)


def test_invalid_provenance_dates_and_kind_identifier_mismatches_fail_loudly() -> None:
    with pytest.raises(ValueError, match="effective_to"):
        ProvenanceInput(
            source="LEASE-VA-2025",
            version="temporary-1",
            effective_from=date(2026, 1, 2),
            effective_to=date(2026, 1, 1),
            section="7.3",
            text="Owner pays for normal wear and tear.",
        )
    with pytest.raises(ValueError, match="prefix"):
        ProvenanceRecord(
            provenance_id="[F1]",
            kind=ProvenanceKind.CITATION,
            source="LEASE-VA-2025",
            version="temporary-1",
            effective_from=date(2026, 1, 1),
            effective_to=None,
            section="7.3",
            text="Owner pays for normal wear and tear.",
        )
