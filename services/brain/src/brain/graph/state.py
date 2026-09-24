"""Strict, framework-independent state for one maintenance ticket workflow.

This module is a transport contract, not a graph builder.  It carries only
typed handoffs and digest-only trace metadata so later LangGraph nodes can
checkpoint and resume without storing raw resident input, prompts, or model
responses in state.  It has no LangGraph, persistence, or tool dependency.
"""

from __future__ import annotations

import re
from decimal import Decimal
from enum import Enum
from typing import Final
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from brain.agents.auditor import AuditResult, PolicyAuditStatus
from brain.agents.diagnostician import DiagnosisResult
from brain.agents.dispatch import DispatchResult, DispatchStatus
from brain.agents.intake import TicketFacts
from brain.agents.safety import SafetyVerdict
from brain.context.envelope import ContextEnvelope


_PROVENANCE_ID_PATTERN: Final = re.compile(r"^\[(?:C|F)[1-9]\d*\]$")
_DIGEST_PATTERN: Final = re.compile(r"^[0-9a-f]{64}$")
_FAILURE_CODE_PATTERN: Final = re.compile(r"^[a-z][a-z0-9_]{0,79}$")


class DecisionMode(str, Enum):
    """Frozen decision-mode vocabulary; a mode never grants write authority."""

    AUTO = "auto"
    APPROVAL_REQUIRED = "approval_required"
    ABSTAIN = "abstain"
    ESCALATE = "escalate"


class DecisionProposal(BaseModel):
    """A cited later-stage decision proposal, not an approval or execution command."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    mode: DecisionMode
    rationale: str = Field(min_length=1, max_length=2_000)
    provenance_ids: tuple[str, ...] = Field(min_length=1, max_length=32)
    unknowns: tuple[str, ...] = Field(default=(), max_length=16)

    @field_validator("rationale")
    @classmethod
    def _require_non_blank_rationale(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("rationale must not be blank")
        return value

    @field_validator("provenance_ids")
    @classmethod
    def _validate_provenance_ids(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if len(value) != len(set(value)):
            raise ValueError("provenance_ids must not contain duplicates")
        if any(_PROVENANCE_ID_PATTERN.fullmatch(item) is None for item in value):
            raise ValueError("provenance_ids must use bracketed C or F identifiers")
        return value

    @field_validator("unknowns")
    @classmethod
    def _validate_unknowns(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if any(not item.strip() for item in value):
            raise ValueError("unknowns must not contain blank entries")
        if len(value) != len(set(value)):
            raise ValueError("unknowns must not contain duplicates")
        return value


class RetryStage(str, Enum):
    """The bounded agent handoffs whose retries are visible in the workflow trace."""

    INTAKE = "intake"
    DIAGNOSIS = "diagnosis"
    DISPATCH = "dispatch"
    POLICY_AUDIT = "policy_audit"
    CITATION_REPAIR = "citation_repair"


class RetryRecord(BaseModel):
    """A counter and safe code only; it never contains a provider response."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    stage: RetryStage
    attempts: int = Field(ge=1, le=2)
    last_failure_code: str = Field(min_length=1, max_length=80)

    @field_validator("last_failure_code")
    @classmethod
    def _validate_failure_code(cls, value: str) -> str:
        if _FAILURE_CODE_PATTERN.fullmatch(value) is None:
            raise ValueError("last_failure_code must be a safe snake_case code")
        return value


class TraceStage(str, Enum):
    """Stable workflow stages rendered by the later decision trace UI."""

    SAFETY = "safety"
    INTAKE = "intake"
    CONTEXT = "context"
    DIAGNOSIS = "diagnosis"
    DISPATCH = "dispatch"
    POLICY_AUDIT = "policy_audit"
    DECISION = "decision"


class TraceOutcome(str, Enum):
    """Non-sensitive status for a single workflow stage."""

    STARTED = "started"
    COMPLETED = "completed"
    ABSTAINED = "abstained"
    HUMAN_REVIEW_REQUIRED = "human_review_required"
    FAILED = "failed"
    SKIPPED = "skipped"


class TraceEntry(BaseModel):
    """A digest-only event suitable for later append-only audit persistence."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    sequence: int = Field(ge=1)
    stage: TraceStage
    outcome: TraceOutcome
    input_digest: str = Field(min_length=64, max_length=64)
    output_digest: str | None = Field(default=None, min_length=64, max_length=64)
    failure_code: str | None = Field(default=None, max_length=80)

    @field_validator("input_digest", "output_digest")
    @classmethod
    def _validate_digests(cls, value: str | None) -> str | None:
        if value is not None and _DIGEST_PATTERN.fullmatch(value) is None:
            raise ValueError("trace digests must be lowercase SHA-256 hex")
        return value

    @field_validator("failure_code")
    @classmethod
    def _validate_optional_failure_code(cls, value: str | None) -> str | None:
        if value is not None and _FAILURE_CODE_PATTERN.fullmatch(value) is None:
            raise ValueError("failure_code must be a safe snake_case code")
        return value

    @model_validator(mode="after")
    def _enforce_trace_shape(self) -> TraceEntry:
        if self.outcome is TraceOutcome.STARTED:
            if self.output_digest is not None or self.failure_code is not None:
                raise ValueError("a started trace event cannot have an outcome payload")
        elif self.outcome is TraceOutcome.FAILED:
            if self.failure_code is None or self.output_digest is not None:
                raise ValueError("a failed trace event requires a failure code only")
        elif self.failure_code is not None:
            raise ValueError("only failed trace events may carry a failure code")
        return self


class TicketState(BaseModel):
    """The checkpointable typed handoff for one tenant-scoped ticket run.

    Partial states are valid because each graph node contributes one field.  The
    state itself cannot invoke an agent, decide a transition, persist data, or
    authorize execution.
    """

    model_config = ConfigDict(
        arbitrary_types_allowed=True,
        extra="forbid",
        frozen=True,
        strict=True,
    )

    org_id: UUID
    ticket_id: UUID
    run_id: UUID
    safety: SafetyVerdict | None = None
    facts: TicketFacts | None = None
    envelope: ContextEnvelope | None = None
    diagnosis: DiagnosisResult | None = None
    plan: DispatchResult | None = None
    audit_result: AuditResult | None = None
    decision: DecisionProposal | None = None
    confidence: Decimal | None = Field(default=None, ge=Decimal("0"), le=Decimal("1"))
    retries: tuple[RetryRecord, ...] = Field(default=())
    trace: tuple[TraceEntry, ...] = Field(default=())

    @field_validator("retries")
    @classmethod
    def _require_one_record_per_retry_stage(
        cls, value: tuple[RetryRecord, ...]
    ) -> tuple[RetryRecord, ...]:
        stages = tuple(record.stage for record in value)
        if len(stages) != len(set(stages)):
            raise ValueError("retries must not repeat a stage")
        return value

    @field_validator("trace")
    @classmethod
    def _require_strictly_increasing_trace_sequence(
        cls, value: tuple[TraceEntry, ...]
    ) -> tuple[TraceEntry, ...]:
        sequences = tuple(entry.sequence for entry in value)
        if sequences != tuple(sorted(sequences)) or len(sequences) != len(
            set(sequences)
        ):
            raise ValueError("trace sequence numbers must be strictly increasing")
        return value

    @model_validator(mode="after")
    def _require_a_valid_precondition_for_automatic_mode(self) -> TicketState:
        if self.decision is None or self.decision.mode is not DecisionMode.AUTO:
            return self
        if self.plan is None or self.plan.status is not DispatchStatus.PROPOSED:
            raise ValueError("an automatic decision requires a proposed dispatch plan")
        if (
            self.audit_result is None
            or self.audit_result.status is not PolicyAuditStatus.COMPLIANT
        ):
            raise ValueError("an automatic decision requires a compliant policy audit")
        return self
