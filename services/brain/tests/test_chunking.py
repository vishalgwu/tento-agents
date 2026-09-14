"""Regression coverage for the deterministic corpus-aware chunking contract."""

from __future__ import annotations

import pytest

from brain.retrieval.chunking import (
    SOP_MAX_TOKENS,
    SOP_MIN_TOKENS,
    CorpusKind,
    chunk_markdown,
    chunk_work_order_history,
    count_lexical_tokens,
)


def test_lease_chunking_keeps_each_clause_and_section_path() -> None:
    markdown = """---
id: LEASE-TEST
---
# Sample lease

## §7.1 Repairs
The owner will review a reported repair request under the executed agreement.

## §7.3 Wear and tear
owner pays for normal wear and tear
"""

    chunks = chunk_markdown(
        markdown=markdown,
        corpus=CorpusKind.LEASE,
        document_title="Fallback lease title",
    )

    assert [chunk.heading_path for chunk in chunks] == [
        "Sample lease > §7.1 Repairs",
        "Sample lease > §7.3 Wear and tear",
    ]
    assert "§7.1 Repairs" in chunks[0].content
    assert "owner pays for normal wear and tear" in chunks[1].content
    _assert_source_spans(markdown, chunks)


def test_sop_chunking_stays_inside_a_heading_and_uses_bounded_overlap() -> None:
    first_section = " ".join(f"first{index}" for index in range(1_200))
    second_section = " ".join(f"second{index}" for index in range(350))
    markdown = f"""# Plumbing protocol

## Drain clearance
{first_section}

## Follow-up
{second_section}
"""

    chunks = chunk_markdown(
        markdown=markdown,
        corpus=CorpusKind.SOP,
        document_title="Plumbing fallback",
    )

    drain_chunks = [
        chunk
        for chunk in chunks
        if chunk.heading_path == "Plumbing protocol > Drain clearance"
    ]
    follow_up_chunks = [
        chunk
        for chunk in chunks
        if chunk.heading_path == "Plumbing protocol > Follow-up"
    ]
    assert len(drain_chunks) == 3
    assert len(follow_up_chunks) == 1
    assert all(
        SOP_MIN_TOKENS <= chunk.token_count <= SOP_MAX_TOKENS for chunk in chunks
    )
    assert all("second" not in chunk.content for chunk in drain_chunks)
    assert "first" not in follow_up_chunks[0].content

    for earlier, later in zip(drain_chunks, drain_chunks[1:]):
        overlap = count_lexical_tokens(
            markdown[later.source_start : earlier.source_end]
        )
        assert overlap / earlier.token_count == pytest.approx(0.15, abs=0.01)
    _assert_source_spans(markdown, chunks)


def test_community_rules_keep_each_top_level_rule_separate() -> None:
    markdown = """# Community rules

## Shared spaces
- Keep common walkways clear.
- Report a damaged fixture through the approved channel.
  - Do not include private access details in the report.

## Pets
Pets must follow the verified property policy.
"""

    chunks = chunk_markdown(
        markdown=markdown,
        corpus=CorpusKind.COMMUNITY_RULES,
        document_title="Community fallback",
    )

    assert [chunk.heading_path for chunk in chunks] == [
        "Community rules > Shared spaces",
        "Community rules > Shared spaces",
        "Community rules > Pets",
    ]
    assert "Keep common walkways clear" in chunks[0].content
    assert "Report a damaged fixture" in chunks[1].content
    assert "Do not include private access details" in chunks[1].content
    assert "Pets must follow" in chunks[2].content
    assert "Report a damaged fixture" not in chunks[0].content
    _assert_source_spans(markdown, chunks)


def test_work_order_history_uses_one_symptom_and_resolution_payload() -> None:
    chunks = chunk_work_order_history(
        ticket_id="ticket-123",
        symptom="Kitchen drain backs up after normal use.",
        resolution="Qualified technician replaced the failed trap assembly.",
    )

    assert len(chunks) == 1
    chunk = chunks[0]
    assert chunk.index == 0
    assert chunk.heading_path == "ticket:ticket-123"
    assert chunk.content == (
        "Symptom: Kitchen drain backs up after normal use.\n"
        "Resolution: Qualified technician replaced the failed trap assembly."
    )
    assert chunk.source_start == 0
    assert chunk.source_end == len(chunk.content)
    assert chunk.token_count == count_lexical_tokens(chunk.content)


@pytest.mark.parametrize("field_name", ["ticket_id", "symptom", "resolution"])
def test_work_order_history_rejects_missing_evidence_fields(field_name: str) -> None:
    values = {
        "ticket_id": "ticket-123",
        "symptom": "Kitchen drain backs up.",
        "resolution": "Trap assembly replaced.",
    }
    values[field_name] = " "

    with pytest.raises(ValueError, match=field_name):
        chunk_work_order_history(**values)


def _assert_source_spans(markdown: str, chunks: tuple[object, ...]) -> None:
    for chunk in chunks:
        source_start = getattr(chunk, "source_start")
        source_end = getattr(chunk, "source_end")
        content = getattr(chunk, "content")
        assert markdown[source_start:source_end] == content
