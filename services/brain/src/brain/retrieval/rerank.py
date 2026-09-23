"""Cross-encoder reranking for the hybrid retrieval candidate set.

The default ``BAAI/bge-reranker-v2-m3`` model is held in one process-wide,
module-level singleton. It is lazily initialized inside a worker thread so the
first model download/load never blocks the event loop, then reused for every
subsequent request in that process. Candidate scoring is bounded to the top 30
hybrid results and returns the best six. Scores for every considered candidate
are persisted to ``retrieval_results`` for later trace inspection and evaluation.
"""

from __future__ import annotations

import asyncio
import importlib
import math
import threading
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Final, Protocol

import asyncpg  # type: ignore[import-untyped]

from brain.retrieval.hybrid import HybridRetrievalHit


RERANKER_MODEL: Final = "BAAI/bge-reranker-v2-m3"
RERANK_CANDIDATE_LIMIT: Final = 30
RERANK_RESULT_LIMIT: Final = 6
DEFAULT_INFERENCE_BATCH_SIZE: Final = 8


class RerankPersistenceError(RuntimeError):
    """Raised when a retrieval score cannot be persisted under tenant scope."""


class CrossEncoderModel(Protocol):
    """The narrow synchronous model surface needed by the async reranker."""

    def predict(
        self,
        sentences: Sequence[tuple[str, str]],
        *,
        batch_size: int,
        show_progress_bar: bool,
    ) -> Sequence[float]:
        """Return one relevance score for each query/document pair."""


class RerankScoreRepository(Protocol):
    """Tenant-scoped persistence for scores added after hybrid retrieval."""

    async def persist_rerank_scores(
        self,
        *,
        org_id: uuid.UUID,
        retrieval_id: uuid.UUID,
        scores: Sequence[RerankScore],
    ) -> None:
        """Atomically write all supplied scores to existing retrieval results."""


@dataclass(frozen=True, slots=True)
class RerankRequest:
    """The ledger identity and candidate set for one rerank operation."""

    org_id: uuid.UUID
    retrieval_id: uuid.UUID
    query: str
    candidates: Sequence[HybridRetrievalHit]


@dataclass(frozen=True, slots=True)
class RerankScore:
    """A finite cross-encoder score for one previously persisted chunk result."""

    chunk_id: uuid.UUID
    score: float

    def __post_init__(self) -> None:
        if not isinstance(self.chunk_id, uuid.UUID):
            raise ValueError("chunk_id must be a UUID")
        if not math.isfinite(self.score):
            raise ValueError("rerank score must be finite")


@dataclass(frozen=True, slots=True)
class RerankedRetrievalHit:
    """A selected hybrid hit with its persisted cross-encoder score and rank."""

    hybrid_hit: HybridRetrievalHit
    rerank_score: float
    rerank_rank: int


_process_reranker_model: CrossEncoderModel | None = None
_process_reranker_lock = threading.Lock()


def get_process_reranker_model() -> CrossEncoderModel:
    """Return the one model instance for this worker process.

    Delaying initialization until the first authorized rerank avoids an
    import-time model download in API-only processes and test collection. The
    module-level lock guarantees that concurrent first requests cannot each load
    a separate model.
    """

    global _process_reranker_model
    with _process_reranker_lock:
        if _process_reranker_model is None:
            _process_reranker_model = _load_cross_encoder_model()
        return _process_reranker_model


def _load_cross_encoder_model() -> CrossEncoderModel:
    """Create the fixed cross-encoder without enabling remote executable code."""

    # Sentence Transformers imports PyTorch. Keep that cost out of API-only
    # processes and unit-test collection; this loader still runs only once per
    # worker because ``get_process_reranker_model`` owns the module singleton.
    package = importlib.import_module("sentence_transformers")
    cross_encoder_class = getattr(package, "CrossEncoder", None)
    if cross_encoder_class is None:
        raise RuntimeError("sentence_transformers.CrossEncoder is unavailable")
    return cross_encoder_class(RERANKER_MODEL, trust_remote_code=False)


@dataclass(slots=True)
class CrossEncoderReranker:
    """Score 30 hybrid candidates, persist all scores, and return the best six."""

    score_repository: RerankScoreRepository
    model: CrossEncoderModel | None = None
    inference_batch_size: int = DEFAULT_INFERENCE_BATCH_SIZE

    def __post_init__(self) -> None:
        if (
            type(self.inference_batch_size) is not int
            or not 1 <= self.inference_batch_size <= RERANK_CANDIDATE_LIMIT
        ):
            raise ValueError(
                f"inference_batch_size must be between 1 and {RERANK_CANDIDATE_LIMIT}"
            )

    async def rerank(self, request: RerankRequest) -> tuple[RerankedRetrievalHit, ...]:
        """Score top hybrid candidates without loading or running a model on-loop."""

        query = _require_non_blank(request.query, "query")
        candidates = _select_rerank_candidates(request.candidates)
        if not candidates:
            return ()

        scores = await asyncio.to_thread(
            _predict_scores,
            self.model,
            query,
            candidates,
            self.inference_batch_size,
        )
        score_records = tuple(
            RerankScore(chunk_id=hit.chunk.chunk_id, score=score)
            for hit, score in zip(candidates, scores, strict=True)
        )
        await self.score_repository.persist_rerank_scores(
            org_id=request.org_id,
            retrieval_id=request.retrieval_id,
            scores=score_records,
        )
        ranked = sorted(
            zip(candidates, score_records, strict=True),
            key=lambda item: (
                -item[1].score,
                item[0].final_rank,
                str(item[0].chunk.chunk_id),
            ),
        )
        return tuple(
            RerankedRetrievalHit(
                hybrid_hit=hybrid_hit,
                rerank_score=score.score,
                rerank_rank=rank,
            )
            for rank, (hybrid_hit, score) in enumerate(
                ranked[:RERANK_RESULT_LIMIT], start=1
            )
        )


class AsyncpgRerankScoreRepository:
    """Persist rerank scores through an RLS-bound PostgreSQL connection.

    The caller owns the transaction and must establish tenant context before
    constructing this adapter. The explicit ``org_id`` predicate is retained as
    defence in depth. The one set-based update either records every requested
    score or raises, rather than silently leaving a partial retrieval trace.
    """

    def __init__(self, connection: asyncpg.Connection) -> None:
        self._connection = connection

    async def persist_rerank_scores(
        self,
        *,
        org_id: uuid.UUID,
        retrieval_id: uuid.UUID,
        scores: Sequence[RerankScore],
    ) -> None:
        if not scores:
            return
        chunk_ids = tuple(score.chunk_id for score in scores)
        if len(chunk_ids) != len(set(chunk_ids)):
            raise ValueError("rerank scores must contain each chunk at most once")
        rows = await self._connection.fetch(
            """
            WITH scored(kb_chunk_id, rerank_score) AS (
                SELECT *
                FROM unnest($3::uuid[], $4::double precision[])
            ),
            matched AS (
                SELECT count(*) AS result_count
                FROM retrieval_results AS result
                JOIN scored ON scored.kb_chunk_id = result.kb_chunk_id
                WHERE result.org_id = $1
                  AND result.retrieval_id = $2
            ),
            updated AS (
                UPDATE retrieval_results AS result
                SET rerank_score = scored.rerank_score::numeric
                FROM scored, matched
                WHERE result.org_id = $1
                  AND result.retrieval_id = $2
                  AND result.kb_chunk_id = scored.kb_chunk_id
                  AND matched.result_count = (SELECT count(*) FROM scored)
                RETURNING result.kb_chunk_id
            )
            SELECT kb_chunk_id FROM updated
            """,
            org_id,
            retrieval_id,
            list(chunk_ids),
            [score.score for score in scores],
        )
        persisted_ids: set[uuid.UUID] = set()
        for row in rows:
            chunk_id = row["kb_chunk_id"]
            if not isinstance(chunk_id, uuid.UUID):
                raise RerankPersistenceError(
                    "retrieval score persistence returned an invalid chunk ID"
                )
            persisted_ids.add(chunk_id)
        expected_ids = set(chunk_ids)
        if persisted_ids != expected_ids:
            raise RerankPersistenceError(
                "retrieval score persistence did not update every requested result"
            )


def _select_rerank_candidates(
    candidates: Sequence[HybridRetrievalHit],
) -> tuple[HybridRetrievalHit, ...]:
    """Use at most the 30 best RRF hits with deterministic tie handling."""

    ordered = tuple(
        sorted(
            candidates,
            key=lambda hit: (hit.final_rank, str(hit.chunk.chunk_id)),
        )
    )
    chunk_ids: set[uuid.UUID] = set()
    final_ranks: set[int] = set()
    for hit in ordered:
        if hit.final_rank <= 0:
            raise ValueError("hybrid hit final_rank must be positive")
        if hit.chunk.chunk_id in chunk_ids:
            raise ValueError("hybrid candidates must not repeat a chunk")
        if hit.final_rank in final_ranks:
            raise ValueError("hybrid candidates must not repeat final_rank")
        chunk_ids.add(hit.chunk.chunk_id)
        final_ranks.add(hit.final_rank)
    return ordered[:RERANK_CANDIDATE_LIMIT]


def _predict_scores(
    injected_model: CrossEncoderModel | None,
    query: str,
    candidates: Sequence[HybridRetrievalHit],
    batch_size: int,
) -> tuple[float, ...]:
    """Run synchronous inference in a worker thread and validate model output."""

    model = (
        injected_model if injected_model is not None else get_process_reranker_model()
    )
    pairs = tuple((query, hit.chunk.content) for hit in candidates)
    raw_scores = model.predict(
        pairs,
        batch_size=batch_size,
        show_progress_bar=False,
    )
    if len(raw_scores) != len(candidates):
        raise RuntimeError("reranker model returned an unexpected score count")
    scores = tuple(float(score) for score in raw_scores)
    if not all(math.isfinite(score) for score in scores):
        raise RuntimeError("reranker model returned a non-finite score")
    return scores


def _require_non_blank(value: str, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must be a non-blank string")
    return value.strip()
