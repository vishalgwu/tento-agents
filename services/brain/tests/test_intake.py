"""Regression coverage for strict, repair-once intake normalisation."""

from __future__ import annotations

from datetime import datetime

import pytest

from brain.agents.intake import (
    AccessWindow,
    IntakeFailureKind,
    IntakeRequest,
    IntakeStatus,
    TicketFacts,
    TicketIntent,
    normalize_intake,
)
from brain.gateway.client import (
    GatewayError,
    RenderedPrompt,
    SchemaValidationError,
    TaskClass,
)


class _IntakeGateway:
    def __init__(self, responses: list[TicketFacts | Exception]) -> None:
        self._responses = iter(responses)
        self.calls: list[tuple[TaskClass, RenderedPrompt, type[TicketFacts]]] = []

    async def complete(
        self,
        task: TaskClass,
        prompt: RenderedPrompt,
        schema: type[TicketFacts],
    ) -> TicketFacts:
        self.calls.append((task, prompt, schema))
        response = next(self._responses)
        if isinstance(response, Exception):
            raise response
        return response


def _request() -> IntakeRequest:
    return IntakeRequest(
        resident_report="The kitchen sink leaks whenever the dishwasher drains.",
        photo_captions=("Water is visible under the sink cabinet.",),
        access_permission=True,
        pets_present=False,
        preferred_access_window=AccessWindow(
            start=datetime.fromisoformat("2026-09-16T09:00:00-04:00"),
            end=datetime.fromisoformat("2026-09-16T12:00:00-04:00"),
        ),
    )


def _facts(**overrides: object) -> TicketFacts:
    payload: dict[str, object] = {
        "intent": TicketIntent.MAINTENANCE,
        "category": "plumbing",
        "symptom_summary": "Kitchen sink leaks during dishwasher drainage.",
        "affected_asset": "kitchen sink drain",
        "access_permission": False,
        "pets_present": True,
        "preferred_access_window": None,
        "media_facts": ("Water is visible under the sink cabinet.",),
    }
    payload.update(overrides)
    return TicketFacts.model_validate(payload)


@pytest.mark.asyncio
async def test_intake_returns_strict_facts_and_preserves_authoritative_metadata() -> (
    None
):
    gateway = _IntakeGateway([_facts()])

    result = await normalize_intake(_request(), gateway=gateway)

    assert result.status is IntakeStatus.COMPLETED
    assert result.repair_attempted is False
    assert result.facts is not None
    assert result.facts.intent is TicketIntent.MAINTENANCE
    assert result.facts.access_permission is True
    assert result.facts.pets_present is False
    assert result.facts.preferred_access_window == _request().preferred_access_window
    assert gateway.calls[0][0] is TaskClass.INTAKE_NORMALIZATION
    assert gateway.calls[0][2] is TicketFacts
    assert "dishwasher drains" in gateway.calls[0][1].dynamic_suffix


@pytest.mark.asyncio
async def test_intake_repairs_one_schema_failure_with_specific_safe_errors() -> None:
    schema_error = SchemaValidationError(
        "schema invalid",
        response_text='{"intent":"maintenance","category":42}',
        validation_errors=(
            {
                "loc": ["category"],
                "type": "string_type",
                "msg": "Input should be a valid string",
            },
        ),
    )
    gateway = _IntakeGateway([schema_error, _facts(category="appliance")])

    result = await normalize_intake(_request(), gateway=gateway)

    assert result.status is IntakeStatus.COMPLETED
    assert result.repair_attempted is True
    assert result.facts is not None
    assert result.facts.category == "appliance"
    assert len(gateway.calls) == 2
    repair_request = gateway.calls[1][1].dynamic_suffix
    assert "invalid_model_output" in repair_request
    assert '"string_type"' in repair_request
    assert 'category":42' in repair_request


@pytest.mark.asyncio
async def test_second_schema_failure_routes_to_human_instead_of_third_model_call() -> (
    None
):
    schema_error = SchemaValidationError(
        "schema invalid",
        response_text="not valid JSON",
        validation_errors=({"loc": [], "type": "json_invalid", "msg": "Invalid JSON"},),
    )
    gateway = _IntakeGateway([schema_error, schema_error])

    result = await normalize_intake(_request(), gateway=gateway)

    assert result.status is IntakeStatus.HUMAN_REVIEW_REQUIRED
    assert result.facts is None
    assert result.repair_attempted is True
    assert result.failure_kind is IntakeFailureKind.SCHEMA_VALIDATION
    assert len(gateway.calls) == 2


@pytest.mark.asyncio
async def test_provider_failure_routes_directly_to_human_review() -> None:
    gateway = _IntakeGateway([GatewayError("gateway unavailable")])

    result = await normalize_intake(_request(), gateway=gateway)

    assert result.status is IntakeStatus.HUMAN_REVIEW_REQUIRED
    assert result.repair_attempted is False
    assert result.failure_kind is IntakeFailureKind.PROVIDER_UNAVAILABLE


@pytest.mark.asyncio
async def test_unexpected_gateway_failure_routes_to_human_review() -> None:
    gateway = _IntakeGateway([RuntimeError("unexpected transport failure")])

    result = await normalize_intake(_request(), gateway=gateway)

    assert result.status is IntakeStatus.HUMAN_REVIEW_REQUIRED
    assert result.repair_attempted is False
    assert result.failure_kind is IntakeFailureKind.PROVIDER_UNAVAILABLE


def test_access_window_requires_both_endpoints_and_a_positive_range() -> None:
    with pytest.raises(ValueError, match="supplied together"):
        AccessWindow(start=datetime.fromisoformat("2026-09-16T09:00:00-04:00"))
    with pytest.raises(ValueError, match="after start"):
        AccessWindow(
            start=datetime.fromisoformat("2026-09-16T12:00:00-04:00"),
            end=datetime.fromisoformat("2026-09-16T09:00:00-04:00"),
        )


def test_ticket_facts_reject_unknown_fields_and_blank_optional_text() -> None:
    with pytest.raises(ValueError, match="Extra inputs"):
        TicketFacts.model_validate(
            {"intent": TicketIntent.MAINTENANCE, "unsupported": "no"}
        )
    with pytest.raises(ValueError, match="null rather than blank"):
        _facts(category="   ")
