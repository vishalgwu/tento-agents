"""Tests for reproducible document-level retrieval evaluation metrics."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from evals.retrieval import (
    RetrievalEvaluationError,
    RetrievalEvaluationItem,
    RetrievalStrategy,
    RerankingVerdict,
    evaluate_rankings,
    load_dataset,
    load_rankings,
    render_markdown_report,
)


def _items() -> tuple[RetrievalEvaluationItem, ...]:
    return (
        RetrievalEvaluationItem(
            identifier="query-1",
            query="drain backs up",
            query_type="natural_resident",
            expected_document_ids=("SOP-PLM-04",),
            should_retrieve=True,
        ),
        RetrievalEvaluationItem(
            identifier="query-2",
            query="lease section 7.3",
            query_type="identifier_lookup",
            expected_document_ids=("LEASE-VA-2025",),
            should_retrieve=True,
            ticket_occurred_at=datetime(2026, 9, 15, tzinfo=UTC),
        ),
        RetrievalEvaluationItem(
            identifier="query-3",
            query="pay rent in bitcoin",
            query_type="no_match",
            expected_document_ids=(),
            should_retrieve=False,
        ),
    )


def _rankings(
    *, rerank_lift: bool
) -> dict[RetrievalStrategy, dict[str, tuple[str, ...]]]:
    return {
        RetrievalStrategy.DENSE_ONLY: {
            "query-1": ("SOP-PLM-04",),
            "query-2": ("OTHER", "LEASE-VA-2025"),
            "query-3": (),
        },
        RetrievalStrategy.LEXICAL_ONLY: {
            "query-1": ("SOP-PLM-04",),
            "query-2": ("LEASE-VA-2025",),
            "query-3": (),
        },
        RetrievalStrategy.HYBRID_RRF: {
            "query-1": ("SOP-PLM-04",),
            "query-2": ("OTHER", "LEASE-VA-2025"),
            "query-3": (),
        },
        RetrievalStrategy.HYBRID_RERANK: {
            "query-1": ("SOP-PLM-04",),
            "query-2": (
                ("LEASE-VA-2025",) if rerank_lift else ("OTHER", "LEASE-VA-2025")
            ),
            "query-3": (),
        },
    }


def test_metrics_are_document_level_and_reranker_is_retained_only_for_a_lift() -> None:
    result = evaluate_rankings(
        items=_items(),
        rankings_by_strategy=_rankings(rerank_lift=True),
        dataset_path=Path("evals/datasets/retrieval_v1.jsonl"),
        git_sha="a" * 40,
    )

    hybrid = result.metrics_by_strategy[RetrievalStrategy.HYBRID_RRF]
    reranked = result.metrics_by_strategy[RetrievalStrategy.HYBRID_RERANK]
    assert hybrid.recall_at_5 == pytest.approx(1.0)
    assert hybrid.recall_at_10 == pytest.approx(1.0)
    assert hybrid.mean_reciprocal_rank == pytest.approx(0.75)
    assert hybrid.ndcg_at_10 == pytest.approx(0.8154648768)
    assert hybrid.no_match_accuracy == pytest.approx(1.0)
    assert reranked.mean_reciprocal_rank == pytest.approx(1.0)
    assert reranked.ndcg_at_10 == pytest.approx(1.0)
    assert result.reranking_verdict is RerankingVerdict.RETAIN


def test_reranker_is_marked_for_removal_without_a_non_regressing_lift() -> None:
    result = evaluate_rankings(
        items=_items(),
        rankings_by_strategy=_rankings(rerank_lift=False),
        dataset_path=Path("evals/datasets/retrieval_v1.jsonl"),
        git_sha="b" * 40,
    )

    assert result.reranking_verdict is RerankingVerdict.REMOVE
    report = render_markdown_report(result)
    assert "Git SHA: `" + ("b" * 40) + "`" in report
    assert "Delete the reranker" in report


def test_dataset_loader_keeps_effective_date_timestamp_and_rejects_bad_lifecycle_data(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    dataset_path = Path("retrieval.jsonl")
    dataset_contents = (
        json.dumps(
            {
                "id": "date-sensitive",
                "query": "was it active?",
                "query_type": "effective_date_sensitive",
                "ticket_occurred_at": "2026-09-15T12:00:00Z",
                "expected_document_ids": ["LEASE-VA-2025"],
                "should_retrieve": True,
            }
        )
        + "\n"
    )

    def read_text(_path: Path, *, encoding: str) -> str:
        assert encoding == "utf-8"
        return dataset_contents

    monkeypatch.setattr(Path, "read_text", read_text)
    items = load_dataset(dataset_path)

    assert items[0].ticket_occurred_at == datetime(2026, 9, 15, 12, tzinfo=UTC)

    dataset_contents = (
        json.dumps(
            {
                "id": "invalid-no-match",
                "query": "nothing",
                "query_type": "no_match",
                "expected_document_ids": ["SOP-PLM-04"],
                "should_retrieve": False,
            }
        )
        + "\n"
    )
    with pytest.raises(RetrievalEvaluationError, match="no-match"):
        load_dataset(dataset_path)


def test_rankings_must_cover_every_item_and_never_repeat_a_document(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rankings_path = Path("rankings.json")
    rankings_contents = json.dumps(
        {
            strategy.value: {"query-1": ["SOP-PLM-04", "SOP-PLM-04"]}
            for strategy in RetrievalStrategy
        }
    )

    def read_text(_path: Path, *, encoding: str) -> str:
        assert encoding == "utf-8"
        return rankings_contents

    monkeypatch.setattr(Path, "read_text", read_text)

    with pytest.raises(RetrievalEvaluationError, match="duplicate"):
        load_rankings(rankings_path)
    with pytest.raises(RetrievalEvaluationError, match="do not match dataset IDs"):
        evaluate_rankings(
            items=_items(),
            rankings_by_strategy={
                strategy: {"query-1": ("SOP-PLM-04",)} for strategy in RetrievalStrategy
            },
            dataset_path=Path("evals/datasets/retrieval_v1.jsonl"),
            git_sha="c" * 40,
        )
