"""Policy-only audit of a proposed dispatch decision.

The auditor sees a dispatch proposal and cited policy evidence, never the
diagnostician's hypothesis or reasoning.  Deterministic precedence resolution
runs before the model is consulted; a same-rank policy conflict therefore
withholds an audit result rather than asking a model to choose an authority.
This module is proposal-only and has no retrieval, persistence, filesystem,
tool, or orchestration dependency.
"""

from __future__ import annotations

import json
import re
from enum import Enum
from typing import Final, Protocol

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from brain.agents.dispatch import DispatchPlan
from brain.gateway.client import (
    RenderedPrompt,
    SchemaValidationError,
    TaskClass,
    load_builtin_prompt,
)
from brain.policy.precedence import (
    PolicyClaim,
    PolicyResolution,
    PolicyResolutionStatus,
    resolve_policy_conflicts,
)
from brain.retrieval.ingest import Authority


_PROVENANCE_ID_PATTERN: Final = re.compile(r"^\[(?:C|F)[1-9]\d*\]$")
_AUDIT_AUTHORITIES: Final = frozenset(
    {Authority.STATUTE, Authority.LEASE, Authority.INTERNAL_SOP}
)


class AuditFindingVerdict(str, Enum):
    """The model's assessment for one already-resolved policy question."""

    COMPLIANT = "compliant"
    CONFLICT = "conflict"
    UNKNOWN = "unknown"


class PolicyAuditFinding(BaseModel):
    """A cited, non-executing audit finding for one policy question."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    policy_key: str = Field(min_length=1, max_length=200)
    verdict: AuditFindingVerdict
    rationale: str = Field(min_length=1, max_length=1_000)
    provenance_ids: tuple[str, ...] = Field(min_length=1, max_length=16)

    @field_validator("policy_key", "rationale")
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


class PolicyAuditAssessment(BaseModel):
    """Model findings; terminal handling remains deterministic in this module."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    findings: tuple[PolicyAuditFinding, ...] = Field(min_length=1, max_length=32)
    unknowns: tuple[str, ...] = Field(default=(), max_length=16)

    @field_validator("unknowns")
    @classmethod
    def _validate_unknowns(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if any(not item.strip() for item in value):
            raise ValueError("unknowns must not contain blank entries")
        if len(value) != len(set(value)):
            raise ValueError("unknowns must not contain duplicates")
        return value

    @model_validator(mode="after")
    def _require_one_finding_per_policy_key(self) -> PolicyAuditAssessment:
        policy_keys = tuple(finding.policy_key for finding in self.findings)
        if len(policy_keys) != len(set(policy_keys)):
            raise ValueError("findings must not repeat a policy_key")
        return self


class PolicyAuditStatus(str, Enum):
    """Safe terminal states for an audit that has no execution authority."""

    COMPLIANT = "compliant"
    CONFLICT = "conflict"
    HUMAN_REVIEW_REQUIRED = "human_review_required"


class PolicyAuditFailureKind(str, Enum):
    """Reasons an audit cannot safely release an approving or conflict result."""

    INSUFFICIENT_POLICY = "insufficient_policy"
    UNRESOLVED_PRECEDENCE = "unresolved_precedence"
    SCHEMA_VALIDATION = "schema_validation"
    PROVIDER_UNAVAILABLE = "provider_unavailable"
    UNSUPPORTED_CITATION = "unsupported_citation"
    POLICY_KEY_MISMATCH = "policy_key_mismatch"


class AuditResult(BaseModel):
    """Typed audit handoff for a later deterministic decision gate."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    status: PolicyAuditStatus
    assessment: PolicyAuditAssessment | None
    policy_resolutions: tuple[PolicyResolution, ...] = Field(min_length=1)
    failure_kind: PolicyAuditFailureKind | None = None

    @model_validator(mode="after")
    def _enforce_terminal_shape(self) -> AuditResult:
        if self.status is PolicyAuditStatus.HUMAN_REVIEW_REQUIRED:
            if self.failure_kind is None:
                raise ValueError("human review requires a failure kind")
        elif self.assessment is None or self.failure_kind is not None:
            raise ValueError("completed audit states require an assessment only")
        return self


class AuditorRequest(BaseModel):
    """Explicitly bounded input for an independent policy review.

    The request intentionally accepts neither a diagnostic assessment nor ticket
    symptoms.  The audit reasons only over the proposed dispatch decision and
    authoritative policy evidence supplied by the caller.
    """

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    dispatch_plan: DispatchPlan
    policy_context: str = Field(min_length=1, max_length=100_000)
    policy_claims: tuple[PolicyClaim, ...] = Field(min_length=1, max_length=64)

    @field_validator("policy_context")
    @classmethod
    def _require_non_blank_policy_context(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("policy_context must be non-blank")
        return value

    @field_validator("policy_claims")
    @classmethod
    def _validate_auditable_policy_claims(
        cls, value: tuple[PolicyClaim, ...]
    ) -> tuple[PolicyClaim, ...]:
        claim_ids = tuple(claim.claim_id for claim in value)
        if len(claim_ids) != len(set(claim_ids)):
            raise ValueError("policy_claims must not repeat claim IDs")
        if any(claim.authority not in _AUDIT_AUTHORITIES for claim in value):
            raise ValueError(
                "auditor policy claims must be statute, lease, or internal_sop"
            )
        for claim in value:
            _validate_provenance_ids(claim.provenance_ids)
        return value

    @model_validator(mode="after")
    def _require_claim_provenance_in_policy_context(self) -> AuditorRequest:
        missing = [
            provenance_id
            for claim in self.policy_claims
            for provenance_id in claim.provenance_ids
            if provenance_id not in self.policy_context
        ]
        if missing:
            raise ValueError(
                "policy claim provenance_ids must appear in policy_context"
            )
        return self


class AuditorGateway(Protocol):
    """The sole external capability available to the policy auditor."""

    async def complete(
        self,
        task: TaskClass,
        prompt: RenderedPrompt,
        schema: type[PolicyAuditAssessment],
    ) -> PolicyAuditAssessment:
        """Return one schema-validated policy assessment through the gateway."""


async def audit_dispatch(
    request: AuditorRequest,
    *,
    gateway: AuditorGateway,
) -> AuditResult:
    """Check a dispatch plan against resolved policy without diagnostic reasoning.

    A precedence conflict stops before a model call.  Otherwise the central
    gateway receives only a serialized dispatch plan, resolved policy outcomes,
    and the cited policy context.  Findings must cover exactly every policy key
    and cite only the supplied policy evidence.
    """

    resolutions = resolve_policy_conflicts(request.policy_claims)
    if any(
        resolution.status is PolicyResolutionStatus.HUMAN_REVIEW_REQUIRED
        for resolution in resolutions
    ):
        return _human_review(
            resolutions=resolutions,
            failure_kind=PolicyAuditFailureKind.UNRESOLVED_PRECEDENCE,
        )

    prompt = _render_audit_prompt(request, resolutions=resolutions)
    try:
        assessment = await gateway.complete(
            TaskClass.POLICY_AUDIT,
            prompt,
            PolicyAuditAssessment,
        )
    except SchemaValidationError:
        return _human_review(
            resolutions=resolutions,
            failure_kind=PolicyAuditFailureKind.SCHEMA_VALIDATION,
        )
    except Exception:
        return _human_review(
            resolutions=resolutions,
            failure_kind=PolicyAuditFailureKind.PROVIDER_UNAVAILABLE,
        )

    expected_policy_keys = {resolution.policy_key for resolution in resolutions}
    actual_policy_keys = {finding.policy_key for finding in assessment.findings}
    if actual_policy_keys != expected_policy_keys:
        return _human_review(
            resolutions=resolutions,
            failure_kind=PolicyAuditFailureKind.POLICY_KEY_MISMATCH,
        )

    allowed_provenance_ids = set(_policy_provenance_ids(request.policy_claims))
    used_provenance_ids = {
        provenance_id
        for finding in assessment.findings
        for provenance_id in finding.provenance_ids
    }
    if not used_provenance_ids.issubset(allowed_provenance_ids):
        return _human_review(
            resolutions=resolutions,
            failure_kind=PolicyAuditFailureKind.UNSUPPORTED_CITATION,
        )

    if assessment.unknowns or any(
        finding.verdict is AuditFindingVerdict.UNKNOWN
        for finding in assessment.findings
    ):
        return AuditResult(
            status=PolicyAuditStatus.HUMAN_REVIEW_REQUIRED,
            assessment=assessment,
            policy_resolutions=resolutions,
            failure_kind=PolicyAuditFailureKind.INSUFFICIENT_POLICY,
        )
    if any(
        finding.verdict is AuditFindingVerdict.CONFLICT
        for finding in assessment.findings
    ):
        return AuditResult(
            status=PolicyAuditStatus.CONFLICT,
            assessment=assessment,
            policy_resolutions=resolutions,
        )
    return AuditResult(
        status=PolicyAuditStatus.COMPLIANT,
        assessment=assessment,
        policy_resolutions=resolutions,
    )


def _render_audit_prompt(
    request: AuditorRequest,
    *,
    resolutions: tuple[PolicyResolution, ...],
) -> RenderedPrompt:
    return load_builtin_prompt("policy-audit").render(
        {
            "dispatch_plan_json": json.dumps(
                request.dispatch_plan.model_dump(mode="json"),
                ensure_ascii=True,
                separators=(",", ":"),
                sort_keys=True,
            ),
            "policy_resolutions_json": json.dumps(
                [resolution.model_dump(mode="json") for resolution in resolutions],
                ensure_ascii=True,
                separators=(",", ":"),
                sort_keys=True,
            ),
            "policy_context": request.policy_context,
            "provenance_ids": _policy_provenance_ids(request.policy_claims),
        },
        schema=PolicyAuditAssessment,
    )


def _human_review(
    *,
    resolutions: tuple[PolicyResolution, ...],
    failure_kind: PolicyAuditFailureKind,
) -> AuditResult:
    return AuditResult(
        status=PolicyAuditStatus.HUMAN_REVIEW_REQUIRED,
        assessment=None,
        policy_resolutions=resolutions,
        failure_kind=failure_kind,
    )


def _validate_provenance_ids(value: tuple[str, ...]) -> None:
    if len(value) != len(set(value)):
        raise ValueError("policy provenance_ids must not contain duplicates")
    if any(_PROVENANCE_ID_PATTERN.fullmatch(item) is None for item in value):
        raise ValueError("policy provenance_ids must use bracketed C or F identifiers")


def _policy_provenance_ids(claims: tuple[PolicyClaim, ...]) -> tuple[str, ...]:
    """Return policy evidence IDs once, preserving the caller's source order."""

    seen: set[str] = set()
    provenance_ids: list[str] = []
    for claim in claims:
        for provenance_id in claim.provenance_ids:
            if provenance_id not in seen:
                seen.add(provenance_id)
                provenance_ids.append(provenance_id)
    return tuple(provenance_ids)
