"""Regression coverage for independent, policy-only dispatch audits."""

from __future__ import annotations

from typing import cast
import pytest

from brain.agents.auditor import (
    AuditFindingVerdict,
    AuditorRequest,
    PolicyAuditAssessment,
    PolicyAuditFailureKind,
    PolicyAuditFinding,
    PolicyAuditStatus,
    audit_dispatch,
)
from brain.agents.dispatch import (
    DispatchFulfillment,
    DispatchPlan,
    DispatchProposal,
    ResponsibleParty,
    Trade,
)
from brain.gateway.client import (
    GatewayError,
    RenderedPrompt,
    SchemaValidationError,
    TaskClass,
)
from brain.policy.precedence import PolicyClaim
from brain.retrieval.ingest import Authority


class _AuditorGateway:
    def __init__(self, result: PolicyAuditAssessment | Exception) -> None:
        self._result = result
        self.calls: list[
            tuple[TaskClass, RenderedPrompt, type[PolicyAuditAssessment]]
        ] = []

    async def complete(
        self,
        task: TaskClass,
        prompt: RenderedPrompt,
        schema: type[PolicyAuditAssessment],
    ) -> PolicyAuditAssessment:
        self.calls.append((task, prompt, schema))
        if isinstance(self._result, Exception):
            raise self._result
        return self._result


def _dispatch_plan() -> DispatchPlan:
    return DispatchPlan(
        proposal=DispatchProposal(
            trade=Trade.PLUMBING,
            fulfillment=DispatchFulfillment.IN_HOUSE,
            scope_summary="Assess the reported kitchen drain backup.",
            parts_hint=("P-trap assembly",),
            responsible_party=ResponsibleParty.UNDETERMINED,
            provenance_ids=("[F1]",),
        )
    )


def _claim(
    claim_id: str,
    authority: Authority,
    outcome: str,
    provenance_id: str,
    *,
    policy_key: str = "maintenance_charge",
) -> PolicyClaim:
    return PolicyClaim(
        claim_id=claim_id,
        policy_key=policy_key,
        outcome=outcome,
        authority=authority,
        provenance_ids=(provenance_id,),
    )


def _request(*, claims: tuple[PolicyClaim, ...] | None = None) -> AuditorRequest:
    return AuditorRequest(
        dispatch_plan=_dispatch_plan(),
        policy_context=(
            "[C1] Statute: legal review is required before a charge decision.\n"
            "[C2] Lease: owner pays for normal wear and tear.\n"
            "[C3] SOP: manager review is required for uncertain responsibility."
        ),
        policy_claims=claims
        or (
            _claim(
                "statute-charge",
                Authority.STATUTE,
                "legal_review_required",
                "[C1]",
            ),
            _claim("lease-charge", Authority.LEASE, "owner_pays", "[C2]"),
            _claim(
                "sop-responsibility",
                Authority.INTERNAL_SOP,
                "manager_review_required",
                "[C3]",
                policy_key="responsibility",
            ),
        ),
    )


def _assessment(
    *, verdict: AuditFindingVerdict = AuditFindingVerdict.COMPLIANT
) -> PolicyAuditAssessment:
    return PolicyAuditAssessment(
        findings=(
            PolicyAuditFinding(
                policy_key="maintenance_charge",
                verdict=verdict,
                rationale="The proposal does not assign a charge.",
                provenance_ids=("[C1]",),
            ),
            PolicyAuditFinding(
                policy_key="responsibility",
                verdict=verdict,
                rationale="The proposal leaves responsibility undetermined.",
                provenance_ids=("[C3]",),
            ),
        )
    )


@pytest.mark.asyncio
async def test_auditor_receives_only_the_dispatch_plan_and_resolved_policy() -> None:
    gateway = _AuditorGateway(_assessment())

    result = await audit_dispatch(_request(), gateway=gateway)

    assert result.status is PolicyAuditStatus.COMPLIANT
    assert result.assessment == _assessment()
    assert result.policy_resolutions[0].policy_key == "maintenance_charge"
    assert result.policy_resolutions[0].controlling_authority is Authority.STATUTE
    assert gateway.calls[0][0] is TaskClass.POLICY_AUDIT
    assert gateway.calls[0][2] is PolicyAuditAssessment
    dynamic_prompt = gateway.calls[0][1].dynamic_suffix
    assert "Assess the reported kitchen drain backup" in dynamic_prompt
    assert "legal_review_required" in dynamic_prompt
    assert "likely_cause" not in dynamic_prompt
    assert "cannot create a work order" in gateway.calls[0][1].static_prefix


@pytest.mark.asyncio
async def test_auditor_returns_a_conflict_when_cited_policy_rejects_the_plan() -> None:
    gateway = _AuditorGateway(_assessment(verdict=AuditFindingVerdict.CONFLICT))

    result = await audit_dispatch(_request(), gateway=gateway)

    assert result.status is PolicyAuditStatus.CONFLICT
    assert result.failure_kind is None
    assert result.assessment is not None


@pytest.mark.asyncio
async def test_unresolved_same_rank_precedence_stops_before_the_model() -> None:
    conflicting_claims = (
        _claim("statute-a", Authority.STATUTE, "owner_pays", "[C1]"),
        _claim("statute-b", Authority.STATUTE, "resident_pays", "[C2]"),
    )
    gateway = _AuditorGateway(_assessment())

    result = await audit_dispatch(_request(claims=conflicting_claims), gateway=gateway)

    assert result.status is PolicyAuditStatus.HUMAN_REVIEW_REQUIRED
    assert result.failure_kind is PolicyAuditFailureKind.UNRESOLVED_PRECEDENCE
    assert result.assessment is None
    assert gateway.calls == []


@pytest.mark.asyncio
async def test_auditor_withholds_unsupported_citations_or_incomplete_policy_findings() -> (
    None
):
    bad_citation = _assessment().model_copy(
        update={
            "findings": (
                PolicyAuditFinding(
                    policy_key="maintenance_charge",
                    verdict=AuditFindingVerdict.COMPLIANT,
                    rationale="A charge is not assigned.",
                    provenance_ids=("[C99]",),
                ),
                PolicyAuditFinding(
                    policy_key="responsibility",
                    verdict=AuditFindingVerdict.COMPLIANT,
                    rationale="Responsibility is not assigned.",
                    provenance_ids=("[C3]",),
                ),
            )
        }
    )
    unknown = _assessment().model_copy(
        update={
            "findings": (
                PolicyAuditFinding(
                    policy_key="maintenance_charge",
                    verdict=AuditFindingVerdict.UNKNOWN,
                    rationale="The applicable charge clause is incomplete.",
                    provenance_ids=("[C1]",),
                ),
                PolicyAuditFinding(
                    policy_key="responsibility",
                    verdict=AuditFindingVerdict.COMPLIANT,
                    rationale="Responsibility is not assigned.",
                    provenance_ids=("[C3]",),
                ),
            )
        }
    )

    bad_citation_result = await audit_dispatch(
        _request(), gateway=_AuditorGateway(bad_citation)
    )
    unknown_result = await audit_dispatch(_request(), gateway=_AuditorGateway(unknown))

    assert (
        bad_citation_result.failure_kind is PolicyAuditFailureKind.UNSUPPORTED_CITATION
    )
    assert unknown_result.status is PolicyAuditStatus.HUMAN_REVIEW_REQUIRED
    assert unknown_result.failure_kind is PolicyAuditFailureKind.INSUFFICIENT_POLICY
    assert unknown_result.assessment == unknown


@pytest.mark.asyncio
async def test_auditor_routes_schema_provider_and_policy_key_failures_to_human_review() -> (
    None
):
    schema_gateway = _AuditorGateway(
        SchemaValidationError(
            "schema invalid",
            response_text='{"findings":42}',
            validation_errors=(),
        )
    )
    provider_gateway = _AuditorGateway(GatewayError("gateway unavailable"))
    mismatch_gateway = _AuditorGateway(
        PolicyAuditAssessment(
            findings=(
                PolicyAuditFinding(
                    policy_key="not_requested",
                    verdict=AuditFindingVerdict.COMPLIANT,
                    rationale="This is not an expected policy key.",
                    provenance_ids=("[C1]",),
                ),
            )
        )
    )

    schema_result = await audit_dispatch(_request(), gateway=schema_gateway)
    provider_result = await audit_dispatch(_request(), gateway=provider_gateway)
    mismatch_result = await audit_dispatch(_request(), gateway=mismatch_gateway)

    assert schema_result.failure_kind is PolicyAuditFailureKind.SCHEMA_VALIDATION
    assert provider_result.failure_kind is PolicyAuditFailureKind.PROVIDER_UNAVAILABLE
    assert mismatch_result.failure_kind is PolicyAuditFailureKind.POLICY_KEY_MISMATCH


def test_auditor_rejects_vendor_contracts_and_unprovenanced_policy_inputs() -> None:
    with pytest.raises(ValueError, match="statute, lease, or internal_sop"):
        _request(
            claims=(
                _claim(
                    "vendor-only",
                    Authority.VENDOR_CONTRACT,
                    "vendor_pays",
                    "[C1]",
                ),
            )
        )
    with pytest.raises(ValueError, match="must appear"):
        AuditorRequest(
            dispatch_plan=_dispatch_plan(),
            policy_context="[C1] Statute evidence only.",
            policy_claims=(_claim("lease", Authority.LEASE, "owner_pays", "[C2]"),),
        )
    with pytest.raises(ValueError, match="bracketed C or F"):
        PolicyAuditFinding(
            policy_key="charge",
            verdict=AuditFindingVerdict.COMPLIANT,
            rationale="No charge is assigned.",
            provenance_ids=cast(tuple[str, ...], ("C1",)),
        )
