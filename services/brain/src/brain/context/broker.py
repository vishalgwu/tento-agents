"""Concurrent, auditable assembly of bounded evidence context for an agent."""

from __future__ import annotations

import asyncio
import math
import uuid
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol

import asyncpg  # type: ignore[import-untyped]

from brain.context.budget import (
    ContextBudget,
    ContextBudgetRequest,
    ContextBudgeter,
    ContextFragment,
    ContextSlot,
    KeyValueFact,
)


@dataclass(frozen=True, slots=True)
class ContextBrokerRequest:
    """One tenant-scoped context request for a pre-existing retrieval ledger row."""

    org_id: uuid.UUID
    retrieval_id: uuid.UUID
    system_schema: str
    current_ticket: str

    def __post_init__(self) -> None:
        if not self.system_schema.strip():
            raise ValueError("system_schema must be non-blank")
        if not self.current_ticket.strip():
            raise ValueError("current_ticket must be non-blank")


@dataclass(frozen=True, slots=True)
class RetrievedContextCase:
    """A ranked similar-case chunk and every score retained for trace replay."""

    chunk_id: uuid.UUID
    fragment: ContextFragment
    bm25_rank: int | None
    vector_rank: int | None
    rrf_score: float
    rerank_score: float | None
    final_rank: int

    def __post_init__(self) -> None:
        if not isinstance(self.chunk_id, uuid.UUID):
            raise ValueError("chunk_id must be a UUID")
        for rank, field_name in (
            (self.bm25_rank, "bm25_rank"),
            (self.vector_rank, "vector_rank"),
        ):
            if rank is not None and (type(rank) is not int or rank <= 0):
                raise ValueError(f"{field_name} must be a positive integer or null")
        if not math.isfinite(self.rrf_score) or self.rrf_score <= 0:
            raise ValueError("rrf_score must be a finite positive number")
        if self.rerank_score is not None and not math.isfinite(self.rerank_score):
            raise ValueError("rerank_score must be finite when present")
        if type(self.final_rank) is not int or self.final_rank <= 0:
            raise ValueError("final_rank must be a positive integer")


@dataclass(frozen=True, slots=True)
class RetrievalContextUsage:
    """The five retrieval fields persisted for every candidate chunk."""

    chunk_id: uuid.UUID
    bm25_rank: int | None
    vector_rank: int | None
    rrf_score: float
    rerank_score: float | None
    final_rank: int
    used_in_context: bool


@dataclass(frozen=True, slots=True)
class BrokeredContext:
    """Bounded prompt context plus the immutable selection trace for similar cases."""

    budget: ContextBudget
    retrieval_usage: tuple[RetrievalContextUsage, ...]


class ContextSourceRepository(Protocol):
    """Read-only context sources; each operation is independent and parallelisable."""

    async def fetch_policy(
        self, *, request: ContextBrokerRequest
    ) -> Sequence[ContextFragment]:
        """Return pre-ranked applicable policy passages."""

    async def fetch_unit_asset_facts(
        self, *, request: ContextBrokerRequest
    ) -> Sequence[KeyValueFact]:
        """Return current unit and asset facts in deterministic display order."""

    async def fetch_similar_cases(
        self, *, request: ContextBrokerRequest
    ) -> Sequence[RetrievedContextCase]:
        """Return pre-ranked similar cases with every retrieval score."""

    async def fetch_episodic_memory(
        self, *, request: ContextBrokerRequest
    ) -> Sequence[ContextFragment]:
        """Return pre-ranked, lifecycle-eligible episodic summaries."""


class RetrievalContextUsageRepository(Protocol):
    """Writes only retrieval score/selection fields under the caller's RLS scope."""

    async def persist_context_usage(
        self,
        *,
        org_id: uuid.UUID,
        retrieval_id: uuid.UUID,
        usage: Sequence[RetrievalContextUsage],
    ) -> None:
        """Persist rank, fusion, rerank, final rank, and used-in-context state."""


@dataclass(slots=True)
class ContextBroker:
    """Fetch all independent sources concurrently, budget, then persist selection."""

    source_repository: ContextSourceRepository
    usage_repository: RetrievalContextUsageRepository
    budgeter: ContextBudgeter

    async def assemble(self, request: ContextBrokerRequest) -> BrokeredContext:
        """Build one complete context envelope without serial I/O or hidden trimming."""

        policy, unit_asset_facts, similar_cases, episodic_memory = await asyncio.gather(
            self.source_repository.fetch_policy(request=request),
            self.source_repository.fetch_unit_asset_facts(request=request),
            self.source_repository.fetch_similar_cases(request=request),
            self.source_repository.fetch_episodic_memory(request=request),
        )
        cases = _validate_cases(similar_cases)
        budget = self.budgeter.build(
            ContextBudgetRequest(
                system_schema=request.system_schema,
                current_ticket=request.current_ticket,
                policy=tuple(policy),
                unit_asset_facts=tuple(unit_asset_facts),
                similar_cases=tuple(case.fragment for case in cases),
                conversation_summary=tuple(episodic_memory),
            )
        )
        usage = _usage_from_budget(cases, budget)
        await self.usage_repository.persist_context_usage(
            org_id=request.org_id,
            retrieval_id=request.retrieval_id,
            usage=usage,
        )
        return BrokeredContext(budget=budget, retrieval_usage=usage)


class AsyncpgRetrievalContextUsageRepository:
    """Persist every score and final context selection through an RLS-bound connection."""

    def __init__(self, connection: asyncpg.Connection) -> None:
        self._connection = connection

    async def persist_context_usage(
        self,
        *,
        org_id: uuid.UUID,
        retrieval_id: uuid.UUID,
        usage: Sequence[RetrievalContextUsage],
    ) -> None:
        if not usage:
            return
        _validate_usage(usage)
        rows = await self._connection.fetch(
            """
            WITH selected(
                kb_chunk_id, bm25_rank, vector_rank, rrf_score, rerank_score,
                final_rank, used_in_context
            ) AS (
                SELECT *
                FROM unnest(
                    $3::uuid[], $4::integer[], $5::integer[], $6::numeric[],
                    $7::numeric[], $8::integer[], $9::boolean[]
                )
            ),
            written AS (
                INSERT INTO retrieval_results (
                    org_id, retrieval_id, kb_chunk_id, bm25_rank, vector_rank,
                    rrf_score, rerank_score, final_rank, used_in_context
                )
                SELECT
                    $1, $2, kb_chunk_id, bm25_rank, vector_rank, rrf_score,
                    rerank_score, final_rank, used_in_context
                FROM selected
                ON CONFLICT (org_id, retrieval_id, kb_chunk_id) DO UPDATE
                SET bm25_rank = EXCLUDED.bm25_rank,
                    vector_rank = EXCLUDED.vector_rank,
                    rrf_score = EXCLUDED.rrf_score,
                    rerank_score = EXCLUDED.rerank_score,
                    final_rank = EXCLUDED.final_rank,
                    used_in_context = EXCLUDED.used_in_context
                RETURNING kb_chunk_id
            )
            SELECT kb_chunk_id FROM written
            """,
            org_id,
            retrieval_id,
            [entry.chunk_id for entry in usage],
            [entry.bm25_rank for entry in usage],
            [entry.vector_rank for entry in usage],
            [entry.rrf_score for entry in usage],
            [entry.rerank_score for entry in usage],
            [entry.final_rank for entry in usage],
            [entry.used_in_context for entry in usage],
        )
        persisted_chunk_ids = {row["kb_chunk_id"] for row in rows}
        expected_chunk_ids = {entry.chunk_id for entry in usage}
        if persisted_chunk_ids != expected_chunk_ids:
            raise RuntimeError("retrieval context usage persistence was incomplete")


def _usage_from_budget(
    cases: Sequence[RetrievedContextCase], budget: ContextBudget
) -> tuple[RetrievalContextUsage, ...]:
    selected_texts = Counter(budget.slots[ContextSlot.SIMILAR_CASES].included_blocks)
    usage: list[RetrievalContextUsage] = []
    for case in cases:
        used_in_context = selected_texts[case.fragment.text] > 0
        if used_in_context:
            selected_texts[case.fragment.text] -= 1
        usage.append(
            RetrievalContextUsage(
                chunk_id=case.chunk_id,
                bm25_rank=case.bm25_rank,
                vector_rank=case.vector_rank,
                rrf_score=case.rrf_score,
                rerank_score=case.rerank_score,
                final_rank=case.final_rank,
                used_in_context=used_in_context,
            )
        )
    return tuple(usage)


def _validate_cases(
    cases: Sequence[RetrievedContextCase],
) -> tuple[RetrievedContextCase, ...]:
    values = tuple(cases)
    chunk_ids = {case.chunk_id for case in values}
    final_ranks = {case.final_rank for case in values}
    if len(chunk_ids) != len(values):
        raise ValueError("similar cases must not repeat a chunk")
    if len(final_ranks) != len(values):
        raise ValueError("similar cases must not repeat final_rank")
    if tuple(sorted(final_ranks)) != tuple(range(1, len(values) + 1)):
        raise ValueError("similar cases must be ordered by consecutive final_rank")
    return values


def _validate_usage(usage: Sequence[RetrievalContextUsage]) -> None:
    chunk_ids = {entry.chunk_id for entry in usage}
    final_ranks = {entry.final_rank for entry in usage}
    if len(chunk_ids) != len(usage) or len(final_ranks) != len(usage):
        raise ValueError("retrieval usage must have unique chunks and final ranks")
