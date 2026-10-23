"""Direct execution preserves safety, tenant identity and terminal failures."""

from typing import cast
from uuid import uuid4
import httpx
import pytest
from fastapi import FastAPI
from pydantic import BaseModel
from api.deps.tenancy import TenantScope, get_request_tenant_scope
from api.routers.agent import execute_agent, router
from brain.agents.intake import IntakeGateway, TicketFacts, TicketIntent
from brain.gateway.client import RenderedPrompt, TaskClass

_SCOPE = TenantScope(
    org_id=uuid4(), person_id=uuid4(), subject_id=uuid4(), role="resident"
)


class Gateway:
    calls = 0

    async def complete(
        self, task: TaskClass, prompt: RenderedPrompt, schema: type[BaseModel]
    ) -> BaseModel:
        self.calls += 1
        return TicketFacts(
            intent=TicketIntent.MAINTENANCE,
            category="plumbing",
            symptom_summary="The sink drains slowly.",
        )


@pytest.mark.asyncio
async def test_direct_agent_completes_real_normalizer_handoff() -> None:
    gateway = Gateway()
    run_id = uuid4()
    result = await execute_agent(
        "My sink drains slowly.", _SCOPE, run_id, cast(IntakeGateway, gateway)
    )
    assert result.run_id == run_id
    assert result.status == "completed"
    assert result.facts is not None and result.facts.category == "plumbing"
    assert gateway.calls == 1


@pytest.mark.asyncio
async def test_emergency_bypasses_model_and_does_not_claim_notification() -> None:
    gateway = Gateway()
    result = await execute_agent(
        "I smell gas in the apartment.", _SCOPE, uuid4(), cast(IntakeGateway, gateway)
    )
    assert result.status == "emergency"
    assert "has not contacted anyone" in result.summary
    assert gateway.calls == 0


@pytest.mark.asyncio
async def test_route_rejects_missing_auth_scope_and_provider_configuration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = FastAPI()
    app.include_router(router)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app, raise_app_exceptions=False),
        base_url="http://test",
    ) as client:
        denied = await client.post("/v1/agent/run", json={"description": "Leaky tap"})
        assert denied.status_code != 200
        app.dependency_overrides[get_request_tenant_scope] = lambda: _SCOPE
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        emergency = await client.post(
            "/v1/agent/run", json={"description": "I smell gas in the apartment."}
        )
        assert emergency.status_code == 200
        assert emergency.json()["status"] == "emergency"
        missing = await client.post("/v1/agent/run", json={"description": "Leaky tap"})
        assert missing.status_code == 503
        invalid = await client.post("/v1/agent/run", json={"description": "   "})
        assert invalid.status_code == 422


@pytest.mark.asyncio
async def test_provider_failure_abstains_without_facts() -> None:
    class UnavailableGateway(Gateway):
        async def complete(
            self, task: TaskClass, prompt: RenderedPrompt, schema: type[BaseModel]
        ) -> BaseModel:
            raise RuntimeError("provider unavailable")

    result = await execute_agent(
        "My sink drains slowly.",
        _SCOPE,
        uuid4(),
        cast(IntakeGateway, UnavailableGateway()),
    )
    assert result.status == "abstained"
    assert result.facts is None


@pytest.mark.asyncio
async def test_content_block_never_reaches_model() -> None:
    gateway = Gateway()
    result = await execute_agent(
        "I am going to bring a gun to the leasing office.",
        _SCOPE,
        uuid4(),
        cast(IntakeGateway, gateway),
    )
    assert result.status == "abstained"
    assert gateway.calls == 0


@pytest.mark.asyncio
async def test_route_deadline_returns_safe_gateway_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from api.routers import agent

    async def timeout_execution(
        description: str, scope: TenantScope, run_id: object, gateway: IntakeGateway
    ) -> agent.AgentRunResponse:
        import asyncio

        await asyncio.sleep(1)
        raise AssertionError("execution should have been cancelled")

    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-placeholder")
    monkeypatch.setenv("ANTHROPIC_MODEL", "test-model")
    monkeypatch.setattr(agent, "execute_agent", timeout_execution)
    monkeypatch.setattr(agent, "RUN_TIMEOUT_SECONDS", 0.001)
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_request_tenant_scope] = lambda: _SCOPE
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post("/v1/agent/run", json={"description": "Slow sink"})
    assert response.status_code == 504
    assert "private provider failure" not in response.text


@pytest.mark.asyncio
async def test_application_authentication_rejects_anonymous_agent_calls(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from api.main import create_app
    from api.deps.auth import get_supabase_jwt_verifier

    monkeypatch.setenv("SUPABASE_URL", "https://test.supabase.co")
    get_supabase_jwt_verifier.cache_clear()

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=create_app()), base_url="http://test"
    ) as client:
        response = await client.post("/v1/agent/run", json={"description": "Slow sink"})
    assert response.status_code == 401
