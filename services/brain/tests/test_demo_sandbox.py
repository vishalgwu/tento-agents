"""Fictional source integrity and sandbox/no-write boundaries."""

import json
from uuid import uuid4

import pytest

from brain.demo import DATA_ROOT, execute_demo, load_bundle, retrieve_demo
from brain.gateway.client import OpenAIProvider
from brain.retrieval.ingest import parse_knowledge_document


def test_sources_remain_unique_hashed_and_ineligible_for_production() -> None:
    bundle = load_bundle()
    assert len(bundle["sources"]) == 5
    assert len(bundle["claims"]) == 10
    for entry in bundle["manifest"]["documents"]:
        source = bundle["sources"][entry["doc_id"]]
        parsed = parse_knowledge_document(
            markdown=source, source_path=DATA_ROOT / entry["filename"]
        )
        assert parsed.source_status == "temporary_fixture"
        assert not parsed.production_eligible
    cases = json.loads((DATA_ROOT / "cases.json").read_text(encoding="utf-8"))
    assert len(cases) == 15
    assert all(
        set(case["expected_doc_ids"]).issubset(bundle["sources"]) for case in cases
    )


def test_actual_ranker_handles_punctuation_and_empty_queries() -> None:
    assert "MC-OPS-003" in retrieve_demo('cabinet hinge " OR *; DROP TABLE')
    assert retrieve_demo("the and our") == []
    assert len(retrieve_demo("cabinet hinge", limit=1)) == 1


@pytest.mark.asyncio
async def test_emergency_short_circuits_before_model_or_any_transport(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "test-only-key")
    monkeypatch.setenv("OPENAI_MODEL", "gpt-4.1-mini")

    async def forbidden(*args: object, **kwargs: object) -> None:
        raise AssertionError("Emergency must not invoke a model")

    monkeypatch.setattr(OpenAIProvider, "invoke", forbidden)
    result = await execute_demo("There is a suspected gas leak", actor_org_id=uuid4())
    assert result["status"] == "emergency"
    assert result["synthetic"] is True
    assert result["model_calls"] == []
    assert result["notifications_sent"] == result["work_orders_created"] == 0


def test_agent_schema_exposes_the_enforced_citation_format() -> None:
    from brain.agents.diagnostician import DiagnosticAssessment, RecommendedAction
    from brain.agents.dispatch import DispatchProposal
    from brain.agents.auditor import PolicyAuditFinding

    for schema, field in (
        (DiagnosticAssessment, "cause_provenance_ids"),
        (RecommendedAction, "provenance_ids"),
        (DispatchProposal, "provenance_ids"),
        (PolicyAuditFinding, "provenance_ids"),
    ):
        assert (
            schema.model_json_schema()["properties"][field]["items"]["pattern"]
            == r"^\[(?:C|F)[1-9]\d*\]$"
        )
