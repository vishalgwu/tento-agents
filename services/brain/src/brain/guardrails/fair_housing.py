"""Deterministic fair-housing screening for resident-facing draft output.

This is a pre-send filter, not a writing assistant: it returns a digest-only
assessment and a human-review route, but never mutates or rewrites the draft.
The patterns intentionally catch only explicit discriminatory advertising,
steering, protected-class treatment, and accommodation denial. They are a
safety net for generated communications, not a legal determination.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from enum import Enum
from typing import Final

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


MAX_DRAFT_LENGTH: Final = 20_000
FAIR_HOUSING_RULE_VERSION: Final = "fair-housing-v1"
_SAFE_IDENTIFIER_PATTERN: Final = re.compile(r"^[a-z][a-z0-9_]{0,79}$")
_RULE_VERSION_PATTERN: Final = re.compile(r"^[a-z][a-z0-9._-]{0,79}$")
_SENTENCE_BOUNDARY: Final = re.compile(r"[.!?\n]+")
_NON_DISCRIMINATION_STATEMENT: Final = re.compile(
    r"\b(?:do\s+not|don't|cannot|can't|will\s+not|won't)\s+"
    r"(?:discriminate|deny|refuse|exclude)\b",
    re.IGNORECASE,
)
_RESTRICTIVE_LANGUAGE: Final = re.compile(
    r"\b(?:do\s+not|don't|cannot|can't|will\s+not|won't|only|exclude|avoid|"
    r"deny|reject|refuse|prefer|not\s+suitable|not\s+eligible)\b",
    re.IGNORECASE,
)
_HOUSING_DECISION_LANGUAGE: Final = re.compile(
    r"\b(?:rent|lease|application|applicant|housing|home|unit|apartment|"
    r"resident|tenant|show|showing|available|eligible|suitable)\b",
    re.IGNORECASE,
)
_STEERING_LANGUAGE: Final = re.compile(
    r"\b(?:steer|direct|send|show|move)\b.{0,100}\b"
    r"(?:elsewhere|another|different|separate)\b",
    re.IGNORECASE | re.DOTALL,
)
_ACCOMMODATION_DENIAL: Final = re.compile(
    r"\b(?:cannot|can't|will\s+not|won't|do\s+not|don't|refuse|deny|decline)\b"
    r".{0,100}\b(?:reasonable\s+accommodation|(?:service|assistance)\s+animal|"
    r"wheelchair\s+(?:access|ramp)|accessibility\s+modification)\b",
    re.IGNORECASE | re.DOTALL,
)


class FairHousingOutcome(str, Enum):
    """The terminal result of screening a drafted communication."""

    PASSED = "passed"
    BLOCKED = "blocked"


class FairHousingRoute(str, Enum):
    """The only safe next step after the output screen."""

    CONTINUE = "continue"
    HUMAN_REVIEW = "human_review"


class FairHousingFindingSource(str, Enum):
    """Whether a deterministic blocklist or intent rule produced the finding."""

    TERM_BLOCKLIST = "term_blocklist"
    INTENT_CLASSIFIER = "intent_classifier"


class FairHousingRisk(str, Enum):
    """Narrow, review-oriented categories for potentially discriminatory output."""

    DISCRIMINATORY_ADVERTISING = "discriminatory_advertising"
    PROTECTED_CLASS_TREATMENT = "protected_class_treatment"
    STEERING = "steering"
    ACCOMMODATION_DENIAL = "accommodation_denial"
    SOURCE_OF_INCOME_EXCLUSION = "source_of_income_exclusion"


class FairHousingDraft(BaseModel):
    """Transient generated text supplied to the pre-send boundary."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    content: str = Field(min_length=1, max_length=MAX_DRAFT_LENGTH, repr=False)

    @field_validator("content")
    @classmethod
    def _require_non_blank_content(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("draft content must be non-blank")
        return value

    @property
    def content_digest(self) -> str:
        """Return the safe audit reference for the original draft."""

        return hashlib.sha256(self.content.encode("utf-8")).hexdigest()


class FairHousingFinding(BaseModel):
    """A content-free explanation of one block decision."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    rule_id: str = Field(min_length=1, max_length=80)
    source: FairHousingFindingSource
    risk: FairHousingRisk

    @field_validator("rule_id")
    @classmethod
    def _validate_rule_id(cls, value: str) -> str:
        if _SAFE_IDENTIFIER_PATTERN.fullmatch(value) is None:
            raise ValueError("rule_id must be a safe stable identifier")
        return value


class FairHousingAssessment(BaseModel):
    """The only export from screening; it contains no generated draft text."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    content_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    rule_version: str = Field(min_length=1, max_length=80)
    outcome: FairHousingOutcome
    route: FairHousingRoute
    findings: tuple[FairHousingFinding, ...] = ()

    @model_validator(mode="after")
    def _require_a_consistent_routing_decision(self) -> FairHousingAssessment:
        rule_ids = tuple(finding.rule_id for finding in self.findings)
        if len(rule_ids) != len(set(rule_ids)):
            raise ValueError("fair-housing findings must not repeat a rule")
        if self.outcome is FairHousingOutcome.BLOCKED:
            if not self.findings or self.route is not FairHousingRoute.HUMAN_REVIEW:
                raise ValueError("blocked output requires findings and human review")
        elif self.findings or self.route is not FairHousingRoute.CONTINUE:
            raise ValueError("passed output cannot contain findings or require review")
        return self

    @field_validator("rule_version")
    @classmethod
    def _validate_rule_version(cls, value: str) -> str:
        if _RULE_VERSION_PATTERN.fullmatch(value) is None:
            raise ValueError("rule_version must be a safe stable identifier")
        return value


@dataclass(frozen=True, slots=True)
class _Rule:
    rule_id: str
    risk: FairHousingRisk
    expression: re.Pattern[str]


_TERM_BLOCKLIST: Final[tuple[_Rule, ...]] = (
    _Rule(
        "adults_only",
        FairHousingRisk.DISCRIMINATORY_ADVERTISING,
        re.compile(r"\badults?\s+only\b", re.IGNORECASE),
    ),
    _Rule(
        "no_children",
        FairHousingRisk.PROTECTED_CLASS_TREATMENT,
        re.compile(r"\bno\s+(?:children|kids)\b", re.IGNORECASE),
    ),
    _Rule(
        "no_vouchers",
        FairHousingRisk.SOURCE_OF_INCOME_EXCLUSION,
        re.compile(
            r"\bno\s+(?:section\s*8|housing\s+vouchers?|vouchers?)\b",
            re.IGNORECASE,
        ),
    ),
    _Rule(
        "no_assistance_animals",
        FairHousingRisk.ACCOMMODATION_DENIAL,
        re.compile(r"\bno\s+(?:service|assistance)\s+animals?\b", re.IGNORECASE),
    ),
    _Rule(
        "exclude_wheelchair_users",
        FairHousingRisk.PROTECTED_CLASS_TREATMENT,
        re.compile(
            r"\b(?:no|exclude)\s+wheelchair\s+(?:users|residents|tenants)\b",
            re.IGNORECASE,
        ),
    ),
    _Rule(
        "protected_group_only",
        FairHousingRisk.DISCRIMINATORY_ADVERTISING,
        re.compile(
            r"\b(?:white|black|asian|christian|muslim|jewish|hindu|latino|"
            r"hispanic)\s+(?:people|residents|tenants)?\s*only\b",
            re.IGNORECASE,
        ),
    ),
)
_PROTECTED_CLASS_SIGNALS: Final[tuple[re.Pattern[str], ...]] = (
    re.compile(
        r"\b(?:famil(?:y|ies)|children|kids|parents|pregnan(?:t|cy))\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:disab(?:led|ility)|wheelchair|(?:service|assistance)\s+animal|"
        r"reasonable\s+accommodation)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:race|color|religion|national(?:ity|\s+origin)|ethnic(?:ity)?|"
        r"sex|gender|sexual\s+orientation|transgender)\b",
        re.IGNORECASE,
    ),
)


def screen_fair_housing_draft(draft: FairHousingDraft) -> FairHousingAssessment:
    """Block unsafe output and route it to a human without changing the draft."""

    findings = (*_blocklist_findings(draft.content), *_intent_findings(draft.content))
    if findings:
        return FairHousingAssessment(
            content_digest=draft.content_digest,
            rule_version=FAIR_HOUSING_RULE_VERSION,
            outcome=FairHousingOutcome.BLOCKED,
            route=FairHousingRoute.HUMAN_REVIEW,
            findings=findings,
        )
    return FairHousingAssessment(
        content_digest=draft.content_digest,
        rule_version=FAIR_HOUSING_RULE_VERSION,
        outcome=FairHousingOutcome.PASSED,
        route=FairHousingRoute.CONTINUE,
    )


def _blocklist_findings(content: str) -> tuple[FairHousingFinding, ...]:
    return tuple(
        FairHousingFinding(
            rule_id=rule.rule_id,
            source=FairHousingFindingSource.TERM_BLOCKLIST,
            risk=rule.risk,
        )
        for rule in _TERM_BLOCKLIST
        if rule.expression.search(content) is not None
    )


def _intent_findings(content: str) -> tuple[FairHousingFinding, ...]:
    findings: list[FairHousingFinding] = []
    for sentence in _SENTENCE_BOUNDARY.split(content):
        if not sentence.strip() or _NON_DISCRIMINATION_STATEMENT.search(sentence):
            continue
        has_protected_signal = any(
            pattern.search(sentence) is not None for pattern in _PROTECTED_CLASS_SIGNALS
        )
        if _ACCOMMODATION_DENIAL.search(sentence) is not None:
            findings.append(
                FairHousingFinding(
                    rule_id="accommodation_denial_intent",
                    source=FairHousingFindingSource.INTENT_CLASSIFIER,
                    risk=FairHousingRisk.ACCOMMODATION_DENIAL,
                )
            )
        if has_protected_signal and _STEERING_LANGUAGE.search(sentence) is not None:
            findings.append(
                FairHousingFinding(
                    rule_id="steering_intent",
                    source=FairHousingFindingSource.INTENT_CLASSIFIER,
                    risk=FairHousingRisk.STEERING,
                )
            )
        if (
            has_protected_signal
            and _RESTRICTIVE_LANGUAGE.search(sentence) is not None
            and _HOUSING_DECISION_LANGUAGE.search(sentence) is not None
        ):
            findings.append(
                FairHousingFinding(
                    rule_id="protected_class_treatment_intent",
                    source=FairHousingFindingSource.INTENT_CLASSIFIER,
                    risk=FairHousingRisk.PROTECTED_CLASS_TREATMENT,
                )
            )
    return tuple({finding.rule_id: finding for finding in findings}.values())
