"""Typed maintenance-intake normalization through the central model gateway."""

from __future__ import annotations

import json
from datetime import datetime
from enum import Enum
from typing import Protocol

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from brain.gateway.client import (
    RenderedPrompt,
    SchemaValidationError,
    TaskClass,
    load_builtin_prompt,
)


class TicketIntent(str, Enum):
    """Resident intent distinguishes maintenance from later non-work-order paths."""

    MAINTENANCE = "maintenance"
    QUESTION = "question"
    OTHER = "other"


class AccessWindow(BaseModel):
    """The resident-supplied preferred access window, if one was provided."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    start: datetime | None = None
    end: datetime | None = None

    @model_validator(mode="after")
    def _require_complete_or_ordered_window(self) -> AccessWindow:
        if (self.start is None) != (self.end is None):
            raise ValueError("access window start and end must be supplied together")
        if self.start is not None and self.end is not None and self.end <= self.start:
            raise ValueError("access window end must be after start")
        return self


class IntakeRequest(BaseModel):
    """Validated resident report data available to the intake normalizer."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    resident_report: str = Field(min_length=1, max_length=20_000)
    photo_captions: tuple[str, ...] = Field(default=(), max_length=5)
    access_permission: bool | None = None
    pets_present: bool | None = None
    preferred_access_window: AccessWindow | None = None

    @field_validator("resident_report")
    @classmethod
    def _require_non_blank_report(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("resident_report must be non-blank")
        return value

    @field_validator("photo_captions")
    @classmethod
    def _require_non_blank_captions(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if any(not caption.strip() for caption in value):
            raise ValueError("photo_captions must not contain blank entries")
        return value


class TicketFacts(BaseModel):
    """Strict, structured handoff from the intake agent to the maintenance loop."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    intent: TicketIntent
    category: str | None = Field(default=None, max_length=80)
    symptom_summary: str | None = Field(default=None, max_length=1_000)
    affected_asset: str | None = Field(default=None, max_length=200)
    access_permission: bool | None = None
    pets_present: bool | None = None
    preferred_access_window: AccessWindow | None = None
    media_facts: tuple[str, ...] = Field(default=(), max_length=5)

    @field_validator("category", "symptom_summary", "affected_asset")
    @classmethod
    def _reject_blank_optional_text(cls, value: str | None) -> str | None:
        if value is not None and not value.strip():
            raise ValueError("optional text must be null rather than blank")
        return value

    @field_validator("media_facts")
    @classmethod
    def _reject_blank_media_facts(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if any(not fact.strip() for fact in value):
            raise ValueError("media_facts must not contain blank entries")
        return value


class IntakeStatus(str, Enum):
    """The explicit next action after normalisation succeeds or exhausts repair."""

    COMPLETED = "completed"
    HUMAN_REVIEW_REQUIRED = "human_review_required"


class IntakeFailureKind(str, Enum):
    """Safe failure classification with no resident or model response content."""

    SCHEMA_VALIDATION = "schema_validation"
    PROVIDER_UNAVAILABLE = "provider_unavailable"


class IntakeNormalizationResult(BaseModel):
    """Outcome that ensures an unrepaired model answer never flows downstream."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    status: IntakeStatus
    facts: TicketFacts | None
    repair_attempted: bool
    failure_kind: IntakeFailureKind | None = None

    @model_validator(mode="after")
    def _enforce_terminal_state(self) -> IntakeNormalizationResult:
        if self.status is IntakeStatus.COMPLETED:
            if self.facts is None or self.failure_kind is not None:
                raise ValueError("completed intake requires facts and no failure kind")
        elif self.facts is not None or self.failure_kind is None:
            raise ValueError("human review requires a failure kind and no facts")
        return self


class IntakeGateway(Protocol):
    """The single central completion capability allowed to the intake agent."""

    async def complete(
        self,
        task: TaskClass,
        prompt: RenderedPrompt,
        schema: type[TicketFacts],
    ) -> TicketFacts:
        """Return one schema-validated ticket-facts response."""


async def normalize_intake(
    request: IntakeRequest,
    *,
    gateway: IntakeGateway,
) -> IntakeNormalizationResult:
    """Normalize an intake report with one schema-repair attempt, then escalate.

    The resident-supplied access, pet, and preferred-window fields are
    authoritative. They replace any conflicting model output before the facts
    leave this agent. The raw invalid response from a failed first attempt stays
    in memory only long enough to build one repair prompt.
    """

    prompt = _render_intake_prompt(request)
    try:
        facts = await gateway.complete(
            TaskClass.INTAKE_NORMALIZATION,
            prompt,
            TicketFacts,
        )
    except SchemaValidationError as first_error:
        return await _repair_once(request, gateway, first_error)
    except Exception:
        return _human_review(
            repair_attempted=False,
            failure_kind=IntakeFailureKind.PROVIDER_UNAVAILABLE,
        )
    return _completed(request, facts, repair_attempted=False)


async def _repair_once(
    request: IntakeRequest,
    gateway: IntakeGateway,
    first_error: SchemaValidationError,
) -> IntakeNormalizationResult:
    repair_prompt = _render_repair_prompt(request, first_error)
    try:
        facts = await gateway.complete(
            TaskClass.INTAKE_NORMALIZATION,
            repair_prompt,
            TicketFacts,
        )
    except SchemaValidationError:
        return _human_review(
            repair_attempted=True,
            failure_kind=IntakeFailureKind.SCHEMA_VALIDATION,
        )
    except Exception:
        return _human_review(
            repair_attempted=True,
            failure_kind=IntakeFailureKind.PROVIDER_UNAVAILABLE,
        )
    return _completed(request, facts, repair_attempted=True)


def _completed(
    request: IntakeRequest, facts: TicketFacts, *, repair_attempted: bool
) -> IntakeNormalizationResult:
    return IntakeNormalizationResult(
        status=IntakeStatus.COMPLETED,
        facts=_apply_authoritative_input(request, facts),
        repair_attempted=repair_attempted,
    )


def _human_review(
    *, repair_attempted: bool, failure_kind: IntakeFailureKind
) -> IntakeNormalizationResult:
    return IntakeNormalizationResult(
        status=IntakeStatus.HUMAN_REVIEW_REQUIRED,
        facts=None,
        repair_attempted=repair_attempted,
        failure_kind=failure_kind,
    )


def _apply_authoritative_input(
    request: IntakeRequest, facts: TicketFacts
) -> TicketFacts:
    payload = facts.model_dump()
    payload.update(
        {
            "access_permission": request.access_permission,
            "pets_present": request.pets_present,
            "preferred_access_window": request.preferred_access_window,
        }
    )
    return TicketFacts.model_validate(payload)


def _render_intake_prompt(request: IntakeRequest) -> RenderedPrompt:
    return load_builtin_prompt("intake-normalize").render(
        _prompt_values(request), schema=TicketFacts
    )


def _render_repair_prompt(
    request: IntakeRequest, first_error: SchemaValidationError
) -> RenderedPrompt:
    values = _prompt_values(request)
    values.update(
        {
            "invalid_output": first_error.response_text,
            "validation_errors_json": json.dumps(
                first_error.validation_errors,
                ensure_ascii=True,
                separators=(",", ":"),
                sort_keys=True,
            ),
        }
    )
    return load_builtin_prompt("intake-repair").render(values, schema=TicketFacts)


def _prompt_values(request: IntakeRequest) -> dict[str, object]:
    return {
        "resident_report": request.resident_report,
        "photo_captions": request.photo_captions,
        "ticket_metadata_json": json.dumps(
            {
                "access_permission": request.access_permission,
                "pets_present": request.pets_present,
                "preferred_access_window": (
                    request.preferred_access_window.model_dump(mode="json")
                    if request.preferred_access_window is not None
                    else None
                ),
            },
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        ),
    }
