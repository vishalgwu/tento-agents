"""Regression coverage for hybrid retrieval's ranking and safety boundaries."""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, cast

import pytest

from brain.retrieval.embed import EMBEDDING_DIMENSIONS, EMBEDDING_MODEL, Embedding
from brain.retrieval.hybrid import (
    LEXICAL_CANDIDATE_LIMIT,
    RRF_K,
    VECTOR_CANDIDATE_LIMIT,
    AsyncpgHybridSearchRepository,
    HybridRetrievalRequest,
    HybridRetriever,
    KnowledgeDocumentStatus,
    RetrievedKnowledgeChunk,
    RetrievalMetadataFilters,
    reciprocal_rank_fusion,
)
from brain.retrieval.ingest import Authority


def _embedding(*, model: str = EMBEDDING_MODEL) -> Embedding:
    return Embedding(
        cache_key=f"sha256:test:model:{model}",
        model=model,
        values=(0.0,) * EMBEDDING_DIMENSIONS,
    )


def _chunk(
    chunk_id: uuid.UUID,
    *,
    status: KnowledgeDocumentStatus = KnowledgeDocumentStatus.ACTIVE,
    jurisdiction_code: str = "US-VA",
    effective_from: datetime = datetime(2026, 9, 13, tzinfo=UTC),
    effective_to: datetime | None = None,
    embedding_model: str | None = EMBEDDING_MODEL,
) -> RetrievedKnowledgeChunk:
    content = "Synthetic retrieval fixture."
    return RetrievedKnowledgeChunk(
        chunk_id=chunk_id,
        document_id=uuid.UUID(int=chunk_id.int + 1_000),
        document_key=f"DOC-{chunk_id.int:03d}",
        document_version="test-1",
        title="Synthetic retrieval fixture",
        authority=Authority.INTERNAL_SOP,
        jurisdiction_code=jurisdiction_code,
        status=status,
        effective_from=effective_from,
        effective_to=effective_to,
        heading_path="Fixture > Section",
        source_start=0,
        source_end=len(content),
        content=content,
        embedding_model=embedding_model,
    )


@dataclass
class FakeHybridRepository:
    lexical_ids: tuple[uuid.UUID, ...]
    vector_ids: tuple[uuid.UUID, ...]
    chunks: dict[uuid.UUID, RetrievedKnowledgeChunk]
    lexical_calls: list[tuple[uuid.UUID, str, int]] = field(default_factory=list)
    vector_calls: list[tuple[uuid.UUID, Embedding, int]] = field(default_factory=list)
    fetch_calls: list[tuple[uuid.UUID, tuple[uuid.UUID, ...]]] = field(
        default_factory=list
    )

    async def lexical_candidate_ids(
        self, *, org_id: uuid.UUID, query: str, limit: int
    ) -> Sequence[uuid.UUID]:
        self.lexical_calls.append((org_id, query, limit))
        return self.lexical_ids

    async def vector_candidate_ids(
        self, *, org_id: uuid.UUID, embedding: Embedding, limit: int
    ) -> Sequence[uuid.UUID]:
        self.vector_calls.append((org_id, embedding, limit))
        return self.vector_ids

    async def fetch_chunks(
        self, *, org_id: uuid.UUID, chunk_ids: Sequence[uuid.UUID]
    ) -> Sequence[RetrievedKnowledgeChunk]:
        requested_ids = tuple(chunk_ids)
        self.fetch_calls.append((org_id, requested_ids))
        return tuple(self.chunks[chunk_id] for chunk_id in requested_ids)


def test_reciprocal_rank_fusion_preserves_each_channel_rank_and_rrf_formula() -> None:
    first = uuid.UUID(int=1)
    second = uuid.UUID(int=2)
    third = uuid.UUID(int=3)

    candidates = reciprocal_rank_fusion(
        lexical_ids=(first, second),
        vector_ids=(second, third),
    )

    assert [candidate.chunk_id for candidate in candidates] == [second, first, third]
    assert candidates[0].bm25_rank == 2
    assert candidates[0].vector_rank == 1
    assert candidates[0].rrf_score == pytest.approx(1 / (RRF_K + 2) + 1 / (RRF_K + 1))
    assert candidates[1].bm25_rank == 1
    assert candidates[1].vector_rank is None
    assert candidates[2].bm25_rank is None
    assert candidates[2].vector_rank == 2


@pytest.mark.asyncio
async def test_retriever_uses_top_thirty_then_filters_metadata_after_fusion() -> None:
    org_id = uuid.UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
    candidate_ids = tuple(uuid.UUID(int=number) for number in range(1, 31))
    ticket_timestamp = datetime(2026, 9, 15, tzinfo=UTC)
    chunks: dict[uuid.UUID, RetrievedKnowledgeChunk] = {}
    for number, chunk_id in enumerate(candidate_ids, start=1):
        chunks[chunk_id] = _chunk(
            chunk_id,
            status=(
                KnowledgeDocumentStatus.DRAFT
                if number == 3
                else KnowledgeDocumentStatus.ACTIVE
            ),
            jurisdiction_code="US-MD" if number == 2 else "US-VA",
            effective_from=(
                datetime(2026, 9, 16, tzinfo=UTC)
                if number == 4
                else datetime(2026, 9, 13, tzinfo=UTC)
            ),
            effective_to=(datetime(2026, 9, 14, tzinfo=UTC) if number == 5 else None),
            embedding_model="other-model" if number == 6 else EMBEDDING_MODEL,
        )
    repository = FakeHybridRepository(
        lexical_ids=candidate_ids,
        vector_ids=candidate_ids,
        chunks=chunks,
    )

    hits = await HybridRetriever(repository=repository).retrieve(
        HybridRetrievalRequest(
            org_id=org_id,
            query="water leaking through a ceiling",
            query_embedding=_embedding(),
            ticket_timestamp=ticket_timestamp,
            filters=RetrievalMetadataFilters(jurisdiction_code="US-VA"),
        )
    )

    assert repository.lexical_calls == [
        (org_id, "water leaking through a ceiling", LEXICAL_CANDIDATE_LIMIT)
    ]
    assert repository.vector_calls[0][0] == org_id
    assert repository.vector_calls[0][2] == VECTOR_CANDIDATE_LIMIT
    assert repository.fetch_calls == [(org_id, candidate_ids)]
    assert [hit.chunk.chunk_id for hit in hits] == [
        candidate_ids[0],
        *candidate_ids[6:],
    ]
    assert [hit.final_rank for hit in hits] == list(range(1, len(hits) + 1))
    assert all(hit.chunk.status is KnowledgeDocumentStatus.ACTIVE for hit in hits)
    assert all(hit.chunk.jurisdiction_code == "US-VA" for hit in hits)
    assert all(hit.chunk.embedding_model == EMBEDDING_MODEL for hit in hits)


@pytest.mark.asyncio
async def test_retriever_uses_ticket_timestamp_not_the_current_time() -> None:
    org_id = uuid.UUID("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb")
    chunk_id = uuid.UUID(int=1)
    repository = FakeHybridRepository(
        lexical_ids=(chunk_id,),
        vector_ids=(chunk_id,),
        chunks={
            chunk_id: _chunk(
                chunk_id,
                effective_from=datetime(2026, 9, 13, tzinfo=UTC),
            )
        },
    )
    retriever = HybridRetriever(repository=repository)

    hits = await retriever.retrieve(
        HybridRetrievalRequest(
            org_id=org_id,
            query="historical plumbing question",
            query_embedding=_embedding(),
            ticket_timestamp=datetime(2026, 9, 12, tzinfo=UTC),
        )
    )

    assert hits == ()


@pytest.mark.asyncio
async def test_retriever_rejects_a_naive_ticket_timestamp_before_querying() -> None:
    org_id = uuid.UUID("cccccccc-cccc-cccc-cccc-cccccccccccc")
    repository = FakeHybridRepository(lexical_ids=(), vector_ids=(), chunks={})

    with pytest.raises(ValueError, match="timezone-aware"):
        await HybridRetriever(repository=repository).retrieve(
            HybridRetrievalRequest(
                org_id=org_id,
                query="a retrieval query",
                query_embedding=_embedding(),
                ticket_timestamp=datetime(2026, 9, 13),
            )
        )

    assert repository.lexical_calls == []
    assert repository.vector_calls == []


@dataclass
class RecordingConnection:
    calls: list[tuple[str, tuple[object, ...]]] = field(default_factory=list)

    async def fetch(self, query: str, *arguments: object) -> tuple[object, ...]:
        self.calls.append((query, arguments))
        return ()


@pytest.mark.asyncio
async def test_asyncpg_candidate_queries_keep_metadata_outside_the_hnsw_and_gin_reads() -> (
    None
):
    org_id = uuid.UUID("dddddddd-dddd-dddd-dddd-dddddddddddd")
    connection = RecordingConnection()
    repository = AsyncpgHybridSearchRepository(connection=cast(Any, connection))

    await repository.lexical_candidate_ids(
        org_id=org_id,
        query="sink leak",
        limit=LEXICAL_CANDIDATE_LIMIT,
    )
    await repository.vector_candidate_ids(
        org_id=org_id,
        embedding=_embedding(),
        limit=VECTOR_CANDIDATE_LIMIT,
    )

    lexical_query, lexical_arguments = connection.calls[0]
    vector_query, vector_arguments = connection.calls[1]
    assert "websearch_to_tsquery" in lexical_query
    assert "content_tsv @@ query_terms.value" in lexical_query
    assert "kb_documents" not in lexical_query
    assert "effective_from" not in lexical_query
    assert "status" not in lexical_query
    assert lexical_arguments == (org_id, "sink leak", LEXICAL_CANDIDATE_LIMIT)
    assert "<=> $2::text::halfvec" in vector_query
    assert "kb_documents" not in vector_query
    assert "effective_from" not in vector_query
    assert "status" not in vector_query
    assert vector_arguments[0] == org_id
    assert vector_arguments[2] == VECTOR_CANDIDATE_LIMIT
