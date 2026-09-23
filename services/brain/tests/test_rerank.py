"""Regression coverage for bounded, persisted cross-encoder reranking."""

from __future__ import annotations

import threading
import uuid
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, cast

import pytest

import brain.retrieval.rerank as rerank_module
from brain.retrieval.hybrid import (
    HybridRetrievalHit,
    KnowledgeDocumentStatus,
    RetrievedKnowledgeChunk,
)
from brain.retrieval.ingest import Authority
from brain.retrieval.rerank import (
    RERANK_CANDIDATE_LIMIT,
    RERANK_RESULT_LIMIT,
    AsyncpgRerankScoreRepository,
    CrossEncoderReranker,
    RerankPersistenceError,
    RerankRequest,
    RerankScore,
    get_process_reranker_model,
)


def _hybrid_hit(number: int, final_rank: int) -> HybridRetrievalHit:
    chunk_id = uuid.UUID(int=number)
    content = f"Retrieval fixture {number}."
    chunk = RetrievedKnowledgeChunk(
        chunk_id=chunk_id,
        document_id=uuid.UUID(int=number + 1_000),
        document_key=f"DOC-{number:03d}",
        document_version="test-1",
        title="Retrieval fixture",
        authority=Authority.INTERNAL_SOP,
        jurisdiction_code="US-VA",
        status=KnowledgeDocumentStatus.ACTIVE,
        effective_from=datetime(2026, 9, 13, tzinfo=UTC),
        effective_to=None,
        heading_path="Fixture > Section",
        source_start=0,
        source_end=len(content),
        content=content,
        embedding_model="text-embedding-3-small",
    )
    return HybridRetrievalHit(
        chunk=chunk,
        bm25_rank=final_rank,
        vector_rank=final_rank,
        rrf_score=1 / (60 + final_rank),
        final_rank=final_rank,
    )


@dataclass
class FakeCrossEncoder:
    scores: tuple[float, ...]
    calls: list[tuple[tuple[tuple[str, str], ...], int, bool]] = field(
        default_factory=list
    )
    thread_ids: list[int] = field(default_factory=list)

    def predict(
        self,
        sentences: Sequence[tuple[str, str]],
        *,
        batch_size: int,
        show_progress_bar: bool,
    ) -> tuple[float, ...]:
        self.calls.append((tuple(sentences), batch_size, show_progress_bar))
        self.thread_ids.append(threading.get_ident())
        return self.scores


@dataclass
class FakeScoreRepository:
    calls: list[tuple[uuid.UUID, uuid.UUID, tuple[RerankScore, ...]]] = field(
        default_factory=list
    )

    async def persist_rerank_scores(
        self,
        *,
        org_id: uuid.UUID,
        retrieval_id: uuid.UUID,
        scores: Sequence[RerankScore],
    ) -> None:
        self.calls.append((org_id, retrieval_id, tuple(scores)))


@pytest.mark.asyncio
async def test_reranker_scores_all_candidates_persists_them_and_returns_best_six() -> (
    None
):
    org_id = uuid.UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
    retrieval_id = uuid.UUID("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb")
    candidates = tuple(_hybrid_hit(number, number) for number in reversed(range(1, 9)))
    model = FakeCrossEncoder((0.2, 0.95, 0.3, 0.8, 0.7, 0.6, 0.5, 0.4))
    repository = FakeScoreRepository()
    main_thread_id = threading.get_ident()

    hits = await CrossEncoderReranker(
        score_repository=repository,
        model=model,
        inference_batch_size=4,
    ).rerank(
        RerankRequest(
            org_id=org_id,
            retrieval_id=retrieval_id,
            query="water leaking through the ceiling",
            candidates=candidates,
        )
    )

    assert [hit.hybrid_hit.chunk.chunk_id.int for hit in hits] == [2, 4, 5, 6, 7, 8]
    assert [hit.rerank_rank for hit in hits] == list(range(1, RERANK_RESULT_LIMIT + 1))
    assert model.calls[0][0] == tuple(
        ("water leaking through the ceiling", f"Retrieval fixture {number}.")
        for number in range(1, 9)
    )
    assert model.calls[0][1:] == (4, False)
    assert model.thread_ids[0] != main_thread_id
    assert repository.calls == [
        (
            org_id,
            retrieval_id,
            tuple(
                RerankScore(chunk_id=uuid.UUID(int=number), score=score)
                for number, score in enumerate(model.scores, start=1)
            ),
        )
    ]


@pytest.mark.asyncio
async def test_reranker_caps_scoring_at_thirty_candidates() -> None:
    candidates = tuple(_hybrid_hit(number, number) for number in range(1, 32))
    model = FakeCrossEncoder(tuple(float(number) for number in range(30)))
    repository = FakeScoreRepository()

    hits = await CrossEncoderReranker(
        score_repository=repository,
        model=model,
    ).rerank(
        RerankRequest(
            org_id=uuid.UUID("cccccccc-cccc-cccc-cccc-cccccccccccc"),
            retrieval_id=uuid.UUID("dddddddd-dddd-dddd-dddd-dddddddddddd"),
            query="maintenance policy",
            candidates=candidates,
        )
    )

    assert len(model.calls[0][0]) == RERANK_CANDIDATE_LIMIT
    assert len(repository.calls[0][2]) == RERANK_CANDIDATE_LIMIT
    assert len(hits) == RERANK_RESULT_LIMIT
    assert hits[0].hybrid_hit.chunk.chunk_id.int == RERANK_CANDIDATE_LIMIT
    assert all(
        hit.hybrid_hit.chunk.chunk_id.int <= RERANK_CANDIDATE_LIMIT for hit in hits
    )


def test_default_model_loader_returns_one_process_wide_instance(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    model = FakeCrossEncoder(())
    load_calls: list[None] = []

    def load_model() -> FakeCrossEncoder:
        load_calls.append(None)
        return model

    monkeypatch.setattr(rerank_module, "_process_reranker_model", None)
    monkeypatch.setattr(rerank_module, "_load_cross_encoder_model", load_model)

    assert get_process_reranker_model() is model
    assert get_process_reranker_model() is model
    assert load_calls == [None]


@dataclass
class RecordingConnection:
    returned_ids: tuple[uuid.UUID, ...]
    calls: list[tuple[str, tuple[object, ...]]] = field(default_factory=list)

    async def fetch(
        self, query: str, *arguments: object
    ) -> tuple[dict[str, uuid.UUID], ...]:
        self.calls.append((query, arguments))
        return tuple({"kb_chunk_id": chunk_id} for chunk_id in self.returned_ids)


@pytest.mark.asyncio
async def test_asyncpg_repository_updates_all_scores_with_tenant_and_retrieval_scope() -> (
    None
):
    org_id = uuid.UUID("eeeeeeee-eeee-eeee-eeee-eeeeeeeeeeee")
    retrieval_id = uuid.UUID("ffffffff-ffff-ffff-ffff-ffffffffffff")
    scores = (
        RerankScore(chunk_id=uuid.UUID(int=1), score=0.25),
        RerankScore(chunk_id=uuid.UUID(int=2), score=0.75),
    )
    connection = RecordingConnection(tuple(score.chunk_id for score in scores))
    repository = AsyncpgRerankScoreRepository(connection=cast(Any, connection))

    await repository.persist_rerank_scores(
        org_id=org_id,
        retrieval_id=retrieval_id,
        scores=scores,
    )

    query, arguments = connection.calls[0]
    assert "UPDATE retrieval_results" in query
    assert "result.org_id = $1" in query
    assert "result.retrieval_id = $2" in query
    assert "unnest($3::uuid[], $4::double precision[])" in query
    assert "matched.result_count = (SELECT count(*) FROM scored)" in query
    assert arguments == (
        org_id,
        retrieval_id,
        [uuid.UUID(int=1), uuid.UUID(int=2)],
        [0.25, 0.75],
    )


@pytest.mark.asyncio
async def test_asyncpg_repository_rejects_partial_score_persistence() -> None:
    first = RerankScore(chunk_id=uuid.UUID(int=1), score=0.25)
    second = RerankScore(chunk_id=uuid.UUID(int=2), score=0.75)
    connection = RecordingConnection((first.chunk_id,))
    repository = AsyncpgRerankScoreRepository(connection=cast(Any, connection))

    with pytest.raises(RerankPersistenceError, match="every requested"):
        await repository.persist_rerank_scores(
            org_id=uuid.UUID("11111111-1111-1111-1111-111111111111"),
            retrieval_id=uuid.UUID("22222222-2222-2222-2222-222222222222"),
            scores=(first, second),
        )
