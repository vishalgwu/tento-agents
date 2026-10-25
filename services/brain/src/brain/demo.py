"""Fictional policy sandbox: real agents, no production index or write tools."""

from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
import time
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any, cast
from uuid import NAMESPACE_URL, UUID, uuid4, uuid5

from langgraph.checkpoint.memory import MemorySaver
from openai import AsyncOpenAI

from brain.agents.auditor import AuditorGateway
from brain.agents.diagnostician import DiagnosticianGateway
from brain.agents.dispatch import DispatchGateway, Trade
from brain.agents.intake import IntakeGateway, IntakeRequest
from brain.agents.p0_protocol import P0Channel, P0PageRequest
from brain.context.budget import (
    ContextBudgeter,
    ContextBudgetRequest,
    ContextFragment,
    ContextSlot,
)
from brain.context.envelope import (
    ContextEnvelope,
    ProvenanceInput,
    assemble_context_envelope,
)
from brain.gateway.client import (
    CallContext,
    GatewayClient,
    LlmCallRecord,
    ModelProvider,
    OpenAIProvider,
    PromptTemplate,
    PromptVersion,
)
from brain.gateway.config import openai_routes
from brain.graph.builder import TicketStateCheckpointSerializer, build_maintenance_graph
from brain.graph.nodes import AuditEvidence, DispatchSnapshot, GraphDependencies
from brain.graph.state import DecisionMode, TicketState
from brain.guardrails.pii import redact_pii
from brain.policy.precedence import PolicyClaim
from brain.retrieval.ingest import Authority, parse_knowledge_document

DATA_ROOT = Path(__file__).parent / "demo_data"
DEMO_ORG_ID = uuid5(NAMESPACE_URL, "tento:fictional:maple-court")
_STOP = frozenset(
    "the a an is are was were my our it this that can should what when where how does and for with from not you your have will".split()
)


def load_bundle() -> dict[str, Any]:
    manifest = json.loads((DATA_ROOT / "manifest.json").read_text(encoding="utf-8"))
    if not manifest.get("fictional") or not manifest.get("synthetic"):
        raise ValueError("demo bundle must remain synthetic and fictional")
    sources: dict[str, str] = {}
    for entry in manifest["documents"]:
        path = (DATA_ROOT / entry["filename"]).resolve()
        if not path.is_relative_to(DATA_ROOT.resolve()) or path.suffix != ".md":
            raise ValueError("invalid demo source path")
        raw = path.read_bytes()
        if hashlib.sha256(raw).hexdigest() != entry["sha256"]:
            raise ValueError("demo source checksum mismatch")
        source = raw.decode("utf-8")
        document = parse_knowledge_document(markdown=source, source_path=path)
        if (
            document.production_eligible
            or document.source_status != "temporary_fixture"
        ):
            raise ValueError("demo source must retain fixture status")
        if entry["doc_id"] != document.document_key or document.document_key in sources:
            raise ValueError("duplicate or mismatched demo identity")
        sources[document.document_key] = source
    claims = json.loads((DATA_ROOT / "claims.json").read_text(encoding="utf-8"))
    for claim in claims:
        source = sources[claim["doc_id"]]
        if not 0 <= claim["source_start"] < claim["source_end"] <= len(source):
            raise ValueError("invalid demo source span")
        if claim["outcome"] != claim["source_text"]:
            raise ValueError("demo outcome must preserve its exact source wording")
        if source[claim["source_start"] : claim["source_end"]] != claim["source_text"]:
            raise ValueError("demo claim must match an exact source span")
    return {"manifest": manifest, "sources": sources, "claims": claims}


def retrieve_demo(query: str, *, limit: int = 5) -> list[str]:
    """Execute local FTS5/BM25; expected result IDs never enter the ranker."""
    bundle = load_bundle()
    terms = sorted(
        {
            word.lower()
            for word in re.findall(r"[A-Za-z]{3,}", query)
            if word.lower() not in _STOP
        }
    )[:30]
    if not terms:
        return []
    connection = sqlite3.connect(":memory:")
    try:
        connection.execute(
            "CREATE VIRTUAL TABLE docs USING fts5(id UNINDEXED, content, tokenize='porter unicode61')"
        )
        for identifier, source in bundle["sources"].items():
            connection.execute(
                "INSERT INTO docs VALUES (?,?)",
                (identifier, source.split("---", 2)[-1]),
            )
        rows = connection.execute(
            "SELECT id FROM docs WHERE docs MATCH ? ORDER BY bm25(docs), id LIMIT ?",
            (" OR ".join(f'"{term}"' for term in terms), min(max(limit, 1), 5)),
        ).fetchall()
        return [str(row[0]) for row in rows]
    finally:
        connection.close()


class DemoAudit:
    def __init__(self) -> None:
        self.records: list[LlmCallRecord] = []

    async def ensure_prompt_version(
        self, *, context: CallContext, prompt: PromptTemplate
    ) -> PromptVersion:
        return PromptVersion(
            uuid5(NAMESPACE_URL, prompt.content_sha256),
            prompt.name,
            prompt.version,
            prompt.content_sha256,
            prompt.template_uri,
        )

    async def write_llm_call(self, record: LlmCallRecord) -> None:
        self.records.append(record)


class NoDemoTransport:
    async def send_p0_page(
        self, *, channel: P0Channel, message: str, idempotency_key: str
    ) -> str:
        raise RuntimeError("demo_has_no_external_transport")


class DemoInputs:
    def __init__(self, description: str) -> None:
        self.description = redact_pii(description).redacted_text
        cases = json.loads((DATA_ROOT / "cases.json").read_text(encoding="utf-8"))
        self.scenario: dict[str, Any] = next(
            (case for case in cases if case["query"] == description), {}
        )
        self.assumptions = (
            [
                "Fictional scenario: a site-authorized, trained general-maintenance worker may inspect and adjust ordinary nonsecurity cabinet and door hardware. No appointment or completed repair is asserted."
            ]
            if self.scenario.get("demo_staff_authorized")
            else []
        )
        self.envelope = assemble_context_envelope()
        self.claims: tuple[PolicyClaim, ...] = ()

    async def load_intake_request(self, state: TicketState) -> IntakeRequest:
        return IntakeRequest(
            resident_report=self.description,
            access_permission=self.scenario.get("access_permission"),
        )

    async def load_context_envelope(self, state: TicketState) -> ContextEnvelope:
        bundle = load_bundle()
        query = (
            state.facts.symptom_summary
            if state.facts and state.facts.symptom_summary
            else self.description
        )
        selected = [
            claim
            for identifier in retrieve_demo(query, limit=3)
            for claim in bundle["claims"]
            if claim["doc_id"] == identifier
        ]
        demo_facts = tuple(
            ProvenanceInput(
                source="DEMO-OPERATIONS",
                version="demo-1.0",
                effective_from=date(2026, 1, 1),
                effective_to=None,
                section="fictional staffing assumption",
                text=value,
            )
            for value in self.assumptions
        )
        envelope = assemble_context_envelope(
            facts=demo_facts,
            citations=tuple(
                ProvenanceInput(
                    source=claim["doc_id"],
                    version="demo-1.0",
                    effective_from=date(2026, 1, 1),
                    effective_to=None,
                    section=f"chars {claim['source_start']}:{claim['source_end']}",
                    text=claim["source_text"],
                )
                for claim in selected
            ),
            unknowns=(
                "Fictional demonstration only. No real dispatch, vendor credentials, legal deadline or completed repair is established.",
            ),
        )
        budget = ContextBudgeter().build(
            ContextBudgetRequest(
                system_schema=envelope.grounding_instructions,
                current_ticket=self.description,
                policy=tuple(
                    ContextFragment(item.render()) for item in envelope.citations
                ),
            )
        )
        kept = set(budget.slots[ContextSlot.POLICY].included_blocks)
        citations = tuple(item for item in envelope.citations if item.render() in kept)
        claim_by_id = {f"[C{index}]": claim for index, claim in enumerate(selected, 1)}
        self.claims = tuple(
            PolicyClaim(
                claim_id=f"demo-{index}",
                policy_key=claim_by_id[item.provenance_id]["policy_key"],
                outcome=claim_by_id[item.provenance_id]["outcome"],
                authority=Authority.INTERNAL_SOP,
                provenance_ids=(item.provenance_id,),
            )
            for index, item in enumerate(citations, 1)
        )
        self.envelope = ContextEnvelope(
            citations=citations, facts=envelope.facts, unknowns=envelope.unknowns
        )
        return self.envelope

    async def load_dispatch_snapshot(self, state: TicketState) -> DispatchSnapshot:
        return DispatchSnapshot(
            property_region_code="US-VA",
            evaluated_at=datetime.now(UTC),
            in_house_trades=(Trade.GENERAL_MAINTENANCE,),
        )

    async def load_audit_evidence(self, state: TicketState) -> AuditEvidence:
        return AuditEvidence(
            policy_context=self.envelope.render(), policy_claims=self.claims
        )

    async def load_p0_page_request(self, state: TicketState) -> P0PageRequest:
        return P0PageRequest(
            org_id=DEMO_ORG_ID,
            ticket_id=state.ticket_id,
            ticket_number="DEMO-NOT-A-TICKET",
        )


def demo_summary(status: str, audit: dict[str, Any] | None = None) -> str:
    if status == "emergency":
        return "Potential emergency: move to safety and contact local emergency services or emergency maintenance. This demonstration has contacted nobody."
    if status == "completed":
        return "Demo plan validated against fictional policies. No ticket, work order, dispatch or notification was created."
    assessment = (audit or {}).get("assessment") or {}
    unknowns = assessment.get("unknowns") or []
    reason = unknowns[0] if unknowns else None
    if not reason:
        finding = next(
            (
                item
                for item in assessment.get("findings", [])
                if item.get("verdict") in {"unknown", "conflict"}
            ),
            None,
        )
        reason = finding.get("rationale") if finding else None
    if not reason and (audit or {}).get("failure_kind") == "unsupported_citation":
        reason = "The policy auditor's citations could not be validated against its allowed evidence."
    return (
        "Demo assessment withheld. "
        + (
            str(reason) + " "
            if reason
            else "The evidence did not support a validated autonomous plan. "
        )
        + "No work order or dispatch was created."
    )


async def execute_demo(description: str, *, actor_org_id: UUID) -> dict[str, Any]:
    """Use the real graph and model gateway without production SQL or writes."""
    key = os.environ.get("OPENAI_API_KEY", "").strip()
    if not key:
        raise ValueError("demo_model_not_configured")
    run_id = uuid4()
    inputs = DemoInputs(description)
    audit = DemoAudit()
    started = time.monotonic()
    async with AsyncOpenAI(api_key=key, max_retries=0) as client:
        provider = cast(ModelProvider, OpenAIProvider(client, streaming=True))
        gateways = {
            stage: GatewayClient(
                context=CallContext(actor_org_id, run_id, uuid5(run_id, stage)),
                providers={"openai": provider},
                tier_routes=openai_routes(os.environ),
                audit=audit,
                timeout_seconds=15,
            )
            for stage in ("intake", "diagnosis", "dispatch", "policy_audit")
        }
        graph = build_maintenance_graph(
            GraphDependencies(
                inputs=inputs,
                intake_gateway=cast(IntakeGateway, gateways["intake"]),
                diagnostician_gateway=cast(DiagnosticianGateway, gateways["diagnosis"]),
                dispatch_gateway=cast(DispatchGateway, gateways["dispatch"]),
                auditor_gateway=cast(AuditorGateway, gateways["policy_audit"]),
                p0_transport=NoDemoTransport(),
                demo_mode=True,
            ),
            checkpointer=MemorySaver(serde=TicketStateCheckpointSerializer()),
        )
        state = await graph.ainvoke(
            TicketState(org_id=DEMO_ORG_ID, ticket_id=uuid4(), run_id=run_id),
            {"configurable": {"thread_id": f"demo:{run_id}"}},
        )
    emergency = bool(state.safety and state.safety.p0)
    completed = bool(state.decision and state.decision.mode is DecisionMode.AUTO)
    return {
        "demo_assumptions": inputs.assumptions,
        "audit": state.audit_result.model_dump(mode="json")
        if state.audit_result
        else None,
        "diagnosis": state.diagnosis.model_dump(mode="json")
        if state.diagnosis
        else None,
        "run_id": str(run_id),
        "synthetic": True,
        "status": "emergency"
        if emergency
        else "completed"
        if completed
        else "abstained",
        "summary": demo_summary(
            "emergency" if emergency else "completed" if completed else "abstained",
            state.audit_result.model_dump(mode="json") if state.audit_result else None,
        ),
        "citations": [
            {
                "id": item.provenance_id,
                "source": item.source,
                "section": item.section,
                "text": item.text,
            }
            for item in inputs.envelope.citations
        ],
        "trace": [
            {"stage": item.stage.value, "outcome": item.outcome.value}
            for item in state.trace
        ],
        "facts": state.facts.model_dump(mode="json") if state.facts else None,
        "plan": state.plan.plan.model_dump(mode="json")
        if state.plan and state.plan.plan
        else None,
        "model_calls": [
            {
                "task": row.task_kind.value,
                "model": row.route.model_name,
                "outcome": row.outcome,
                "latency_ms": row.latency_ms,
                "estimated_cost_microusd": row.cost_microusd,
            }
            for row in audit.records
        ],
        "metrics": {
            "elapsed_ms": round((time.monotonic() - started) * 1000, 3),
            "estimated_cost_microusd": sum(row.cost_microusd for row in audit.records),
        },
        "work_orders_created": 0,
        "notifications_sent": 0,
    }
