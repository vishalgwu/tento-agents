"""Regression coverage for deterministic policy conflict resolution."""

from __future__ import annotations

import pytest

from brain.policy.precedence import (
    PolicyClaim,
    PolicyResolutionStatus,
    authority_rank,
    resolve_policy_conflicts,
)
from brain.retrieval.ingest import Authority


def _claim(
    claim_id: str,
    authority: Authority,
    outcome: str,
    *,
    policy_key: str = "maintenance_charge",
) -> PolicyClaim:
    return PolicyClaim(
        claim_id=claim_id,
        policy_key=policy_key,
        outcome=outcome,
        authority=authority,
        provenance_ids=(f"[{claim_id.upper()}]",),
    )


def test_statute_controls_all_lower_authorities_and_preserves_them_for_audit() -> None:
    resolution = resolve_policy_conflicts(
        (
            _claim("vendor", Authority.VENDOR_CONTRACT, "vendor_pays"),
            _claim("sop", Authority.INTERNAL_SOP, "owner_pays"),
            _claim("lease", Authority.LEASE, "resident_pays"),
            _claim("statute", Authority.STATUTE, "legal_review_required"),
        )
    )

    assert len(resolution) == 1
    assert resolution[0].status is PolicyResolutionStatus.RESOLVED
    assert resolution[0].controlling_authority is Authority.STATUTE
    assert resolution[0].controlling_outcome == "legal_review_required"
    assert resolution[0].controlling_claim_ids == ("statute",)
    assert resolution[0].superseded_claim_ids == ("lease", "sop", "vendor")


def test_lease_controls_when_no_statute_exists() -> None:
    resolution = resolve_policy_conflicts(
        (
            _claim("vendor", Authority.VENDOR_CONTRACT, "vendor_pays"),
            _claim("sop", Authority.INTERNAL_SOP, "owner_pays"),
            _claim("lease", Authority.LEASE, "resident_pays"),
        )
    )[0]

    assert resolution.status is PolicyResolutionStatus.RESOLVED
    assert resolution.controlling_authority is Authority.LEASE
    assert resolution.controlling_outcome == "resident_pays"
    assert resolution.superseded_claim_ids == ("sop", "vendor")


def test_same_rank_conflict_requires_human_review_instead_of_arbitrary_selection() -> (
    None
):
    resolution = resolve_policy_conflicts(
        (
            _claim("lease-a", Authority.LEASE, "owner_pays"),
            _claim("lease-b", Authority.LEASE, "resident_pays"),
            _claim("vendor", Authority.VENDOR_CONTRACT, "vendor_pays"),
        )
    )[0]

    assert resolution.status is PolicyResolutionStatus.HUMAN_REVIEW_REQUIRED
    assert resolution.controlling_authority is Authority.LEASE
    assert resolution.controlling_outcome is None
    assert resolution.conflicting_claim_ids == ("lease-a", "lease-b")
    assert resolution.superseded_claim_ids == ("vendor",)


def test_equal_controlling_claims_and_multiple_policy_keys_are_deterministic() -> None:
    resolutions = resolve_policy_conflicts(
        (
            _claim("sop-b", Authority.INTERNAL_SOP, "manager_review"),
            _claim("sop-a", Authority.INTERNAL_SOP, "manager_review"),
            _claim(
                "vendor-a",
                Authority.VENDOR_CONTRACT,
                "vendor_review",
                policy_key="vendor_access",
            ),
        )
    )

    assert [resolution.policy_key for resolution in resolutions] == [
        "maintenance_charge",
        "vendor_access",
    ]
    assert resolutions[0].controlling_claim_ids == ("sop-a", "sop-b")
    assert resolutions[0].controlling_outcome == "manager_review"
    assert resolutions[1].controlling_authority is Authority.VENDOR_CONTRACT


def test_rejects_duplicate_claim_ids_and_exposes_frozen_ranks() -> None:
    with pytest.raises(ValueError, match="unique"):
        resolve_policy_conflicts(
            (
                _claim("duplicate", Authority.STATUTE, "a"),
                _claim("duplicate", Authority.LEASE, "b"),
            )
        )

    assert authority_rank(Authority.STATUTE) < authority_rank(Authority.LEASE)
    assert authority_rank(Authority.LEASE) < authority_rank(Authority.INTERNAL_SOP)
    assert authority_rank(Authority.INTERNAL_SOP) < authority_rank(
        Authority.VENDOR_CONTRACT
    )
