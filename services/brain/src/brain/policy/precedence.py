"""Deterministic resolution of conflicting policy claims.

Policy precedence is a control, not a model preference.  Callers provide the
already-retrieved claims and their verified authorities; this module selects a
controlling outcome using the frozen authority order and abstains on a conflict
at the same authority level.  It never infers authority from source text,
retrieves evidence, persists a decision, or calls a model.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence
from enum import Enum
from typing import Final

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from brain.retrieval.ingest import Authority


AUTHORITY_PRECEDENCE: Final[dict[Authority, int]] = {
    Authority.STATUTE: 1,
    Authority.LEASE: 2,
    Authority.INTERNAL_SOP: 3,
    Authority.VENDOR_CONTRACT: 4,
}


class PolicyResolutionStatus(str, Enum):
    """Whether one outcome controls a policy question."""

    RESOLVED = "resolved"
    HUMAN_REVIEW_REQUIRED = "human_review_required"


class PolicyClaim(BaseModel):
    """One normalized, cited outcome for a single policy question.

    ``outcome`` is deliberately an opaque canonical value owned by the caller's
    policy contract.  Comparing the value exactly avoids this control making a
    semantic or legal judgment from source prose.
    """

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    claim_id: str = Field(min_length=1, max_length=200)
    policy_key: str = Field(min_length=1, max_length=200)
    outcome: str = Field(min_length=1, max_length=2_000)
    authority: Authority
    provenance_ids: tuple[str, ...] = Field(min_length=1, max_length=16)

    @field_validator("claim_id", "policy_key", "outcome")
    @classmethod
    def _require_non_blank_text(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("text fields must not be blank")
        return value

    @field_validator("provenance_ids")
    @classmethod
    def _require_distinct_non_blank_provenance(
        cls, value: tuple[str, ...]
    ) -> tuple[str, ...]:
        if any(not item.strip() for item in value):
            raise ValueError("provenance_ids must not contain blank entries")
        if len(value) != len(set(value)):
            raise ValueError("provenance_ids must not contain duplicates")
        return value


class PolicyResolution(BaseModel):
    """The deterministic result for one policy key, including its audit trail."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    policy_key: str = Field(min_length=1, max_length=200)
    status: PolicyResolutionStatus
    controlling_authority: Authority
    controlling_outcome: str | None = Field(default=None, max_length=2_000)
    controlling_claim_ids: tuple[str, ...] = Field(default=())
    superseded_claim_ids: tuple[str, ...] = Field(default=())
    conflicting_claim_ids: tuple[str, ...] = Field(default=())

    @model_validator(mode="after")
    def _enforce_terminal_shape(self) -> PolicyResolution:
        all_ids = (
            *self.controlling_claim_ids,
            *self.superseded_claim_ids,
            *self.conflicting_claim_ids,
        )
        if len(all_ids) != len(set(all_ids)):
            raise ValueError("claim IDs must appear in exactly one resolution bucket")
        if self.status is PolicyResolutionStatus.RESOLVED:
            if (
                self.controlling_outcome is None
                or not self.controlling_claim_ids
                or self.conflicting_claim_ids
            ):
                raise ValueError(
                    "a resolved policy key requires controlling claims and no conflicts"
                )
        elif (
            self.controlling_outcome is not None
            or self.controlling_claim_ids
            or len(self.conflicting_claim_ids) < 2
        ):
            raise ValueError(
                "a human-review policy key requires two or more same-rank conflicts"
            )
        return self


def authority_rank(authority: Authority) -> int:
    """Return the frozen rank where a lower number is more authoritative."""

    try:
        return AUTHORITY_PRECEDENCE[authority]
    except KeyError as exc:  # Defensive if the enum is expanded without this control.
        raise ValueError(
            f"authority has no configured precedence: {authority!r}"
        ) from exc


def resolve_policy_conflicts(
    claims: Sequence[PolicyClaim],
) -> tuple[PolicyResolution, ...]:
    """Resolve each policy key using statute > lease > SOP > vendor contract.

    Claims at a lower authority are retained as superseded for the audit trail.
    Claims at the controlling authority must agree exactly on their canonical
    outcome.  When they do not, selecting either outcome would be arbitrary, so
    the function returns a typed human-review requirement instead.
    """

    if isinstance(claims, (str, bytes)):
        raise ValueError("claims must be a sequence of PolicyClaim values")
    normalized_claims = tuple(claims)
    if any(not isinstance(claim, PolicyClaim) for claim in normalized_claims):
        raise ValueError("claims must contain only PolicyClaim values")
    claim_ids = tuple(claim.claim_id for claim in normalized_claims)
    if len(claim_ids) != len(set(claim_ids)):
        raise ValueError("claim_id values must be unique within one resolution")

    by_policy_key: dict[str, list[PolicyClaim]] = defaultdict(list)
    for claim in normalized_claims:
        by_policy_key[claim.policy_key].append(claim)

    return tuple(
        _resolve_one_policy_key(policy_key, by_policy_key[policy_key])
        for policy_key in sorted(by_policy_key)
    )


def _resolve_one_policy_key(
    policy_key: str,
    claims: Sequence[PolicyClaim],
) -> PolicyResolution:
    ordered_claims = tuple(sorted(claims, key=lambda claim: claim.claim_id))
    controlling_rank = min(authority_rank(claim.authority) for claim in ordered_claims)
    controlling_claims = tuple(
        claim
        for claim in ordered_claims
        if authority_rank(claim.authority) == controlling_rank
    )
    superseded_claim_ids = tuple(
        claim.claim_id
        for claim in ordered_claims
        if authority_rank(claim.authority) > controlling_rank
    )
    outcomes = {claim.outcome for claim in controlling_claims}
    controlling_authority = controlling_claims[0].authority

    if len(outcomes) != 1:
        return PolicyResolution(
            policy_key=policy_key,
            status=PolicyResolutionStatus.HUMAN_REVIEW_REQUIRED,
            controlling_authority=controlling_authority,
            superseded_claim_ids=superseded_claim_ids,
            conflicting_claim_ids=tuple(claim.claim_id for claim in controlling_claims),
        )

    return PolicyResolution(
        policy_key=policy_key,
        status=PolicyResolutionStatus.RESOLVED,
        controlling_authority=controlling_authority,
        controlling_outcome=controlling_claims[0].outcome,
        controlling_claim_ids=tuple(claim.claim_id for claim in controlling_claims),
        superseded_claim_ids=superseded_claim_ids,
    )
