"""Compatibility execution uses the same provider preference as durable runs."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from uuid import uuid4

import pytest

from api.deps.tenancy import TenantScope
from api.routers import agent


class Client:
    def __init__(self, **kwargs: object) -> None:
        pass

    async def __aenter__(self) -> Client:
        return self

    async def __aexit__(self, *args: object) -> None:
        pass


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "openai_enabled,expected", [(True, "openai"), (False, "anthropic")]
)
async def test_compatibility_provider_selection_without_network(
    monkeypatch: pytest.MonkeyPatch, openai_enabled: bool, expected: str
) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "test-placeholder" if openai_enabled else "")
    monkeypatch.setenv("OPENAI_MODEL", "test-openai-model")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-placeholder")
    monkeypatch.setenv("ANTHROPIC_MODEL", "test-anthropic-model")
    monkeypatch.setattr(agent, "AsyncOpenAI", Client)
    monkeypatch.setattr(agent, "AsyncAnthropic", Client)
    captured: dict[str, Any] = {}

    def gateway(**kwargs: Any) -> SimpleNamespace:
        captured.update(kwargs)
        return SimpleNamespace()

    async def execute(
        description: str, scope: TenantScope, run_id: object, gateway: object
    ) -> agent.AgentRunResponse:
        return agent.AgentRunResponse(
            run_id=uuid4(), status="completed", summary="Mock analysis"
        )

    monkeypatch.setattr(agent, "GatewayClient", gateway)
    monkeypatch.setattr(agent, "execute_agent", execute)
    person = uuid4()
    scope = TenantScope(
        org_id=uuid4(), person_id=person, subject_id=person, role="resident"
    )
    result = await agent.run_agent(
        agent.AgentRunRequest(description="Kitchen tap drips"), scope
    )
    assert result.status == "completed"
    assert list(captured["providers"]) == [expected]
    assert all(route.provider == expected for route in captured["tier_routes"].values())
