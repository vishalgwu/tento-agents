"""Regression coverage for citation-preserving parent-section expansion."""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, cast

import pytest

from brain.retrieval.hybrid import KnowledgeDocumentStatus, RetrievedKnowledgeChunk
from brain.retrieval.ingest import Authority
from brain.retrieval.parent import (
    AsyncpgParentSectionRepository,
    ParentExpansionError,
    ParentSectionChunk,
    ParentSectionExpander,
    ParentSectionKey,
)


_DOCUMENT_ID = uuid.UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
_ORG_ID = uuid.UUID("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb")
_HEADING_PATH = "Resident handbook > Repairs"


def _chunk(
    *, chunk_id: int, source_start: int, content: str
) -> RetrievedKnowledgeChunk:
    return RetrievedKnowledgeChunk(
        chunk_id=uuid.UUID(int=chunk_id),
        document_id=_DOCUMENT_ID,
        document_key="HANDBOOK-001",
        document_version="1.0",
        title="Resident handbook",
        authority=Authority.INTERNAL_SOP,
        jurisdiction_code="US-VA",
        status=KnowledgeDocumentStatus.ACTIVE,
        effective_from=datetime(2026, 9, 13, tzinfo=UTC),
        effective_to=None,
        heading_path=_HEADING_PATH,
        source_start=source_start,
        source_end=source_start + len(content),
        content=content,
        embedding_model="text-embedding-3-small",
    )


def _section_chunk(
    *, chunk_id: int, source_start: int, content: str, heading_path: str = _HEADING_PATH
) -> ParentSectionChunk:
    return ParentSectionChunk(
        chunk_id=uuid.UUID(int=chunk_id),
        document_id=_DOCUMENT_ID,
        heading_path=heading_path,
        source_start=source_start,
        source_end=source_start + len(content),
        content=content,
    )


@dataclass
class FakeParentRepository:
    chunks: tuple[ParentSectionChunk, ...]
    calls: list[tuple[uuid.UUID, tuple[ParentSectionKey, ...]]] = field(
        default_factory=list
    )

    async def fetch_section_chunks(
        self,
        *,
        org_id: uuid.UUID,
        section_keys: Sequence[ParentSectionKey],
    ) -> tuple[ParentSectionChunk, ...]:
        self.calls.append((org_id, tuple(section_keys)))
        return self.chunks


@pytest.mark.asyncio
async def test_parent_expansion_reconstructs_the_complete_heading_scope() -> None:
    section = (
        "## Repairs\n"
        "Only report issues that affect habitability.\n\n"
        "Do not authorize repairs until written approval is recorded.\n"
    )
    source_start = 120
    first_end = section.index("\n\n")
    second_start = section.index("report issues")
    anchor = _chunk(
        chunk_id=1,
        source_start=source_start,
        content=section[:first_end],
    )
    later = _chunk(
        chunk_id=2,
        source_start=source_start + second_start,
        content=section[second_start:],
    )
    repository = FakeParentRepository(
        chunks=(
            _section_chunk(
                chunk_id=2,
                source_start=later.source_start,
                content=later.content,
            ),
            _section_chunk(
                chunk_id=1,
                source_start=anchor.source_start,
                content=anchor.content,
            ),
        )
    )

    expanded = await ParentSectionExpander(repository=repository).expand(
        org_id=_ORG_ID,
        chunks=(anchor, later),
    )

    assert repository.calls == [
        (_ORG_ID, (ParentSectionKey(_DOCUMENT_ID, _HEADING_PATH),))
    ]
    assert [item.anchor.chunk_id for item in expanded] == [
        anchor.chunk_id,
        later.chunk_id,
    ]
    assert all(item.source_start == source_start for item in expanded)
    assert all(item.source_end == source_start + len(section) for item in expanded)
    assert all(item.content == section for item in expanded)
    assert expanded[0].source_chunk_ids == (anchor.chunk_id, later.chunk_id)


@pytest.mark.asyncio
async def test_parent_expansion_preserves_absolute_positions_through_whitespace_gaps() -> (
    None
):
    first = _chunk(chunk_id=1, source_start=10, content="Clause A.")
    second = _chunk(chunk_id=2, source_start=22, content="Clause B.")
    repository = FakeParentRepository(
        chunks=(
            _section_chunk(chunk_id=1, source_start=10, content="Clause A."),
            _section_chunk(chunk_id=2, source_start=22, content="Clause B."),
        )
    )

    expanded = (
        await ParentSectionExpander(repository=repository).expand(
            org_id=_ORG_ID,
            chunks=(first,),
        )
    )[0]

    assert expanded.source_start == 10
    assert expanded.content == "Clause A.   Clause B."
    assert (
        expanded.content[second.source_start - expanded.source_start :]
        == second.content
    )


@pytest.mark.asyncio
async def test_parent_expansion_rejects_missing_or_changed_anchor() -> None:
    anchor = _chunk(chunk_id=1, source_start=10, content="Required condition.")
    repository = FakeParentRepository(
        chunks=(
            _section_chunk(chunk_id=2, source_start=10, content="Different condition."),
        )
    )

    with pytest.raises(ParentExpansionError, match="retrieved anchor"):
        await ParentSectionExpander(repository=repository).expand(
            org_id=_ORG_ID,
            chunks=(anchor,),
        )


@pytest.mark.asyncio
async def test_parent_expansion_rejects_cross_scope_or_conflicting_content() -> None:
    anchor = _chunk(chunk_id=1, source_start=10, content="Required condition.")
    wrong_scope_repository = FakeParentRepository(
        chunks=(
            _section_chunk(
                chunk_id=1,
                source_start=10,
                content="Required condition.",
                heading_path="Resident handbook > Payments",
            ),
        )
    )
    with pytest.raises(ParentExpansionError, match="unrequested"):
        await ParentSectionExpander(repository=wrong_scope_repository).expand(
            org_id=_ORG_ID,
            chunks=(anchor,),
        )

    conflicting_repository = FakeParentRepository(
        chunks=(
            _section_chunk(chunk_id=1, source_start=10, content="Required condition."),
            _section_chunk(chunk_id=2, source_start=10, content="Different condition."),
        )
    )
    with pytest.raises(ParentExpansionError, match="disagree"):
        await ParentSectionExpander(repository=conflicting_repository).expand(
            org_id=_ORG_ID,
            chunks=(anchor,),
        )


@dataclass
class RecordingConnection:
    rows: tuple[dict[str, object], ...] = ()
    calls: list[tuple[str, tuple[object, ...]]] = field(default_factory=list)

    async def fetch(
        self, query: str, *arguments: object
    ) -> tuple[dict[str, object], ...]:
        self.calls.append((query, arguments))
        return self.rows


@pytest.mark.asyncio
async def test_asyncpg_parent_repository_scopes_queries_to_tenant_and_requested_sections() -> (
    None
):
    connection = RecordingConnection()
    repository = AsyncpgParentSectionRepository(connection=cast(Any, connection))
    key = ParentSectionKey(_DOCUMENT_ID, _HEADING_PATH)

    result = await repository.fetch_section_chunks(org_id=_ORG_ID, section_keys=(key,))

    assert result == ()
    query, arguments = connection.calls[0]
    assert "WHERE chunk.org_id = $1" in query
    assert "unnest($2::uuid[], $3::text[])" in query
    assert "requested.heading_path = chunk.heading_path" in query
    assert "ORDER BY" in query
    assert arguments == (_ORG_ID, [_DOCUMENT_ID], [_HEADING_PATH])
