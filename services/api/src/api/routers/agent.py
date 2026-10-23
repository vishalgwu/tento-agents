"""Authenticated, bounded execution of the maintenance intake MVP."""

from __future__ import annotations

import asyncio
import logging
import os
from typing import Annotated, Literal, cast
from uuid import UUID, uuid4, uuid5, NAMESPACE_URL

from anthropic import AsyncAnthropic
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field, field_validator

from api.deps.tenancy import TenantScope, get_request_tenant_scope
from brain.agents.intake import (
    IntakeGateway,
    IntakeRequest,
    IntakeStatus,
    TicketFacts,
    normalize_intake,
)
from brain.agents.safety import assess_safety
from brain.gateway.client import (
    AnthropicProvider,
    CallContext,
    GatewayClient,
    LlmCallRecord,
    ModelProvider,
    ModelRoute,
    ModelTier,
    PromptTemplate,
    PromptVersion,
)
from brain.guardrails.shield import Shield, ShieldRequest, ShieldStage, ShieldOutcome

router = APIRouter(prefix="/v1/agent", tags=["agent"])
_LOG = logging.getLogger("resident_os.agent")
RUN_TIMEOUT_SECONDS = 45


class AgentRunRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    description: str = Field(min_length=1, max_length=20_000)

    @field_validator("description")
    @classmethod
    def nonblank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("description must not be blank")
        return value


class AgentRunResponse(BaseModel):
    run_id: UUID
    status: Literal["completed", "abstained", "emergency"]
    summary: str
    facts: TicketFacts | None = None


class LoggingCallAudit:
    """Emit digest-only call telemetry to the host's log sink; no report content."""

    async def ensure_prompt_version(
        self, *, context: CallContext, prompt: PromptTemplate
    ) -> PromptVersion:
        return PromptVersion(
            id=uuid5(
                NAMESPACE_URL, f"{prompt.name}:{prompt.version}:{prompt.content_sha256}"
            ),
            prompt_name=prompt.name,
            version=prompt.version,
            content_sha256=prompt.content_sha256,
            template_uri=prompt.template_uri,
        )

    async def write_llm_call(self, record: LlmCallRecord) -> None:
        _LOG.info(
            "model_call org=%s run=%s task=%s outcome=%s request_digest=%s response_digest=%s latency_ms=%s",
            record.context.org_id,
            record.context.agent_run_id,
            record.task_kind.value,
            record.outcome,
            record.request_digest,
            record.response_digest,
            record.latency_ms,
        )


async def execute_agent(
    description: str, scope: TenantScope, run_id: UUID, gateway: IntakeGateway
) -> AgentRunResponse:
    safety = await assess_safety(description)
    if safety.p0:
        return AgentRunResponse(
            run_id=run_id,
            status="emergency",
            summary="This report may describe an emergency. Move to safety and contact local emergency services or your property's emergency maintenance number immediately. This service has not contacted anyone.",
        )
    shield = await Shield().inspect(
        ShieldRequest(content=description, stage=ShieldStage.PRE_MODEL)
    )
    if shield.outcome is ShieldOutcome.BLOCK:
        return AgentRunResponse(
            run_id=run_id,
            status="abstained",
            summary="This request could not be processed safely. Please submit a maintenance description.",
        )
    result = await normalize_intake(
        IntakeRequest(resident_report=description), gateway=gateway
    )
    if result.status is not IntakeStatus.COMPLETED or result.facts is None:
        return AgentRunResponse(
            run_id=run_id,
            status="abstained",
            summary="The report could not be analyzed reliably. Please try again with a clear description of the issue.",
        )
    return AgentRunResponse(
        run_id=run_id,
        status="completed",
        summary=result.facts.symptom_summary
        or "Your maintenance description has been analyzed. No work order has been created.",
        facts=result.facts,
    )


@router.post("/run", response_model=AgentRunResponse)
async def run_agent(
    body: AgentRunRequest,
    scope: Annotated[TenantScope, Depends(get_request_tenant_scope)],
) -> AgentRunResponse:
    run_id = uuid4()
    safety = await assess_safety(body.description)
    if safety.p0:
        return AgentRunResponse(
            run_id=run_id,
            status="emergency",
            summary="This report may describe an emergency. Move to safety and contact local emergency services or your property's emergency maintenance number immediately. This service has not contacted anyone.",
        )
    key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    model = os.environ.get("ANTHROPIC_MODEL", "").strip()
    if not key or not model:
        raise HTTPException(503, "Agent provider is not configured")
    route = ModelRoute(provider="anthropic", model_name=model, model_version=model)
    async with AsyncAnthropic(api_key=key, max_retries=0) as client:
        gateway = GatewayClient(
            context=CallContext(
                org_id=scope.org_id, agent_run_id=run_id, agent_step_id=uuid4()
            ),
            providers={"anthropic": cast(ModelProvider, AnthropicProvider(client))},
            tier_routes={tier: route for tier in ModelTier},
            audit=LoggingCallAudit(),
            timeout_seconds=15,
        )
        try:
            async with asyncio.timeout(RUN_TIMEOUT_SECONDS):
                return await execute_agent(
                    body.description, scope, run_id, cast(IntakeGateway, gateway)
                )
        except TimeoutError as error:
            raise HTTPException(504, "Agent execution deadline exceeded") from error
