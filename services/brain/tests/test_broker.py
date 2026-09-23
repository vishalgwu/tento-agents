"""Regression coverage for concurrent, score-audited context brokerage."""

from __future__ import annotations

import asyncio
import re
from collections.abc import Sequence
from uuid import UUID

import pytest

from brain.context.broker import (
    AsyncpgRetrievalContextUsageRepository,
    ContextBroker,
    ContextBrokerRequest,
    RetrievedContextCase,
    RetrievalContextUsage,
)
from brain.context.budget import ContextBudgeter, ContextFragment, KeyValueFact


class _CountingTokenizer:
    def count(self, text: str) -> int:
        return len(re.findall(r"\S+", text))


class _ConcurrentSources:
    def __init__(self) -> None:
        self.started: set[str] = set()
        self.all_started = asyncio.Event()
        self.release = asyncio.Event()
        self.cases = (
            RetrievedContextCase(
                chunk_id=UUID(int=1),
                fragment=ContextFragment("case " * 1_400),
                bm25_rank=1,
                vector_rank=2,
                rrf_score=0.031,
                rerank_score=0.89,
                final_rank=1,
            ),
            RetrievedContextCase(
                chunk_id=UUID(int=2),
                fragment=ContextFragment("[C2] Prior kitchen drain blockage."),
                bm25_rank=2,
                vector_rank=1,
                rrf_score=0.032,
                rerank_score=0.91,
                final_rank=2,
            ),
        )

    async def _wait(self, name: str) -> None:
        self.started.add(name)
        if len(self.started) == 4:
            self.all_started.set()
        await self.release.wait()

    async def fetch_policy(
        self, *, request: ContextBrokerRequest
    ) -> Sequence[ContextFragment]:
        await self._wait("policy")
        return (ContextFragment("[C1] Follow the applicable plumbing SOP."),)

    async def fetch_unit_asset_facts(
        self, *, request: ContextBrokerRequest
    ) -> Sequence[KeyValueFact]:
        await self._wait("facts")
        return (KeyValueFact("asset", "kitchen sink"),)

    async def fetch_similar_cases(
        self, *, request: ContextBrokerRequest
    ) -> Sequence[RetrievedContextCase]:
        await self._wait("cases")
        return self.cases

    async def fetch_episodic_memory(
        self, *, request: ContextBrokerRequest
    ) -> Sequence[ContextFragment]:
        await self._wait("memory")
        return (ContextFragment("Similar reports started after dishwasher use."),)


class _UsageRepository:
    def __init__(self) -> None:
        self.calls: list[tuple[UUID, UUID, tuple[RetrievalContextUsage, ...]]] = []

    async def persist_context_usage(
        self,
        *,
        org_id: UUID,
        retrieval_id: UUID,
        usage: Sequence[RetrievalContextUsage],
    ) -> None:
        self.calls.append((org_id, retrieval_id, tuple(usage)))


class _Connection:
    def __init__(self, returned_ids: Sequence[UUID]) -> None:
        self.returned_ids = returned_ids
        self.calls: list[tuple[str, tuple[object, ...]]] = []

    async def fetch(self, query: str, *args: object) -> list[dict[str, UUID]]:
        self.calls.append((query, args))
        return [{"kb_chunk_id": value} for value in self.returned_ids]


def _request() -> ContextBrokerRequest:
    return ContextBrokerRequest(
        org_id=UUID(int=10),
        retrieval_id=UUID(int=11),
        system_schema="Use cited maintenance evidence only.",
        current_ticket="Kitchen sink backs up whenever the dishwasher drains.",
    )


@pytest.mark.asyncio
async def test_broker_fetches_all_independent_sources_concurrently_and_persists_scores() -> (
    None
):
    sources = _ConcurrentSources()
    usage_repository = _UsageRepository()
    broker = ContextBroker(
        source_repository=sources,
        usage_repository=usage_repository,
        budgeter=ContextBudgeter(tokenizer=_CountingTokenizer()),
    )
    task = asyncio.create_task(broker.assemble(_request()))

    await asyncio.wait_for(sources.all_started.wait(), timeout=0.5)
    assert sources.started == {"policy", "facts", "cases", "memory"}
    sources.release.set()
    result = await task

    assert "plumbing SOP" in result.budget.render()
    assert "kitchen sink" in result.budget.render()
    assert [entry.used_in_context for entry in result.retrieval_usage] == [False, True]
    assert result.retrieval_usage[0].bm25_rank == 1
    assert result.retrieval_usage[0].vector_rank == 2
    assert result.retrieval_usage[0].rrf_score == 0.031
    assert result.retrieval_usage[0].rerank_score == 0.89
    assert len(usage_repository.calls) == 1
    assert usage_repository.calls[0][2] == result.retrieval_usage


@pytest.mark.asyncio
async def test_asyncpg_usage_repository_writes_all_rank_fields_and_detects_partial_write() -> (
    None
):
    usage = (
        RetrievalContextUsage(
            chunk_id=UUID(int=1),
            bm25_rank=1,
            vector_rank=None,
            rrf_score=0.02,
            rerank_score=0.8,
            final_rank=1,
            used_in_context=True,
        ),
    )
    connection = _Connection(returned_ids=(UUID(int=1),))

    await AsyncpgRetrievalContextUsageRepository(connection).persist_context_usage(
        org_id=UUID(int=10), retrieval_id=UUID(int=11), usage=usage
    )

    query, args = connection.calls[0]
    assert "bm25_rank, vector_rank, rrf_score, rerank_score" in query
    assert "used_in_context" in query
    assert "ON CONFLICT (org_id, retrieval_id, kb_chunk_id) DO UPDATE" in query
    assert args[3:] == ([1], [None], [0.02], [0.8], [1], [True])

    partial = _Connection(returned_ids=())
    with pytest.raises(RuntimeError, match="incomplete"):
        await AsyncpgRetrievalContextUsageRepository(partial).persist_context_usage(
            org_id=UUID(int=10), retrieval_id=UUID(int=11), usage=usage
        )
