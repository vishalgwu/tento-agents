"""Production composition tests: tenant scope, real graph routing and sources."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from brain.agents.intake import TicketFacts, TicketIntent
from brain.context.budget import ContextBudgeter
from brain.graph.state import TicketState
from brain.ingest import load_source_policies
from brain.production import (
    PostgresWorkflowInputs,
    SqlAlchemyConnection,
    execute_maintenance,
)


class Rows:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self.rows = rows

    def mappings(self) -> Rows:
        return self

    def all(self) -> list[dict[str, Any]]:
        return self.rows

    def one_or_none(self) -> dict[str, Any] | None:
        return self.rows[0] if self.rows else None


class Session:
    def __init__(
        self,
        *,
        report: str = "My kitchen sink drains slowly.",
        evidence: list[dict[str, Any]] | None = None,
    ) -> None:
        self.report = report
        self.evidence = evidence or []
        self.calls: list[tuple[str, dict[str, Any]]] = []

    async def execute(self, query: object, values: dict[str, Any]) -> Rows:
        sql = str(query)
        self.calls.append((sql, values))
        if "SELECT ticket.*" in sql:
            return Rows(
                [
                    {
                        "reported_text": self.report,
                        "ticket_number": 123,
                        "access_permission": None,
                        "pets_present": None,
                        "region_code": "VA",
                        "country_code": "US",
                        "in_house_trades": ["plumbing"],
                        "submitted_at": datetime(2026, 10, 1, tzinfo=UTC),
                    }
                ]
            )
        if "FROM public.kb_chunks" in sql:
            return Rows(self.evidence)
        return Rows([])


class Tokenizer:
    def count(self, value: str) -> int:
        return len(value.split())


def test_asyncpg_parameter_bridge_preserves_casts_and_never_interpolates_values() -> (
    None
):
    statement, values = SqlAlchemyConnection.bind(
        "SELECT $1::uuid, $2::text::halfvec WHERE id=$1", ("untrusted' text", "[]")
    )
    assert statement == "SELECT (:arg1)::uuid, (:arg2)::text::halfvec WHERE id=(:arg1)"
    assert "untrusted" not in statement
    assert values["arg1"] == "untrusted' text"


@pytest.mark.asyncio
async def test_emergency_runs_real_graph_without_provider_or_outbound_side_effects(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    session = Session(report="I smell gas in my apartment.")
    result = await execute_maintenance(
        session=cast(AsyncSession, session),
        org_id=uuid4(),
        person_id=uuid4(),
        ticket_id=uuid4(),
        run_id=uuid4(),
    )
    assert result["status"] == "emergency"
    assert "has not contacted anyone" in result["summary"]
    assert [row["stage"] for row in result["trace"]] == ["safety", "p0"]
    assert not any("kb_chunks" in query for query, _ in session.calls)


@pytest.mark.asyncio
async def test_missing_provider_abstains_and_persists_terminal_steps(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    session = Session()
    org = uuid4()
    person = uuid4()
    result = await execute_maintenance(
        session=cast(AsyncSession, session),
        org_id=org,
        person_id=person,
        ticket_id=uuid4(),
        run_id=uuid4(),
    )
    assert result["status"] == "abstained"
    assert result["facts"] is None
    ticket_query, scope = next(
        (query, args) for query, args in session.calls if "SELECT ticket.*" in query
    )
    assert "ticket.org_id = CAST(:org_id AS uuid)" in ticket_query
    assert "ticket.reporter_person_id = CAST(:person_id AS uuid)" in ticket_query
    assert scope["org_id"] == str(org) and scope["person_id"] == str(person)
    updates = [
        args for query, args in session.calls if "UPDATE public.agent_steps" in query
    ]
    assert len(updates) == 8
    assert any(item["status"] == "skipped" for item in updates)


@pytest.mark.asyncio
async def test_empty_corpus_has_no_citation_authority(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "brain.production.ContextBudgeter",
        lambda: ContextBudgeter(tokenizer=Tokenizer()),
    )
    session = Session()
    inputs = PostgresWorkflowInputs(
        cast(AsyncSession, session),
        org_id=uuid4(),
        person_id=uuid4(),
        ticket_id=uuid4(),
        run_id=uuid4(),
    )
    state = TicketState(
        org_id=inputs.org_id,
        ticket_id=inputs.ticket_id,
        run_id=inputs.run_id,
        facts=TicketFacts(
            intent=TicketIntent.MAINTENANCE, symptom_summary="The sink drains slowly."
        ),
    )
    envelope = await inputs.load_context_envelope(state)
    assert envelope.citations == () and envelope.facts == ()
    assert "No active" in envelope.unknowns[0]
    query = next(
        query for query, _ in session.calls if "FROM public.kb_chunks" in query
    )
    assert "document.status = 'active'" in query
    assert "document.effective_from <= :submitted_at" in query
    assert "document.jurisdiction_code IN (:jurisdiction, :country)" in query
    assert inputs.policy_claims == ()


@pytest.mark.asyncio
async def test_retrieved_policy_uses_exact_span_and_canonical_claim(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "brain.production.ContextBudgeter",
        lambda: ContextBudgeter(tokenizer=Tokenizer()),
    )
    passage = "Owner repairs plumbing defects reported by the resident."
    claim_id = uuid4()
    row = {
        "chunk_id": uuid4(),
        "kb_document_id": uuid4(),
        "source_start": 100,
        "source_end": 100 + len(passage),
        "heading_path": "Repairs",
        "content": passage,
        "document_key": "LEASE-REAL",
        "version": "v1",
        "effective_from": datetime(2026, 1, 1, tzinfo=UTC),
        "effective_to": None,
        "authority": "lease",
        "claim_id": claim_id,
        "policy_key": "repair",
        "outcome": "owner_responsible",
        "claim_start": 100,
        "claim_end": 100 + len(passage),
    }
    session = Session(evidence=[row, row])
    inputs = PostgresWorkflowInputs(
        cast(AsyncSession, session),
        org_id=uuid4(),
        person_id=uuid4(),
        ticket_id=uuid4(),
        run_id=uuid4(),
    )
    state = TicketState(
        org_id=inputs.org_id,
        ticket_id=inputs.ticket_id,
        run_id=inputs.run_id,
        facts=TicketFacts(
            intent=TicketIntent.MAINTENANCE, symptom_summary="The sink drains slowly."
        ),
    )
    envelope = await inputs.load_context_envelope(state)
    assert len(envelope.citations) == 1
    assert envelope.citations[0].text == passage
    assert inputs.policy_claims[0].claim_id == str(claim_id)
    assert inputs.policy_claims[0].provenance_ids == ("[C1]",)
    assert len(inputs.policy_claims) == 1


def test_policy_import_rejects_source_text_mismatch_and_duplicates(
    tmp_path: Path,
) -> None:
    source = "Owner repairs the sink."
    config = {
        "policy_key": "repair",
        "outcome": "owner",
        "source_start": 0,
        "source_end": len(source),
        "source_text": source,
    }
    path = tmp_path / "policy.json"
    path.write_text(json.dumps([config]), encoding="utf-8")
    assert load_source_policies(path, source)[0].outcome == "owner"
    config["source_text"] = "An invented policy."
    path.write_text(json.dumps([config]), encoding="utf-8")
    with pytest.raises(ValueError, match="exactly match"):
        load_source_policies(path, source)
    config["source_text"] = source
    path.write_text(json.dumps([config, config]), encoding="utf-8")
    with pytest.raises(ValueError, match="duplicate"):
        load_source_policies(path, source)


@pytest.mark.asyncio
async def test_actual_production_repository_drives_complete_autonomous_graph(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from pydantic import BaseModel
    from brain.production import _run_graph
    from brain.gateway.client import TaskClass, RenderedPrompt
    from brain.graph.state import DecisionMode

    class PlanningGateway:
        def __init__(self) -> None:
            self.names: list[str] = []

        async def complete(
            self, task: TaskClass, prompt: RenderedPrompt, schema: type[BaseModel]
        ) -> BaseModel:
            self.names.append(schema.__name__)
            payloads = {
                "TicketFacts": {
                    "intent": "maintenance",
                    "category": "plumbing",
                    "symptom_summary": "The kitchen sink drains slowly.",
                },
                "DiagnosticAssessment": {
                    "likely_cause": "The drain may be obstructed.",
                    "cause_provenance_ids": ["[C1]"],
                    "recommended_actions": [
                        {
                            "action": "Inspect the drain.",
                            "rationale": "The cited source supports maintenance.",
                            "provenance_ids": ["[C1]"],
                        }
                    ],
                },
                "DispatchProposal": {
                    "trade": "plumbing",
                    "fulfillment": "in_house",
                    "scope_summary": "Inspect the sink drain.",
                    "responsible_party": "owner",
                    "provenance_ids": ["[C1]"],
                },
                "PolicyAuditAssessment": {
                    "findings": [
                        {
                            "policy_key": "repair",
                            "verdict": "compliant",
                            "rationale": "The policy permits the proposed scope.",
                            "provenance_ids": ["[C1]"],
                        }
                    ]
                },
            }
            return schema.model_validate_json(json.dumps(payloads[schema.__name__]))

    monkeypatch.setattr(
        "brain.production.ContextBudgeter",
        lambda: ContextBudgeter(tokenizer=Tokenizer()),
    )
    passage = "Owner repairs plumbing defects reported by the resident."
    session = Session(
        evidence=[
            {
                "chunk_id": uuid4(),
                "kb_document_id": uuid4(),
                "source_start": 100,
                "source_end": 100 + len(passage),
                "heading_path": "Repairs",
                "content": passage,
                "document_key": "LEASE-REAL",
                "version": "v1",
                "effective_from": datetime(2026, 1, 1, tzinfo=UTC),
                "effective_to": None,
                "authority": "lease",
                "claim_id": uuid4(),
                "policy_key": "repair",
                "outcome": "owner_responsible",
                "claim_start": 100,
                "claim_end": 100 + len(passage),
            }
        ]
    )
    inputs = PostgresWorkflowInputs(
        cast(AsyncSession, session),
        org_id=uuid4(),
        person_id=uuid4(),
        ticket_id=uuid4(),
        run_id=uuid4(),
    )
    gateway = PlanningGateway()
    result = await _run_graph(
        inputs,
        {
            stage: gateway
            for stage in ("intake", "diagnosis", "dispatch", "policy_audit")
        },
    )
    assert result.decision is not None and result.decision.mode is DecisionMode.AUTO
    assert gateway.names == [
        "TicketFacts",
        "DiagnosticAssessment",
        "DispatchProposal",
        "PolicyAuditAssessment",
    ]
    assert [row.stage.value for row in result.trace] == [
        "safety",
        "intake",
        "context",
        "diagnosis",
        "dispatch",
        "policy_audit",
        "decision",
    ]


@pytest.mark.asyncio
async def test_production_import_refuses_repository_synthetic_fixtures() -> None:
    from brain.ingest import ingest_source

    source = (
        Path(__file__).resolve().parents[3] / "knowledge" / "sops" / "SOP-PLM-04.md"
    )
    with pytest.raises(ValueError, match="only active, production-eligible"):
        await ingest_source(org_id=uuid4(), source=source, claims=None)


@pytest.mark.asyncio
async def test_full_graph_abstains_before_diagnosis_when_production_sources_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from pydantic import BaseModel
    from brain.production import _run_graph
    from brain.gateway.client import TaskClass, RenderedPrompt
    from brain.graph.state import DecisionMode

    class IntakeOnlyGateway:
        calls = 0

        async def complete(
            self, task: TaskClass, prompt: RenderedPrompt, schema: type[BaseModel]
        ) -> BaseModel:
            self.calls += 1
            assert schema is TicketFacts, (
                "No later model may run without source evidence"
            )
            return TicketFacts(
                intent=TicketIntent.MAINTENANCE,
                symptom_summary="The sink drains slowly.",
            )

    monkeypatch.setattr(
        "brain.production.ContextBudgeter",
        lambda: ContextBudgeter(tokenizer=Tokenizer()),
    )
    session = Session()
    inputs = PostgresWorkflowInputs(
        cast(AsyncSession, session),
        org_id=uuid4(),
        person_id=uuid4(),
        ticket_id=uuid4(),
        run_id=uuid4(),
    )
    gateway = IntakeOnlyGateway()
    result = await _run_graph(
        inputs,
        {
            stage: gateway
            for stage in ("intake", "diagnosis", "dispatch", "policy_audit")
        },
    )
    assert gateway.calls == 1
    assert result.decision is None or result.decision.mode is not DecisionMode.AUTO
    assert result.trace[-1].outcome.value == "abstained"
