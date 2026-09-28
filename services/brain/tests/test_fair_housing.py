"""Regression tests for the no-rewrite fair-housing output boundary."""

from __future__ import annotations

import pytest

from brain.guardrails.fair_housing import (
    FairHousingAssessment,
    FairHousingDraft,
    FairHousingFindingSource,
    FairHousingOutcome,
    FairHousingRisk,
    FairHousingRoute,
    FAIR_HOUSING_RULE_VERSION,
    screen_fair_housing_draft,
)


def test_neutral_maintenance_draft_passes_without_retaining_text() -> None:
    draft = FairHousingDraft(
        content="A licensed plumber is scheduled to inspect the kitchen sink tomorrow."
    )

    assessment = screen_fair_housing_draft(draft)

    assert assessment.outcome is FairHousingOutcome.PASSED
    assert assessment.route is FairHousingRoute.CONTINUE
    assert assessment.findings == ()
    assert assessment.rule_version == FAIR_HOUSING_RULE_VERSION
    assert draft.content not in assessment.model_dump_json()


@pytest.mark.parametrize(
    ("content", "rule_id", "risk"),
    (
        (
            "This community is adults only.",
            "adults_only",
            FairHousingRisk.DISCRIMINATORY_ADVERTISING,
        ),
        (
            "No vouchers are accepted.",
            "no_vouchers",
            FairHousingRisk.SOURCE_OF_INCOME_EXCLUSION,
        ),
        (
            "No service animals are allowed.",
            "no_assistance_animals",
            FairHousingRisk.ACCOMMODATION_DENIAL,
        ),
        (
            "We exclude wheelchair users.",
            "exclude_wheelchair_users",
            FairHousingRisk.PROTECTED_CLASS_TREATMENT,
        ),
    ),
)
def test_term_blocklist_routes_output_to_human_review(
    content: str, rule_id: str, risk: FairHousingRisk
) -> None:
    assessment = screen_fair_housing_draft(FairHousingDraft(content=content))

    assert assessment.outcome is FairHousingOutcome.BLOCKED
    assert assessment.route is FairHousingRoute.HUMAN_REVIEW
    assert assessment.findings[0].rule_id == rule_id
    assert assessment.findings[0].risk is risk
    assert assessment.findings[0].source is FairHousingFindingSource.TERM_BLOCKLIST


@pytest.mark.parametrize(
    ("content", "rule_id", "risk"),
    (
        (
            "We will not approve this apartment application because the household has children.",
            "protected_class_treatment_intent",
            FairHousingRisk.PROTECTED_CLASS_TREATMENT,
        ),
        (
            "Please direct families with children to a different building.",
            "steering_intent",
            FairHousingRisk.STEERING,
        ),
        (
            "We cannot grant a reasonable accommodation for your assistance animal.",
            "accommodation_denial_intent",
            FairHousingRisk.ACCOMMODATION_DENIAL,
        ),
    ),
)
def test_intent_classifier_routes_indirect_discrimination_to_human_review(
    content: str, rule_id: str, risk: FairHousingRisk
) -> None:
    assessment = screen_fair_housing_draft(FairHousingDraft(content=content))

    finding = next(item for item in assessment.findings if item.rule_id == rule_id)
    assert assessment.route is FairHousingRoute.HUMAN_REVIEW
    assert finding.risk is risk
    assert finding.source is FairHousingFindingSource.INTENT_CLASSIFIER


def test_neutral_accommodation_and_non_discrimination_statements_are_not_rewritten() -> (
    None
):
    content = (
        "We can discuss a reasonable accommodation for your assistance animal. "
        "We do not discriminate based on disability in housing decisions."
    )

    assessment = screen_fair_housing_draft(FairHousingDraft(content=content))

    assert assessment.outcome is FairHousingOutcome.PASSED
    assert assessment.route is FairHousingRoute.CONTINUE
    assert not hasattr(assessment, "rewritten_content")


def test_models_reject_unsafe_or_inconsistent_assessments() -> None:
    with pytest.raises(ValueError, match="non-blank"):
        FairHousingDraft(content="   ")
    with pytest.raises(ValueError, match="blocked output"):
        FairHousingAssessment(
            content_digest="a" * 64,
            rule_version=FAIR_HOUSING_RULE_VERSION,
            outcome=FairHousingOutcome.BLOCKED,
            route=FairHousingRoute.CONTINUE,
        )
