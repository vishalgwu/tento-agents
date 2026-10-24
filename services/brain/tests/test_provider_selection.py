"""Configured production providers share identical audited gateway wiring."""

from __future__ import annotations

from typing import Any, cast
from uuid import uuid4
from unittest.mock import AsyncMock

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from brain import production
from brain.graph.state import TicketState


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
async def test_production_provider_selection_preserves_audit_scope(
    monkeypatch: pytest.MonkeyPatch, openai_enabled: bool, expected: str
) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "test-placeholder" if openai_enabled else "")
    monkeypatch.setenv("OPENAI_MODEL", "test-openai-model")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-placeholder")
    monkeypatch.setenv("ANTHROPIC_MODEL", "test-anthropic-model")
    monkeypatch.setattr(production, "AsyncOpenAI", Client)
    monkeypatch.setattr(production, "AsyncAnthropic", Client)
    captured: list[dict[str, Any]] = []

    def gateway(**kwargs: Any) -> object:
        captured.append(kwargs)
        return object()

    org, ticket, run = uuid4(), uuid4(), uuid4()

    async def graph(inputs: object, gateways: object) -> TicketState:
        return TicketState(org_id=org, ticket_id=ticket, run_id=run)

    monkeypatch.setattr(production, "GatewayClient", gateway)
    monkeypatch.setattr(production, "_run_graph", graph)
    monkeypatch.setattr(production, "persist_graph_result", AsyncMock())
    await production.execute_maintenance(
        session=cast(AsyncSession, AsyncMock()),
        org_id=org,
        person_id=uuid4(),
        ticket_id=ticket,
        run_id=run,
    )
    assert len(captured) == 4
    for arguments in captured:
        assert list(arguments["providers"]) == [expected]
        assert arguments["context"].org_id == org
        assert arguments["context"].agent_run_id == run
        assert arguments["audit"] is not None
