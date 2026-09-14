"""Integrity checks for the human-authored retrieval benchmark."""

from __future__ import annotations

import json
from collections import Counter
from datetime import date, datetime
from pathlib import Path
from typing import Final, NotRequired, TypedDict, cast

from brain.retrieval.ingest import parse_knowledge_document


class RetrievalCase(TypedDict):
    """The intentionally small, versioned retrieval-evaluation contract."""

    id: str
    query: str
    query_type: str
    expected_document_ids: list[str]
    should_retrieve: bool
    ticket_occurred_at: NotRequired[str]


_REPOSITORY_ROOT: Final = Path(__file__).resolve().parents[3]
_DATASET_PATH: Final = _REPOSITORY_ROOT / "evals" / "datasets" / "retrieval_v1.jsonl"
_REQUIRED_KEYS: Final = frozenset(
    {"id", "query", "query_type", "expected_document_ids", "should_retrieve"}
)
_OPTIONAL_KEYS: Final = frozenset({"ticket_occurred_at"})
_EXPECTED_TYPES: Final = Counter(
    {
        "natural_resident": 12,
        "identifier_lookup": 8,
        "synonym_paraphrase": 10,
        "jurisdiction_specific": 8,
        "effective_date_sensitive": 7,
        "no_match": 5,
    }
)


def _load_cases() -> tuple[RetrievalCase, ...]:
    """Load JSONL with explicit runtime checks before narrowing its type."""

    cases: list[RetrievalCase] = []
    for line_number, raw_line in enumerate(
        _DATASET_PATH.read_text(encoding="utf-8").splitlines(), start=1
    ):
        assert raw_line.strip(), f"line {line_number} must not be blank"
        decoded = cast(dict[str, object], json.loads(raw_line))
        assert set(decoded).issuperset(_REQUIRED_KEYS), (
            f"line {line_number} is missing a required field"
        )
        assert set(decoded).issubset(_REQUIRED_KEYS | _OPTIONAL_KEYS), (
            f"line {line_number} contains an unsupported field"
        )

        case_id = decoded["id"]
        query = decoded["query"]
        query_type = decoded["query_type"]
        expected_document_ids = decoded["expected_document_ids"]
        should_retrieve = decoded["should_retrieve"]
        assert isinstance(case_id, str) and case_id
        assert isinstance(query, str) and query.strip()
        assert isinstance(query_type, str) and query_type
        assert isinstance(expected_document_ids, list) and all(
            isinstance(document_id, str) and document_id
            for document_id in expected_document_ids
        )
        assert type(should_retrieve) is bool

        case: RetrievalCase = {
            "id": case_id,
            "query": query,
            "query_type": query_type,
            "expected_document_ids": expected_document_ids,
            "should_retrieve": should_retrieve,
        }
        ticket_occurred_at = decoded.get("ticket_occurred_at")
        if ticket_occurred_at is not None:
            assert isinstance(ticket_occurred_at, str) and ticket_occurred_at
            case["ticket_occurred_at"] = ticket_occurred_at
        cases.append(case)
    return tuple(cases)


def _source_effective_dates() -> dict[str, date]:
    """Read source IDs and effective dates through the ingestion validator."""

    knowledge_root = _REPOSITORY_ROOT / "knowledge"
    content_paths = tuple(
        path
        for path in sorted(knowledge_root.rglob("*.md"))
        if path.name != "README.md"
    )
    documents = tuple(
        parse_knowledge_document(
            markdown=path.read_text(encoding="utf-8"), source_path=path
        )
        for path in content_paths
    )
    return {
        document.document_key: document.effective_from.date() for document in documents
    }


def test_retrieval_dataset_has_stable_coverage_and_valid_source_ids() -> None:
    """Keep labels independent, complete, and anchored to real source fixtures."""

    cases = _load_cases()
    source_effective_dates = _source_effective_dates()

    assert len(cases) == 50
    assert [case["id"] for case in cases] == [
        f"retrieval-{number:03d}" for number in range(1, 51)
    ]
    assert len({case["query"] for case in cases}) == len(cases)
    assert Counter(case["query_type"] for case in cases) == _EXPECTED_TYPES
    assert sum(not case["should_retrieve"] for case in cases) == 5

    for case in cases:
        expected_ids = case["expected_document_ids"]
        assert len(expected_ids) == len(set(expected_ids)), case["id"]
        assert all(
            document_id in source_effective_dates for document_id in expected_ids
        )

        if case["query_type"] == "no_match":
            assert case["should_retrieve"] is False
            assert expected_ids == []
        else:
            assert case["should_retrieve"] is True
            assert expected_ids

        if case["query_type"] == "effective_date_sensitive":
            ticket_time = datetime.fromisoformat(
                case["ticket_occurred_at"].replace("Z", "+00:00")
            )
            assert ticket_time.tzinfo is not None
            assert all(
                source_effective_dates[document_id] <= ticket_time.date()
                for document_id in expected_ids
            )
        else:
            assert "ticket_occurred_at" not in case
