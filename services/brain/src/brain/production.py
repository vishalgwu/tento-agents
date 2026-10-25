"""Production composition of the bounded autonomous maintenance graph.

The caller owns the tenant-bound transaction and durable job lease. Restarted
jobs replay this side-effect-free graph; deterministic row identities make the
trace receipts retry-safe. This module never sends a notification or a work order.
"""

from __future__ import annotations

import hashlib
import os
import re
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any, cast
from uuid import UUID, uuid5

from anthropic import AsyncAnthropic
from openai import AsyncOpenAI
from langgraph.checkpoint.memory import MemorySaver
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from brain.agents.auditor import AuditorGateway
from brain.agents.diagnostician import DiagnosticianGateway
from brain.agents.dispatch import DispatchGateway, Trade
from brain.agents.intake import AccessWindow, IntakeGateway, IntakeRequest
from brain.agents.p0_protocol import P0Channel, P0PageRequest
from brain.context.budget import (
    ContextBudgetError,
    ContextBudgeter,
    ContextBudgetRequest,
    ContextFragment,
    ContextSlot,
    TokenizerUnavailableError,
)
from brain.context.envelope import (
    ContextEnvelope,
    ProvenanceInput,
    assemble_context_envelope,
)
from brain.gateway.config import openai_routes
from brain.gateway.client import (
    AnthropicProvider,
    AsyncpgLlmCallAudit,
    CallContext,
    configure_model_metrics_logging,
    GatewayClient,
    ModelProvider,
    ModelRoute,
    ModelTier,
    OpenAIProvider,
)
from brain.graph.builder import TicketStateCheckpointSerializer, build_maintenance_graph
from brain.graph.nodes import AuditEvidence, DispatchSnapshot, GraphDependencies
from brain.graph.state import DecisionMode, TicketState
from brain.guardrails.pii import redact_pii
from brain.policy.precedence import PolicyClaim, authority_rank
from brain.retrieval.ingest import Authority

_STAGE_ORDER = (
    "safety",
    "p0",
    "intake",
    "context",
    "diagnosis",
    "dispatch",
    "policy_audit",
    "decision",
)


class SqlAlchemyConnection:
    """Adapt existing asyncpg audit repositories without a second transaction."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    @staticmethod
    def bind(query: str, args: tuple[object, ...]) -> tuple[str, dict[str, object]]:
        statement = re.sub(r"\$(\d+)", lambda match: f"(:arg{match[1]})", query)
        return statement, {f"arg{index}": value for index, value in enumerate(args, 1)}

    async def execute(self, query: str, *args: object) -> str:
        statement, values = self.bind(query, args)
        await self.session.execute(text(statement), values)
        return "OK"

    async def fetchrow(self, query: str, *args: object) -> Mapping[str, object] | None:
        statement, values = self.bind(query, args)
        result = await self.session.execute(text(statement), values)
        row = result.mappings().one_or_none()
        return dict(row) if row is not None else None


class MissingProviderGateway:
    async def complete(self, *args: object, **kwargs: object) -> Any:
        raise RuntimeError("model_provider_not_configured")


class NoPagingTransport:
    async def send_p0_page(
        self, *, channel: P0Channel, message: str, idempotency_key: str
    ) -> str:
        raise RuntimeError("paging_transport_not_configured")


class PostgresWorkflowInputs:
    """Production source reads with explicit organisation and ticket boundaries."""

    def __init__(
        self,
        session: AsyncSession,
        *,
        org_id: UUID,
        person_id: UUID,
        ticket_id: UUID,
        run_id: UUID,
    ) -> None:
        self.session = session
        self.org_id = org_id
        self.person_id = person_id
        self.ticket_id = ticket_id
        self.run_id = run_id
        self.ticket: dict[str, Any] | None = None
        self.policy_claims: tuple[PolicyClaim, ...] = ()
        self.source_rows: dict[str, dict[str, Any]] = {}
        self.policy_context = "No eligible policy evidence is available."

    def identity(self) -> dict[str, object]:
        return {
            "org_id": str(self.org_id),
            "person_id": str(self.person_id),
            "ticket_id": str(self.ticket_id),
        }

    async def load_ticket(self) -> dict[str, Any]:
        if self.ticket is None:
            result = await self.session.execute(
                text("""
                SELECT ticket.*, property.region_code, property.country_code,
                       property.in_house_trades
                FROM public.tickets AS ticket
                JOIN public.properties AS property
                  ON property.org_id = ticket.org_id AND property.id = ticket.property_id
                WHERE ticket.org_id = CAST(:org_id AS uuid)
                  AND ticket.id = CAST(:ticket_id AS uuid)
                  AND ticket.reporter_person_id = CAST(:person_id AS uuid)
                FOR UPDATE OF ticket
            """),
                self.identity(),
            )
            row = result.mappings().one_or_none()
            if row is None:
                raise ValueError("ticket_not_accessible")
            self.ticket = dict(row)
        return self.ticket

    async def load_intake_request(self, state: TicketState) -> IntakeRequest:
        ticket = await self.load_ticket()
        report = redact_pii(str(ticket["reported_text"])).redacted_text
        return IntakeRequest(
            resident_report=report,
            access_permission=ticket["access_permission"],
            pets_present=ticket["pets_present"],
            preferred_access_window=AccessWindow(
                start=ticket["preferred_access_start"],
                end=ticket["preferred_access_end"],
            )
            if ticket.get("preferred_access_start")
            and ticket.get("preferred_access_end")
            else None,
        )

    async def load_context_envelope(self, state: TicketState) -> ContextEnvelope:
        ticket = await self.load_ticket()
        if state.facts is None:
            raise ValueError("context_requires_intake")
        query = state.facts.symptom_summary or "maintenance"
        query_terms = (
            " OR ".join(re.findall(r"[A-Za-z]{3,}", query)[:30]) or "maintenance"
        )
        result = await self.session.execute(
            text("""
            WITH terms AS (SELECT websearch_to_tsquery('english', :query) AS value)
            SELECT chunk.id AS chunk_id, chunk.kb_document_id, chunk.source_start,
                   chunk.source_end, chunk.heading_path, chunk.content,
                   document.document_key, document.version, document.effective_from,
                   document.effective_to, document.authority,
                   claim.id AS claim_id, claim.policy_key, claim.outcome,
                   claim.source_start AS claim_start, claim.source_end AS claim_end
            FROM public.kb_chunks AS chunk
            JOIN public.kb_documents AS document
              ON document.org_id = chunk.org_id AND document.id = chunk.kb_document_id
            JOIN public.kb_policy_claims AS claim
              ON claim.org_id = chunk.org_id AND claim.kb_document_id = document.id
             AND claim.source_start >= chunk.source_start AND claim.source_end <= chunk.source_end
            CROSS JOIN terms
            WHERE chunk.org_id = CAST(:org_id AS uuid)
              AND document.status = 'active'
              AND document.authority::text IN ('statute', 'lease', 'internal_sop')
              AND document.effective_from <= :submitted_at
              AND (document.effective_to IS NULL OR document.effective_to > :submitted_at)
              AND document.jurisdiction_code IN (:jurisdiction, :country)
              AND chunk.content_tsv @@ terms.value
            ORDER BY ts_rank_cd(chunk.content_tsv, terms.value) DESC, document.document_key, claim.id
            LIMIT 30
        """),
            {
                "org_id": str(self.org_id),
                "query": query_terms,
                "submitted_at": ticket["submitted_at"],
                "jurisdiction": f"{ticket['country_code']}-{ticket['region_code']}",
                "country": ticket["country_code"],
            },
        )
        rows = [dict(row) for row in result.mappings().all()]
        lexical_ranks: dict[object, int] = {}
        for row in rows:
            lexical_ranks.setdefault(row["chunk_id"], len(lexical_ranks) + 1)
            row["lexical_rank"] = lexical_ranks[row["chunk_id"]]
        # Preserve lexical order within each authority; admit statute before SOP.
        rows.sort(key=lambda row: authority_rank(Authority(str(row["authority"]))))
        sources: list[ProvenanceInput] = []
        accepted: list[dict[str, Any]] = []
        seen_claims: set[object] = set()
        for row in rows:
            if row["claim_id"] in seen_claims:
                continue
            seen_claims.add(row["claim_id"])
            start = int(row["claim_start"]) - int(row["source_start"])
            end = int(row["claim_end"]) - int(row["source_start"])
            passage = str(row["content"])[start:end]
            if (
                start < 0
                or end <= start
                or end > len(str(row["content"]))
                or not passage.strip()
            ):
                continue
            sources.append(
                ProvenanceInput(
                    source=str(row["document_key"]),
                    version=str(row["version"]),
                    effective_from=row["effective_from"].date(),
                    effective_to=row["effective_to"].date()
                    if row["effective_to"]
                    else None,
                    section=f"{row['heading_path']} chars {row['claim_start']}:{row['claim_end']}",
                    text=passage,
                )
            )
            accepted.append(row)
        envelope = assemble_context_envelope(
            citations=sources,
            unknowns=(
                "Availability and scheduling are unconfirmed until an execution receipt exists.",
            ),
        )
        try:
            budget = ContextBudgeter().build(
                ContextBudgetRequest(
                    system_schema=envelope.grounding_instructions,
                    current_ticket=query,
                    policy=tuple(
                        ContextFragment(record.render())
                        for record in envelope.citations
                    ),
                )
            )
        except (ContextBudgetError, TokenizerUnavailableError):
            self.policy_claims = ()
            return assemble_context_envelope(
                unknowns=(
                    "The source context could not be validated within its token budget.",
                )
            )
        selected = set(budget.slots[ContextSlot.POLICY].included_blocks)
        citations = tuple(
            record for record in envelope.citations if record.render() in selected
        )
        claims: list[PolicyClaim] = []
        kept = {record.provenance_id for record in citations}
        for index, row in enumerate(accepted, 1):
            identifier = f"[C{index}]"
            if identifier in kept:
                self.source_rows[identifier] = row
                claims.append(
                    PolicyClaim(
                        claim_id=str(row["claim_id"]),
                        policy_key=str(row["policy_key"]),
                        outcome=str(row["outcome"]),
                        authority=Authority(str(row["authority"])),
                        provenance_ids=(identifier,),
                    )
                )
        self.policy_claims = tuple(claims)
        envelope = ContextEnvelope(
            citations=citations,
            facts=(),
            unknowns=envelope.unknowns
            if citations
            else (
                "No active, applicable source-backed policy evidence matches this report.",
            ),
        )
        self.policy_context = envelope.render()
        await self.persist_retrieval(query, accepted, kept, ticket["submitted_at"])
        return envelope

    async def persist_retrieval(
        self,
        query: str,
        rows: list[dict[str, Any]],
        kept: set[str],
        submitted_at: datetime,
    ) -> None:
        retrieval_id = uuid5(self.run_id, "production-retrieval")
        await self.session.execute(
            text("""INSERT INTO public.retrievals(id,org_id,agent_run_id,agent_step_id,query_digest,ticket_timestamp,retrieval_strategy)
            VALUES(CAST(:id AS uuid),CAST(:org_id AS uuid),CAST(:run_id AS uuid),CAST(:step_id AS uuid),:digest,:submitted_at,'lexical_policy')
            ON CONFLICT(id) DO NOTHING"""),
            {
                "id": str(retrieval_id),
                "org_id": str(self.org_id),
                "run_id": str(self.run_id),
                "step_id": str(uuid5(self.run_id, "context")),
                "digest": _digest(query),
                "submitted_at": submitted_at,
            },
        )
        seen: set[object] = set()
        used_chunks = {
            row["chunk_id"]
            for index, row in enumerate(rows, 1)
            if f"[C{index}]" in kept
        }
        for index, row in enumerate(rows, 1):
            if row["chunk_id"] in seen:
                continue
            seen.add(row["chunk_id"])
            await self.session.execute(
                text("""INSERT INTO public.retrieval_results(org_id,retrieval_id,kb_chunk_id,bm25_rank,final_rank,used_in_context)
                VALUES(CAST(:org_id AS uuid),CAST(:retrieval_id AS uuid),CAST(:chunk_id AS uuid),:lexical_rank,:rank,:used)
                ON CONFLICT(org_id,retrieval_id,kb_chunk_id) DO NOTHING"""),
                {
                    "org_id": str(self.org_id),
                    "retrieval_id": str(retrieval_id),
                    "chunk_id": str(row["chunk_id"]),
                    "rank": index,
                    "lexical_rank": row["lexical_rank"],
                    "used": row["chunk_id"] in used_chunks,
                },
            )

    async def load_dispatch_snapshot(self, state: TicketState) -> DispatchSnapshot:
        ticket = await self.load_ticket()
        # Missing real availability remains unavailable. No synthetic service windows.
        return DispatchSnapshot(
            property_region_code=f"{ticket['country_code']}-{ticket['region_code']}",
            evaluated_at=datetime.now(UTC),
            in_house_trades=tuple(Trade(value) for value in ticket["in_house_trades"]),
        )

    async def load_audit_evidence(self, state: TicketState) -> AuditEvidence:
        if not self.policy_claims:
            raise ValueError("source_backed_policy_required")
        return AuditEvidence(
            policy_context=self.policy_context, policy_claims=self.policy_claims
        )

    async def load_p0_page_request(self, state: TicketState) -> P0PageRequest:
        ticket = await self.load_ticket()
        return P0PageRequest(
            org_id=self.org_id,
            ticket_id=self.ticket_id,
            ticket_number=str(ticket["ticket_number"]),
        )


async def initialize_steps(session: AsyncSession, org_id: UUID, run_id: UUID) -> None:
    for index, stage in enumerate(_STAGE_ORDER, 1):
        await session.execute(
            text("""INSERT INTO public.agent_steps(id,org_id,agent_run_id,sequence_number,component_name,status,input_digest,started_at)
            VALUES(CAST(:id AS uuid),CAST(:org_id AS uuid),CAST(:run_id AS uuid),:sequence,:stage,'running',:digest,now())
            ON CONFLICT(id) DO NOTHING"""),
            {
                "id": str(uuid5(run_id, stage)),
                "org_id": str(org_id),
                "run_id": str(run_id),
                "sequence": index,
                "stage": stage,
                "digest": _digest(f"{run_id}:{stage}"),
            },
        )


async def persist_graph_result(
    session: AsyncSession,
    state: TicketState,
    evidence: Mapping[str, dict[str, Any]] | None = None,
) -> None:
    by_stage = {entry.stage.value: entry for entry in state.trace}
    for stage in _STAGE_ORDER:
        entry = by_stage.get(stage)
        status = (
            "skipped"
            if entry is None
            else "failed"
            if entry.outcome.value == "failed"
            else "completed"
        )
        await session.execute(
            text("""UPDATE public.agent_steps SET status=CAST(:status AS agent_step_status),input_digest=COALESCE(:input_digest,input_digest),output_digest=:digest,error_code=:error,completed_at=now()
            WHERE org_id=CAST(:org_id AS uuid) AND id=CAST(:id AS uuid)"""),
            {
                "status": status,
                "input_digest": entry.input_digest if entry else None,
                "digest": entry.output_digest if entry else None,
                "error": entry.failure_code if entry else None,
                "org_id": str(state.org_id),
                "id": str(uuid5(state.run_id, stage)),
            },
        )
    for index, event in enumerate(state.guardrail_events):
        await session.execute(
            text("""INSERT INTO public.guardrail_events(id,org_id,agent_run_id,ticket_id,kind,stage,outcome,rule_version,content_digest,reason_code)
            VALUES(CAST(:id AS uuid),CAST(:org_id AS uuid),CAST(:run_id AS uuid),CAST(:ticket_id AS uuid),CAST(:kind AS guardrail_kind),CAST(:stage AS guardrail_stage),CAST(:outcome AS guardrail_outcome),:version,:digest,:reason)
            ON CONFLICT(id) DO NOTHING"""),
            {
                "id": str(uuid5(state.run_id, f"guardrail:{index}")),
                "org_id": str(state.org_id),
                "run_id": str(state.run_id),
                "ticket_id": str(state.ticket_id),
                "kind": event.kind.value,
                "stage": event.stage.value,
                "outcome": event.outcome.value,
                "version": event.rule_version,
                "digest": event.content_digest,
                "reason": event.reason_code,
            },
        )
    if state.decision is not None:
        proposal = state.plan.plan.proposal if state.plan and state.plan.plan else None
        await session.execute(
            text("""INSERT INTO public.decisions(id,org_id,ticket_id,agent_run_id,sequence_number,mode,status,proposed_trade,rationale,unknowns,citation_verified)
            VALUES(CAST(:id AS uuid),CAST(:org_id AS uuid),CAST(:ticket_id AS uuid),CAST(:run_id AS uuid),(SELECT COALESCE(MAX(sequence_number),0)+1 FROM public.decisions WHERE org_id=CAST(:org_id AS uuid) AND ticket_id=CAST(:ticket_id AS uuid)),CAST(:mode AS decision_mode),CAST(:status AS decision_status),CAST(:trade AS trade),:rationale,:unknowns,:verified)
            ON CONFLICT(id) DO NOTHING"""),
            {
                "id": str(uuid5(state.run_id, "decision")),
                "org_id": str(state.org_id),
                "ticket_id": str(state.ticket_id),
                "run_id": str(state.run_id),
                "mode": state.decision.mode.value,
                "status": "proposed"
                if state.decision.mode is DecisionMode.AUTO
                else "abstained",
                "trade": proposal.trade.value if proposal else None,
                "rationale": state.decision.rationale,
                "unknowns": "\n".join(state.decision.unknowns),
                "verified": state.decision.mode is DecisionMode.AUTO,
            },
        )

        decision_id = uuid5(state.run_id, "decision")
        claim_id = uuid5(state.run_id, "decision-claim")
        await session.execute(
            text("""INSERT INTO public.decision_claims(id,org_id,decision_id,claim_index,claim_text,is_material,is_unknown)
            VALUES(CAST(:id AS uuid),CAST(:org_id AS uuid),CAST(:decision_id AS uuid),1,:claim,:material,:unknown)
            ON CONFLICT(id) DO NOTHING"""),
            {
                "id": str(claim_id),
                "org_id": str(state.org_id),
                "decision_id": str(decision_id),
                "claim": proposal.scope_summary
                if proposal
                else state.decision.rationale,
                "material": proposal is not None,
                "unknown": state.decision.mode is not DecisionMode.AUTO,
            },
        )
        for provenance_id in state.decision.provenance_ids:
            row = (evidence or {}).get(provenance_id)
            if row is None:
                continue
            await session.execute(
                text("""INSERT INTO public.decision_evidence(id,org_id,decision_claim_id,kb_chunk_id,source_start,source_end)
                VALUES(CAST(:id AS uuid),CAST(:org_id AS uuid),CAST(:claim_id AS uuid),CAST(:chunk_id AS uuid),:start,:end)
                ON CONFLICT(id) DO NOTHING"""),
                {
                    "id": str(uuid5(claim_id, provenance_id)),
                    "org_id": str(state.org_id),
                    "claim_id": str(claim_id),
                    "chunk_id": str(row["chunk_id"]),
                    "start": row["claim_start"],
                    "end": row["claim_end"],
                },
            )


async def execute_maintenance(
    *,
    session: AsyncSession,
    org_id: UUID,
    person_id: UUID,
    ticket_id: UUID,
    run_id: UUID,
) -> dict[str, Any]:
    """Run the actual multi-agent graph under the worker's RLS transaction."""
    configure_model_metrics_logging()
    await initialize_steps(session, org_id, run_id)
    inputs = PostgresWorkflowInputs(
        session, org_id=org_id, person_id=person_id, ticket_id=ticket_id, run_id=run_id
    )

    # Select the configured LLM provider.
    openai_key = os.environ.get("OPENAI_API_KEY", "").strip()
    openai_model = os.environ.get("OPENAI_MODEL", "").strip()

    anthropic_key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    anthropic_model = os.environ.get("ANTHROPIC_MODEL", "").strip()

    if openai_key and openai_model:
        # Prefer OpenAI when configured.
        async with AsyncOpenAI(
            api_key=openai_key,
            max_retries=0,
        ) as client:
            provider_name = "openai"
            provider = cast(
                ModelProvider,
                OpenAIProvider(client, streaming=True),
            )
            routes = openai_routes(os.environ)

            gateways = {}

            for stage in (
                "intake",
                "diagnosis",
                "dispatch",
                "policy_audit",
            ):
                gateways[stage] = GatewayClient(
                    context=CallContext(
                        org_id=org_id,
                        agent_run_id=run_id,
                        agent_step_id=uuid5(run_id, stage),
                    ),
                    providers={provider_name: provider},
                    tier_routes=routes,
                    audit=AsyncpgLlmCallAudit(SqlAlchemyConnection(session)),
                    timeout_seconds=15,
                )

            state = await _run_graph(inputs, gateways)

    elif anthropic_key and anthropic_model:
        # Preserve Anthropic as an optional alternative.
        async with AsyncAnthropic(
            api_key=anthropic_key,
            max_retries=0,
        ) as anthropic_client:
            provider_name = "anthropic"
            provider = cast(
                ModelProvider,
                AnthropicProvider(anthropic_client),
            )
            route = ModelRoute(
                provider=provider_name,
                model_name=anthropic_model,
                model_version=anthropic_model,
            )

            gateways = {}

            for stage in (
                "intake",
                "diagnosis",
                "dispatch",
                "policy_audit",
            ):
                gateways[stage] = GatewayClient(
                    context=CallContext(
                        org_id=org_id,
                        agent_run_id=run_id,
                        agent_step_id=uuid5(run_id, stage),
                    ),
                    providers={provider_name: provider},
                    tier_routes={tier: route for tier in ModelTier},
                    audit=AsyncpgLlmCallAudit(SqlAlchemyConnection(session)),
                    timeout_seconds=15,
                )

            state = await _run_graph(inputs, gateways)

    else:
        # Fail safely when neither provider is configured.
        state = await _run_graph(
            inputs,
            {
                stage: MissingProviderGateway()
                for stage in (
                    "intake",
                    "diagnosis",
                    "dispatch",
                    "policy_audit",
                )
            },
        )

    await persist_graph_result(session, state, inputs.source_rows)
    emergency = state.safety is not None and state.safety.p0
    completed = state.decision is not None and state.decision.mode is DecisionMode.AUTO
    return {
        "status": "emergency"
        if emergency
        else "completed"
        if completed
        else "abstained",
        "summary": "This report may describe an emergency. Move to safety and contact local emergency services or your property's emergency maintenance number. This service has not contacted anyone."
        if emergency
        else state.decision.rationale
        if state.decision
        else "The report was saved, but there is insufficient evidence or provider availability for a validated maintenance plan.",
        "facts": state.facts.model_dump(mode="json") if state.facts else None,
        "decision": state.decision.model_dump(mode="json") if state.decision else None,
        "plan": state.plan.plan.model_dump(mode="json")
        if state.plan and state.plan.plan
        else None,
        "diagnosis": state.diagnosis.assessment.model_dump(mode="json")
        if state.diagnosis and state.diagnosis.assessment
        else None,
        "trace": [entry.model_dump(mode="json") for entry in state.trace],
    }


async def _run_graph(
    inputs: PostgresWorkflowInputs, gateways: Mapping[str, Any]
) -> TicketState:
    dependencies = GraphDependencies(
        inputs=inputs,
        intake_gateway=cast(IntakeGateway, gateways["intake"]),
        diagnostician_gateway=cast(DiagnosticianGateway, gateways["diagnosis"]),
        dispatch_gateway=cast(DispatchGateway, gateways["dispatch"]),
        auditor_gateway=cast(AuditorGateway, gateways["policy_audit"]),
        p0_transport=NoPagingTransport(),
        demo_mode=True,
    )
    graph = build_maintenance_graph(
        dependencies, checkpointer=MemorySaver(serde=TicketStateCheckpointSerializer())
    )
    return await graph.ainvoke(
        TicketState(
            org_id=inputs.org_id, ticket_id=inputs.ticket_id, run_id=inputs.run_id
        ),
        {"configurable": {"thread_id": f"{inputs.org_id}:{inputs.run_id}"}},
    )


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()
