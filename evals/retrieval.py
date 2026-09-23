"""Offline retrieval benchmark scoring and Git-SHA-stamped report generation.

Rankings are supplied by the retrieval runner rather than generated here. That
keeps the metric implementation deterministic, lets all four retrieval
strategies be compared against identical human-authored queries, and prevents a
report from claiming results for an index that has not actually been run.
"""

from __future__ import annotations

import argparse
import json
import math
import re
import subprocess
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Final, cast


RECALL_CUTOFFS: Final = (5, 10)
NDCG_CUTOFF: Final = 10
GIT_SHA_PATTERN: Final = re.compile(r"^[0-9a-f]{7,40}$")


class RetrievalStrategy(str, Enum):
    """The fixed strategies that are meaningful to compare in this project."""

    DENSE_ONLY = "dense_only"
    LEXICAL_ONLY = "lexical_only"
    HYBRID_RRF = "hybrid_rrf"
    HYBRID_RERANK = "hybrid_rerank"


class RerankingVerdict(str, Enum):
    """The measurable retention decision for the optional cross-encoder."""

    RETAIN = "retain"
    REMOVE = "remove"


class RetrievalEvaluationError(ValueError):
    """Raised for invalid datasets, rankings, or an unreproducible report."""


@dataclass(frozen=True, slots=True)
class RetrievalEvaluationItem:
    """One human-authored expected-document query from the evaluation corpus."""

    identifier: str
    query: str
    query_type: str
    expected_document_ids: tuple[str, ...]
    should_retrieve: bool
    ticket_occurred_at: datetime | None = None

    def __post_init__(self) -> None:
        _require_non_blank(self.identifier, "identifier")
        _require_non_blank(self.query, "query")
        _require_non_blank(self.query_type, "query_type")
        if not isinstance(self.should_retrieve, bool):
            raise RetrievalEvaluationError("should_retrieve must be a boolean")
        if len(self.expected_document_ids) != len(set(self.expected_document_ids)):
            raise RetrievalEvaluationError(
                "expected_document_ids must not contain duplicates"
            )
        for document_id in self.expected_document_ids:
            _require_non_blank(document_id, "expected_document_ids entries")
        if self.should_retrieve and not self.expected_document_ids:
            raise RetrievalEvaluationError(
                "retrievable items must specify expected_document_ids"
            )
        if not self.should_retrieve and self.expected_document_ids:
            raise RetrievalEvaluationError(
                "no-match items must not specify expected_document_ids"
            )
        if self.ticket_occurred_at is not None and (
            self.ticket_occurred_at.tzinfo is None
            or self.ticket_occurred_at.utcoffset() is None
        ):
            raise RetrievalEvaluationError(
                "ticket_occurred_at must be timezone-aware when provided"
            )


@dataclass(frozen=True, slots=True)
class StrategyMetrics:
    """Macro query-level retrieval metrics for one ranked-result strategy."""

    query_count: int
    answerable_query_count: int
    no_match_query_count: int
    recall_at_5: float
    recall_at_10: float
    mean_reciprocal_rank: float
    ndcg_at_10: float
    no_match_accuracy: float

    def __post_init__(self) -> None:
        if self.query_count < 1:
            raise RetrievalEvaluationError("query_count must be positive")
        if self.answerable_query_count < 1:
            raise RetrievalEvaluationError("at least one query must be answerable")
        if self.no_match_query_count < 0:
            raise RetrievalEvaluationError("no_match_query_count must be non-negative")
        for metric_name, value in (
            ("recall_at_5", self.recall_at_5),
            ("recall_at_10", self.recall_at_10),
            ("mean_reciprocal_rank", self.mean_reciprocal_rank),
            ("ndcg_at_10", self.ndcg_at_10),
            ("no_match_accuracy", self.no_match_accuracy),
        ):
            if not 0 <= value <= 1:
                raise RetrievalEvaluationError(
                    f"{metric_name} must be between zero and one"
                )


@dataclass(frozen=True, slots=True)
class RetrievalEvaluationResult:
    """All strategy metrics plus the required reranker retention decision."""

    dataset_path: Path
    git_sha: str
    metrics_by_strategy: Mapping[RetrievalStrategy, StrategyMetrics]
    reranking_verdict: RerankingVerdict

    def __post_init__(self) -> None:
        if not isinstance(self.dataset_path, Path):
            raise RetrievalEvaluationError("dataset_path must be a Path")
        if not GIT_SHA_PATTERN.fullmatch(self.git_sha):
            raise RetrievalEvaluationError(
                "git_sha must be a short or full lowercase SHA"
            )
        if set(self.metrics_by_strategy) != set(RetrievalStrategy):
            raise RetrievalEvaluationError(
                "metrics must be supplied for every required retrieval strategy"
            )


def load_dataset(path: Path) -> tuple[RetrievalEvaluationItem, ...]:
    """Load and validate the human-authored retrieval JSONL corpus."""

    items: list[RetrievalEvaluationItem] = []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as error:
        raise RetrievalEvaluationError(f"could not read dataset {path}") from error
    for line_number, line in enumerate(lines, start=1):
        if not line.strip():
            raise RetrievalEvaluationError(
                f"dataset {path} contains a blank line at {line_number}"
            )
        try:
            payload: object = json.loads(line)
        except json.JSONDecodeError as error:
            raise RetrievalEvaluationError(
                f"dataset {path} has invalid JSON at line {line_number}"
            ) from error
        items.append(_parse_dataset_item(payload, path, line_number))
    if not items:
        raise RetrievalEvaluationError(f"dataset {path} must contain at least one item")
    identifiers = [item.identifier for item in items]
    if len(identifiers) != len(set(identifiers)):
        raise RetrievalEvaluationError(f"dataset {path} contains duplicate item IDs")
    return tuple(items)


def load_rankings(
    path: Path,
) -> Mapping[RetrievalStrategy, Mapping[str, tuple[str, ...]]]:
    """Load strategy-to-query ranked document IDs from a JSON object.

    The accepted structure is ``{"dense_only": {"retrieval-001":
    ["SOP-PLM-04", ...]}, ...}``. Each ranking must contain document IDs in
    descending relevance order and must have no duplicates.
    """

    try:
        payload: object = json.loads(path.read_text(encoding="utf-8"))
    except OSError as error:
        raise RetrievalEvaluationError(f"could not read rankings {path}") from error
    except json.JSONDecodeError as error:
        raise RetrievalEvaluationError(f"rankings {path} are not valid JSON") from error
    if not isinstance(payload, dict):
        raise RetrievalEvaluationError("rankings must be a JSON object")

    rankings: dict[RetrievalStrategy, Mapping[str, tuple[str, ...]]] = {}
    expected_names = {strategy.value for strategy in RetrievalStrategy}
    if set(payload) != expected_names:
        raise RetrievalEvaluationError(
            "rankings must contain exactly dense_only, lexical_only, hybrid_rrf, and hybrid_rerank"
        )
    for strategy in RetrievalStrategy:
        raw_strategy_rankings = payload[strategy.value]
        if not isinstance(raw_strategy_rankings, dict):
            raise RetrievalEvaluationError(
                f"{strategy.value} rankings must map item IDs to document ID arrays"
            )
        parsed_rankings: dict[str, tuple[str, ...]] = {}
        for item_id, raw_ranking in raw_strategy_rankings.items():
            if not isinstance(item_id, str) or not item_id.strip():
                raise RetrievalEvaluationError(
                    f"{strategy.value} has an invalid evaluation item ID"
                )
            if not isinstance(raw_ranking, list) or not all(
                isinstance(document_id, str) and document_id.strip()
                for document_id in raw_ranking
            ):
                raise RetrievalEvaluationError(
                    f"{strategy.value} ranking for {item_id} must be a document ID array"
                )
            ranking = tuple(cast(str, document_id) for document_id in raw_ranking)
            if len(ranking) != len(set(ranking)):
                raise RetrievalEvaluationError(
                    f"{strategy.value} ranking for {item_id} contains duplicate document IDs"
                )
            parsed_rankings[item_id] = ranking
        rankings[strategy] = parsed_rankings
    return rankings


def evaluate_rankings(
    *,
    items: Sequence[RetrievalEvaluationItem],
    rankings_by_strategy: Mapping[RetrievalStrategy, Mapping[str, Sequence[str]]],
    dataset_path: Path,
    git_sha: str,
) -> RetrievalEvaluationResult:
    """Measure the four fixed strategies on the same complete benchmark."""

    _validate_items(items)
    normalized_sha = _validate_git_sha(git_sha)
    if set(rankings_by_strategy) != set(RetrievalStrategy):
        raise RetrievalEvaluationError(
            "rankings must be supplied for every required retrieval strategy"
        )
    metrics_by_strategy = {
        strategy: _evaluate_strategy(
            items=items,
            rankings=_validate_strategy_rankings(
                strategy=strategy,
                items=items,
                rankings=rankings_by_strategy[strategy],
            ),
        )
        for strategy in RetrievalStrategy
    }
    return RetrievalEvaluationResult(
        dataset_path=dataset_path,
        git_sha=normalized_sha,
        metrics_by_strategy=metrics_by_strategy,
        reranking_verdict=_reranking_verdict(metrics_by_strategy),
    )


def render_markdown_report(result: RetrievalEvaluationResult) -> str:
    """Render a publishable metric table whose provenance includes the Git SHA."""

    lines = [
        "# Retrieval evaluation",
        "",
        f"- Dataset: `{result.dataset_path.as_posix()}`",
        f"- Git SHA: `{result.git_sha}`",
        "- Metrics are macro-averaged over answerable queries; no-match accuracy is reported separately.",
        "",
        "| Strategy | Recall@5 | Recall@10 | MRR | nDCG@10 | No-match accuracy |",
        "| --- | ---: | ---: | ---: | ---: | ---: |",
    ]
    for strategy in RetrievalStrategy:
        metrics = result.metrics_by_strategy[strategy]
        lines.append(
            "| "
            f"{_strategy_label(strategy)} | "
            f"{metrics.recall_at_5:.4f} | "
            f"{metrics.recall_at_10:.4f} | "
            f"{metrics.mean_reciprocal_rank:.4f} | "
            f"{metrics.ndcg_at_10:.4f} | "
            f"{metrics.no_match_accuracy:.4f} |"
        )
    lines.extend(
        [
            "",
            "## Reranker disposition",
            "",
            _reranking_message(result.reranking_verdict),
            "",
        ]
    )
    return "\n".join(lines)


def write_report(path: Path, report: str) -> None:
    """Atomically publish a completed report only after all measurements exist."""

    if not report.strip():
        raise RetrievalEvaluationError("report must not be blank")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = path.with_suffix(path.suffix + ".tmp")
    try:
        temporary_path.write_text(report, encoding="utf-8")
        temporary_path.replace(path)
    except OSError as error:
        raise RetrievalEvaluationError(f"could not write report {path}") from error


def resolve_git_sha(repository_root: Path) -> str:
    """Resolve the exact checked-out Git revision used for an evaluation run."""

    try:
        completed = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=repository_root,
            check=False,
            capture_output=True,
            text=True,
        )
    except OSError as error:
        raise RetrievalEvaluationError(
            "Git is required to publish evaluation metrics"
        ) from error
    if completed.returncode != 0:
        raise RetrievalEvaluationError("Git is required to publish evaluation metrics")
    return _validate_git_sha(completed.stdout.strip())


def main(argv: Sequence[str] | None = None) -> int:
    """Run a complete comparison and publish its report to the requested path."""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dataset",
        type=Path,
        default=Path(__file__).with_name("datasets") / "retrieval_v1.jsonl",
        help="Human-authored retrieval JSONL dataset.",
    )
    parser.add_argument(
        "--rankings",
        required=True,
        type=Path,
        help="JSON rankings for dense, lexical, hybrid, and reranked strategies.",
    )
    parser.add_argument(
        "--output",
        required=True,
        type=Path,
        help="Markdown report destination. Commit this file with its Git SHA.",
    )
    parser.add_argument(
        "--git-sha",
        help="Optional explicit checked-out Git SHA; defaults to git rev-parse HEAD.",
    )
    parser.add_argument(
        "--require-rerank-lift",
        action="store_true",
        help="Exit non-zero when hybrid + rerank does not improve without regression.",
    )
    arguments = parser.parse_args(argv)
    repository_root = Path(__file__).resolve().parents[1]
    git_sha = arguments.git_sha or resolve_git_sha(repository_root)
    result = evaluate_rankings(
        items=load_dataset(arguments.dataset),
        rankings_by_strategy=load_rankings(arguments.rankings),
        dataset_path=arguments.dataset,
        git_sha=git_sha,
    )
    report = render_markdown_report(result)
    write_report(arguments.output, report)
    if (
        arguments.require_rerank_lift
        and result.reranking_verdict is RerankingVerdict.REMOVE
    ):
        return 2
    return 0


def _parse_dataset_item(
    payload: object, path: Path, line_number: int
) -> RetrievalEvaluationItem:
    if not isinstance(payload, dict):
        raise RetrievalEvaluationError(
            f"dataset {path} line {line_number} must be a JSON object"
        )
    expected_fields = {
        "id",
        "query",
        "query_type",
        "expected_document_ids",
        "should_retrieve",
        "ticket_occurred_at",
    }
    unexpected_fields = set(payload).difference(expected_fields)
    if unexpected_fields:
        raise RetrievalEvaluationError(
            f"dataset {path} line {line_number} has unexpected fields"
        )
    identifier = _required_string(payload, "id", path, line_number)
    query = _required_string(payload, "query", path, line_number)
    query_type = _required_string(payload, "query_type", path, line_number)
    should_retrieve = payload.get("should_retrieve")
    if not isinstance(should_retrieve, bool):
        raise RetrievalEvaluationError(
            f"dataset {path} line {line_number} should_retrieve must be a boolean"
        )
    raw_document_ids = payload.get("expected_document_ids")
    if not isinstance(raw_document_ids, list) or not all(
        isinstance(document_id, str) for document_id in raw_document_ids
    ):
        raise RetrievalEvaluationError(
            f"dataset {path} line {line_number} expected_document_ids must be a string array"
        )
    occurred_at = _parse_optional_timestamp(
        payload.get("ticket_occurred_at"), path, line_number
    )
    return RetrievalEvaluationItem(
        identifier=identifier,
        query=query,
        query_type=query_type,
        expected_document_ids=tuple(
            cast(str, document_id) for document_id in raw_document_ids
        ),
        should_retrieve=should_retrieve,
        ticket_occurred_at=occurred_at,
    )


def _required_string(
    payload: Mapping[str, object], field_name: str, path: Path, line_number: int
) -> str:
    value = payload.get(field_name)
    if not isinstance(value, str) or not value.strip():
        raise RetrievalEvaluationError(
            f"dataset {path} line {line_number} {field_name} must be non-blank"
        )
    return value


def _parse_optional_timestamp(
    value: object, path: Path, line_number: int
) -> datetime | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise RetrievalEvaluationError(
            f"dataset {path} line {line_number} ticket_occurred_at must be a string"
        )
    try:
        occurred_at = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise RetrievalEvaluationError(
            f"dataset {path} line {line_number} has an invalid ticket_occurred_at"
        ) from error
    if occurred_at.tzinfo is None or occurred_at.utcoffset() is None:
        raise RetrievalEvaluationError(
            f"dataset {path} line {line_number} ticket_occurred_at must include a timezone"
        )
    return occurred_at


def _validate_items(items: Sequence[RetrievalEvaluationItem]) -> None:
    if not items:
        raise RetrievalEvaluationError("items must not be empty")
    if any(not isinstance(item, RetrievalEvaluationItem) for item in items):
        raise RetrievalEvaluationError(
            "items must contain only RetrievalEvaluationItem values"
        )
    identifiers = [item.identifier for item in items]
    if len(identifiers) != len(set(identifiers)):
        raise RetrievalEvaluationError("items must have unique identifiers")


def _validate_strategy_rankings(
    *,
    strategy: RetrievalStrategy,
    items: Sequence[RetrievalEvaluationItem],
    rankings: Mapping[str, Sequence[str]],
) -> Mapping[str, tuple[str, ...]]:
    item_ids = {item.identifier for item in items}
    if set(rankings) != item_ids:
        missing = sorted(item_ids.difference(rankings))
        unknown = sorted(set(rankings).difference(item_ids))
        raise RetrievalEvaluationError(
            f"{strategy.value} rankings do not match dataset IDs; "
            f"missing={missing}, unknown={unknown}"
        )
    validated: dict[str, tuple[str, ...]] = {}
    for item_id, ranking in rankings.items():
        if isinstance(ranking, (str, bytes)) or not isinstance(ranking, Sequence):
            raise RetrievalEvaluationError(
                f"{strategy.value} ranking for {item_id} must be a sequence of document IDs"
            )
        normalized = tuple(ranking)
        if any(
            not isinstance(document_id, str) or not document_id.strip()
            for document_id in normalized
        ):
            raise RetrievalEvaluationError(
                f"{strategy.value} ranking for {item_id} has an invalid document ID"
            )
        if len(normalized) != len(set(normalized)):
            raise RetrievalEvaluationError(
                f"{strategy.value} ranking for {item_id} contains duplicate document IDs"
            )
        validated[item_id] = normalized
    return validated


def _evaluate_strategy(
    *,
    items: Sequence[RetrievalEvaluationItem],
    rankings: Mapping[str, tuple[str, ...]],
) -> StrategyMetrics:
    answerable = tuple(item for item in items if item.should_retrieve)
    no_match = tuple(item for item in items if not item.should_retrieve)
    recall_at_5 = _mean(
        _recall_at(item.expected_document_ids, rankings[item.identifier], 5)
        for item in answerable
    )
    recall_at_10 = _mean(
        _recall_at(item.expected_document_ids, rankings[item.identifier], 10)
        for item in answerable
    )
    reciprocal_rank = _mean(
        _reciprocal_rank(item.expected_document_ids, rankings[item.identifier])
        for item in answerable
    )
    ndcg_at_10 = _mean(
        _ndcg_at(item.expected_document_ids, rankings[item.identifier], NDCG_CUTOFF)
        for item in answerable
    )
    no_match_accuracy = (
        _mean(1.0 if not rankings[item.identifier] else 0.0 for item in no_match)
        if no_match
        else 1.0
    )
    return StrategyMetrics(
        query_count=len(items),
        answerable_query_count=len(answerable),
        no_match_query_count=len(no_match),
        recall_at_5=recall_at_5,
        recall_at_10=recall_at_10,
        mean_reciprocal_rank=reciprocal_rank,
        ndcg_at_10=ndcg_at_10,
        no_match_accuracy=no_match_accuracy,
    )


def _recall_at(
    expected_document_ids: Sequence[str], ranking: Sequence[str], cutoff: int
) -> float:
    expected = set(expected_document_ids)
    return len(expected.intersection(ranking[:cutoff])) / len(expected)


def _reciprocal_rank(
    expected_document_ids: Sequence[str], ranking: Sequence[str]
) -> float:
    expected = set(expected_document_ids)
    for rank, document_id in enumerate(ranking, start=1):
        if document_id in expected:
            return 1 / rank
    return 0.0


def _ndcg_at(
    expected_document_ids: Sequence[str], ranking: Sequence[str], cutoff: int
) -> float:
    expected = set(expected_document_ids)
    dcg = sum(
        1 / math.log2(rank + 1)
        for rank, document_id in enumerate(ranking[:cutoff], start=1)
        if document_id in expected
    )
    ideal_count = min(len(expected), cutoff)
    ideal_dcg = sum(1 / math.log2(rank + 1) for rank in range(1, ideal_count + 1))
    return dcg / ideal_dcg


def _reranking_verdict(
    metrics_by_strategy: Mapping[RetrievalStrategy, StrategyMetrics],
) -> RerankingVerdict:
    hybrid = metrics_by_strategy[RetrievalStrategy.HYBRID_RRF]
    reranked = metrics_by_strategy[RetrievalStrategy.HYBRID_RERANK]
    compared_metrics = (
        (hybrid.recall_at_5, reranked.recall_at_5),
        (hybrid.recall_at_10, reranked.recall_at_10),
        (hybrid.mean_reciprocal_rank, reranked.mean_reciprocal_rank),
        (hybrid.ndcg_at_10, reranked.ndcg_at_10),
        (hybrid.no_match_accuracy, reranked.no_match_accuracy),
    )
    no_regression = all(
        reranked_value >= hybrid_value
        for hybrid_value, reranked_value in compared_metrics
    )
    measured_lift = any(
        reranked_value > hybrid_value
        for hybrid_value, reranked_value in compared_metrics
    )
    return (
        RerankingVerdict.RETAIN
        if no_regression and measured_lift
        else RerankingVerdict.REMOVE
    )


def _strategy_label(strategy: RetrievalStrategy) -> str:
    return {
        RetrievalStrategy.DENSE_ONLY: "Dense only",
        RetrievalStrategy.LEXICAL_ONLY: "Lexical only",
        RetrievalStrategy.HYBRID_RRF: "Hybrid RRF",
        RetrievalStrategy.HYBRID_RERANK: "Hybrid + rerank",
    }[strategy]


def _reranking_message(verdict: RerankingVerdict) -> str:
    if verdict is RerankingVerdict.RETAIN:
        return (
            "**Retain `hybrid + rerank`:** it improves at least one primary metric "
            "without regressing any measured retrieval or no-match metric."
        )
    return (
        "**Remove `hybrid + rerank`:** it did not produce a non-regressing measured "
        "lift over hybrid RRF. Delete the reranker before accepting this result."
    )


def _mean(values: Iterable[float]) -> float:
    values_tuple = tuple(values)
    if not values_tuple:
        raise RetrievalEvaluationError("cannot average an empty metric population")
    return sum(values_tuple) / len(values_tuple)


def _validate_git_sha(value: str) -> str:
    if not isinstance(value, str) or GIT_SHA_PATTERN.fullmatch(value) is None:
        raise RetrievalEvaluationError("git_sha must be a short or full lowercase SHA")
    return value


def _require_non_blank(value: str, field_name: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise RetrievalEvaluationError(f"{field_name} must be a non-blank string")


if __name__ == "__main__":
    raise SystemExit(main())
