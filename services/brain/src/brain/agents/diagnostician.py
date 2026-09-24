"""Grounded, tool-free maintenance diagnosis from caller-supplied context.

This module intentionally has no retrieval, persistence, filesystem, tool, or
orchestration dependency.  The caller must provide already-authorized, bounded
evidence and its provenance IDs.  The diagnostician may propose a cause and
recommended actions, but it cannot fetch more information or make a change.
"""

from __future__ import annotations

import json
import re
from enum import Enum
from typing import Final, Protocol

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from brain.agents.intake import TicketFacts
from brain.gateway.client import (
    RenderedPrompt,
    SchemaValidationError,
    TaskClass,
    load_builtin_prompt,
)


_PROVENANCE_ID_PATTERN: Final = re.compile(r"^\[(?:C|F)[1-9]\d*\]$")


class DiagnosisStatus(str, Enum):
    """Whether a diagnosis is safe to pass to the next proposal-only agent."""

    COMPLETED = "completed"
    ABSTAINED = "abstained"


class DiagnosisFailureKind(str, Enum):
    """Reasons a diagnosis is withheld without exposing model or resident text."""

    INSUFFICIENT_EVIDENCE = "insufficient_evidence"
    SCHEMA_VALIDATION = "schema_validation"
    PROVIDER_UNAVAILABLE = "provider_unavailable"
    UNSUPPORTED_CITATION = "unsupported_citation"


class RecommendedAction(BaseModel):
    """One evidence-backed next step that remains a non-executing proposal."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    action: str = Field(min_length=1, max_length=600)
    rationale: str = Field(min_length=1, max_length=1_000)
    provenance_ids: tuple[str, ...] = Field(min_length=1, max_length=8)

    @field_validator("action", "rationale")
    @classmethod
    def _require_non_blank_text(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("text fields must not be blank")
        return value

    @field_validator("provenance_ids")
    @classmethod
    def _validate_provenance_ids(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        _validate_provenance_ids(value)
        return value


class DiagnosticAssessment(BaseModel):
    """A cause hypothesis, actions, and explicit unknowns from grounded evidence."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    likely_cause: str | None = Field(default=None, max_length=1_000)
    cause_provenance_ids: tuple[str, ...] = Field(default=(), max_length=8)
    recommended_actions: tuple[RecommendedAction, ...] = Field(default=(), max_length=5)
    unknowns: tuple[str, ...] = Field(default=(), max_length=8)

    @field_validator("likely_cause")
    @classmethod
    def _reject_blank_cause(cls, value: str | None) -> str | None:
        if value is not None and not value.strip():
            raise ValueError("likely_cause must be null rather than blank")
        return value

    @field_validator("cause_provenance_ids")
    @classmethod
    def _validate_cause_provenance_ids(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        _validate_provenance_ids(value)
        return value

    @field_validator("unknowns")
    @classmethod
    def _validate_unknowns(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if any(not item.strip() for item in value):
            raise ValueError("unknowns must not contain blank entries")
        if len(value) != len(set(value)):
            raise ValueError("unknowns must not contain duplicates")
        return value

    @model_validator(mode="after")
    def _require_grounded_completion_or_explicit_abstention(
        self,
    ) -> DiagnosticAssessment:
        if self.likely_cause is None:
            if self.cause_provenance_ids:
                raise ValueError("a null likely_cause must not have cause citations")
            if not self.recommended_actions and not self.unknowns:
                raise ValueError(
                    "an abstained assessment must record at least one unknown"
                )
        elif not self.cause_provenance_ids:
            raise ValueError("a likely_cause requires at least one provenance ID")
        if self.likely_cause is not None and not self.recommended_actions:
            raise ValueError("a completed assessment requires a recommended action")
        return self


class DiagnosticianRequest(BaseModel):
    """All evidence is pushed into this boundary by the orchestrator or broker."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    ticket_facts: TicketFacts
    grounded_context: str = Field(min_length=1, max_length=100_000)
    provenance_ids: tuple[str, ...] = Field(default=(), max_length=100)

    @field_validator("grounded_context")
    @classmethod
    def _require_non_blank_context(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("grounded_context must be non-blank")
        return value

    @field_validator("provenance_ids")
    @classmethod
    def _validate_pushed_provenance_ids(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        _validate_provenance_ids(value)
        return value

    @model_validator(mode="after")
    def _require_ids_to_be_present_in_pushed_context(self) -> DiagnosticianRequest:
        missing = [
            provenance_id
            for provenance_id in self.provenance_ids
            if provenance_id not in self.grounded_context
        ]
        if missing:
            raise ValueError("provenance_ids must appear in grounded_context")
        return self


class DiagnosisResult(BaseModel):
    """Safe terminal result for a diagnosis attempt, including explicit abstention."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    status: DiagnosisStatus
    assessment: DiagnosticAssessment | None
    failure_kind: DiagnosisFailureKind | None = None

    @model_validator(mode="after")
    def _enforce_terminal_state(self) -> DiagnosisResult:
        if self.status is DiagnosisStatus.COMPLETED:
            if self.assessment is None or self.failure_kind is not None:
                raise ValueError("completed diagnosis requires an assessment only")
        elif self.assessment is not None or self.failure_kind is None:
            raise ValueError("abstained diagnosis requires a failure kind only")
        return self


class DiagnosticianGateway(Protocol):
    """The sole external capability allowed to the diagnostician."""

    async def complete(
        self,
        task: TaskClass,
        prompt: RenderedPrompt,
        schema: type[DiagnosticAssessment],
    ) -> DiagnosticAssessment:
        """Return one schema-validated, gateway-audited assessment."""


async def diagnose(
    request: DiagnosticianRequest,
    *,
    gateway: DiagnosticianGateway,
) -> DiagnosisResult:
    """Propose a grounded cause and actions from pushed context only.

    The central gateway owns retries, timeout handling, routing, and call audit.
    This function makes one diagnosis request and returns an abstention for any
    unavailable provider, schema failure, missing evidence, or citation outside
    the caller-supplied provenance set.  It never retries by modifying evidence
    and never invokes a tool.
    """

    if not request.provenance_ids:
        return _abstained(DiagnosisFailureKind.INSUFFICIENT_EVIDENCE)

    prompt = _render_diagnostician_prompt(request)
    try:
        assessment = await gateway.complete(
            TaskClass.DIAGNOSIS,
            prompt,
            DiagnosticAssessment,
        )
    except SchemaValidationError:
        return _abstained(DiagnosisFailureKind.SCHEMA_VALIDATION)
    except Exception:
        return _abstained(DiagnosisFailureKind.PROVIDER_UNAVAILABLE)

    if not _uses_only_pushed_provenance(assessment, request.provenance_ids):
        return _abstained(DiagnosisFailureKind.UNSUPPORTED_CITATION)
    return DiagnosisResult(status=DiagnosisStatus.COMPLETED, assessment=assessment)


def _render_diagnostician_prompt(request: DiagnosticianRequest) -> RenderedPrompt:
    return load_builtin_prompt("diagnostician").render(
        {
            "ticket_facts_json": json.dumps(
                request.ticket_facts.model_dump(mode="json"),
                ensure_ascii=True,
                separators=(",", ":"),
                sort_keys=True,
            ),
            "grounded_context": request.grounded_context,
            "provenance_ids": request.provenance_ids,
        },
        schema=DiagnosticAssessment,
    )


def _uses_only_pushed_provenance(
    assessment: DiagnosticAssessment,
    pushed_provenance_ids: tuple[str, ...],
) -> bool:
    allowed = set(pushed_provenance_ids)
    used = set(assessment.cause_provenance_ids)
    used.update(
        provenance_id
        for action in assessment.recommended_actions
        for provenance_id in action.provenance_ids
    )
    return used.issubset(allowed)


def _abstained(failure_kind: DiagnosisFailureKind) -> DiagnosisResult:
    return DiagnosisResult(
        status=DiagnosisStatus.ABSTAINED,
        assessment=None,
        failure_kind=failure_kind,
    )


def _validate_provenance_ids(value: tuple[str, ...]) -> None:
    if len(value) != len(set(value)):
        raise ValueError("provenance_ids must not contain duplicates")
    if any(_PROVENANCE_ID_PATTERN.fullmatch(item) is None for item in value):
        raise ValueError("provenance_ids must use bracketed C or F identifiers")
