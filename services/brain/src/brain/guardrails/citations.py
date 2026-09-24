"""Deterministic citation verification with one bounded regeneration attempt.

The verifier checks only literal, auditable properties: citation IDs must come
from the supplied envelope, and every numeric, date, currency, or section claim
must carry a known citation whose source text contains that exact figure.  It
does not judge whether a diagnosis is generally sensible.  A failed candidate
gets one targeted repair request; a second failure is withheld for human review.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from enum import Enum
from typing import Final, Protocol

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from brain.context.envelope import ContextEnvelope, ProvenanceRecord
from brain.gateway.client import (
    RenderedPrompt,
    SchemaValidationError,
    TaskClass,
    load_builtin_prompt,
)


MAX_CANDIDATE_TEXT_LENGTH: Final = 50_000
_CITATION_PATTERN: Final = re.compile(r"\[(?:C|F)[1-9]\d*\]")
_FIGURE_PATTERN: Final = re.compile(
    r"(?:"
    r"[$€£]\s?\d+(?:,\d{3})*(?:\.\d{2})?"
    r"|§\s*\d+(?:\.\d+)*"
    r"|\b\d{4}-\d{1,2}-\d{1,2}\b"
    r"|\b\d{1,2}[/-]\d{1,2}[/-]\d{2,4}\b"
    r"|\b(?:jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|"
    r"jun(?:e)?|jul(?:y)?|aug(?:ust)?|sep(?:t(?:ember)?)?|oct(?:ober)?|"
    r"nov(?:ember)?|dec(?:ember)?)\s+\d{1,2}(?:,\s*\d{4})?\b"
    r"|(?<![A-Za-z])\d+(?:,\d{3})*(?:\.\d+)?%?"
    r")",
    re.IGNORECASE,
)
_SENTENCE_CLOSERS: Final = frozenset("\"'”’)]}")
_ABBREVIATIONS: Final = frozenset(
    {
        "approx.",
        "dr.",
        "e.g.",
        "etc.",
        "fig.",
        "i.e.",
        "mr.",
        "mrs.",
        "ms.",
        "no.",
        "prof.",
        "u.s.",
    }
)


class CitationViolationKind(str, Enum):
    """The deterministic reasons a candidate cannot be released."""

    UNKNOWN_CITATION = "unknown_citation"
    MISSING_CITATION = "missing_citation"
    UNSUPPORTED_FIGURE = "unsupported_figure"


class CitationGuardStatus(str, Enum):
    """Whether the text passed verification or requires human review."""

    VERIFIED = "verified"
    HUMAN_REVIEW_REQUIRED = "human_review_required"


class CitationGuardFailureKind(str, Enum):
    """Terminal failure after the single permitted logical repair attempt."""

    REPAIR_SCHEMA_VALIDATION = "repair_schema_validation"
    REPAIR_PROVIDER_UNAVAILABLE = "repair_provider_unavailable"
    REPAIR_STILL_INVALID = "repair_still_invalid"


class CitationViolation(BaseModel):
    """One claim-level failure, suitable for a targeted repair prompt or review."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    kind: CitationViolationKind
    sentence_index: int = Field(ge=1)
    claim: str = Field(min_length=1, max_length=MAX_CANDIDATE_TEXT_LENGTH)
    citation_id: str | None = None
    figure: str | None = None

    @field_validator("claim")
    @classmethod
    def _require_non_blank_claim(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("claim must be non-blank")
        return value

    @model_validator(mode="after")
    def _validate_kind_specific_fields(self) -> CitationViolation:
        if self.kind is CitationViolationKind.UNKNOWN_CITATION:
            if self.citation_id is None or self.figure is not None:
                raise ValueError("unknown citations require only citation_id")
        elif self.kind is CitationViolationKind.MISSING_CITATION:
            if self.citation_id is not None or self.figure is None:
                raise ValueError("missing citations require only figure")
        elif self.citation_id is None or self.figure is None:
            raise ValueError("unsupported figures require citation_id and figure")
        return self


class CitationVerification(BaseModel):
    """The immutable deterministic verdict over a candidate text and envelope."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    valid: bool
    violations: tuple[CitationViolation, ...]

    @model_validator(mode="after")
    def _validate_consistency(self) -> CitationVerification:
        if self.valid != (not self.violations):
            raise ValueError("valid must match whether violations are empty")
        return self


class CitationRegeneration(BaseModel):
    """Strict output contract for the single targeted citation repair."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    revised_text: str = Field(min_length=1, max_length=MAX_CANDIDATE_TEXT_LENGTH)

    @field_validator("revised_text")
    @classmethod
    def _require_non_blank_revised_text(cls, value: str) -> str:
        _require_candidate_text(value)
        return value


class CitationGuardResult(BaseModel):
    """A verified text or a hard stop carrying specific review failures."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    status: CitationGuardStatus
    safe_text: str | None
    verification: CitationVerification
    regeneration_attempted: bool
    failure_kind: CitationGuardFailureKind | None = None

    @model_validator(mode="after")
    def _enforce_terminal_state(self) -> CitationGuardResult:
        if self.status is CitationGuardStatus.VERIFIED:
            if (
                self.safe_text is None
                or not self.verification.valid
                or self.failure_kind is not None
            ):
                raise ValueError("verified output requires safe text and no failure")
        elif (
            self.safe_text is not None
            or self.verification.valid
            or self.failure_kind is None
        ):
            raise ValueError("review-required output must withhold invalid text")
        return self


class CitationRepairGateway(Protocol):
    """The only external capability used after a deterministic citation failure."""

    async def complete(
        self,
        task: TaskClass,
        prompt: RenderedPrompt,
        schema: type[CitationRegeneration],
    ) -> CitationRegeneration:
        """Return one schema-validated targeted regeneration through the gateway."""


@dataclass(frozen=True, slots=True)
class _Sentence:
    """One generated sentence or list line, preserved for deterministic checks."""

    index: int
    text: str


def verify_citations(
    candidate_text: str,
    *,
    envelope: ContextEnvelope,
) -> CitationVerification:
    """Verify citation membership and exact support for numeric material claims.

    A numeric figure is supported when it appears as an exact substring in at
    least one provenance record named by that sentence.  The check deliberately
    does not normalize currency, commas, decimal places, or section formatting:
    doing so would turn a precise evidence check into an inference engine.
    """

    _require_candidate_text(candidate_text)
    records = _records_by_id(envelope)
    violations: list[CitationViolation] = []
    for sentence in _sentences(candidate_text):
        citations = tuple(_CITATION_PATTERN.findall(sentence.text))
        known_citations = tuple(
            citation for citation in citations if citation in records
        )
        for citation in citations:
            if citation not in records:
                violations.append(
                    CitationViolation(
                        kind=CitationViolationKind.UNKNOWN_CITATION,
                        sentence_index=sentence.index,
                        claim=sentence.text,
                        citation_id=citation,
                    )
                )

        for figure in _figures(sentence.text):
            if not citations:
                violations.append(
                    CitationViolation(
                        kind=CitationViolationKind.MISSING_CITATION,
                        sentence_index=sentence.index,
                        claim=sentence.text,
                        figure=figure,
                    )
                )
            elif not any(
                figure in records[citation].text for citation in known_citations
            ):
                violations.append(
                    CitationViolation(
                        kind=CitationViolationKind.UNSUPPORTED_FIGURE,
                        sentence_index=sentence.index,
                        claim=sentence.text,
                        citation_id=(
                            known_citations[0] if known_citations else citations[0]
                        ),
                        figure=figure,
                    )
                )
    return CitationVerification(valid=not violations, violations=tuple(violations))


async def verify_and_repair_citations(
    candidate_text: str,
    *,
    envelope: ContextEnvelope,
    gateway: CitationRepairGateway,
) -> CitationGuardResult:
    """Verify a candidate, perform exactly one targeted repair, then fail closed.

    The candidate is released without a model call when it passes deterministic
    verification.  Otherwise this calls the gateway once with the precise claim
    failures.  A failed repair is intentionally not retried or silently
    corrected; a human must decide how to proceed.
    """

    initial_verification = verify_citations(candidate_text, envelope=envelope)
    if initial_verification.valid:
        return CitationGuardResult(
            status=CitationGuardStatus.VERIFIED,
            safe_text=candidate_text,
            verification=initial_verification,
            regeneration_attempted=False,
        )

    prompt = _render_repair_prompt(
        candidate_text=candidate_text,
        envelope=envelope,
        verification=initial_verification,
    )
    try:
        regeneration = await gateway.complete(
            TaskClass.CITATION_REPAIR,
            prompt,
            CitationRegeneration,
        )
    except SchemaValidationError:
        return _human_review(
            verification=initial_verification,
            failure_kind=CitationGuardFailureKind.REPAIR_SCHEMA_VALIDATION,
        )
    except Exception:
        return _human_review(
            verification=initial_verification,
            failure_kind=CitationGuardFailureKind.REPAIR_PROVIDER_UNAVAILABLE,
        )

    repaired_verification = verify_citations(
        regeneration.revised_text,
        envelope=envelope,
    )
    if not repaired_verification.valid:
        return _human_review(
            verification=repaired_verification,
            failure_kind=CitationGuardFailureKind.REPAIR_STILL_INVALID,
        )
    return CitationGuardResult(
        status=CitationGuardStatus.VERIFIED,
        safe_text=regeneration.revised_text,
        verification=repaired_verification,
        regeneration_attempted=True,
    )


def _render_repair_prompt(
    *,
    candidate_text: str,
    envelope: ContextEnvelope,
    verification: CitationVerification,
) -> RenderedPrompt:
    return load_builtin_prompt("citation-repair").render(
        {
            "candidate_text": candidate_text,
            "envelope": envelope.render(),
            "violations_json": json.dumps(
                [
                    violation.model_dump(mode="json")
                    for violation in verification.violations
                ],
                ensure_ascii=True,
                separators=(",", ":"),
                sort_keys=True,
            ),
        },
        schema=CitationRegeneration,
    )


def _human_review(
    *,
    verification: CitationVerification,
    failure_kind: CitationGuardFailureKind,
) -> CitationGuardResult:
    return CitationGuardResult(
        status=CitationGuardStatus.HUMAN_REVIEW_REQUIRED,
        safe_text=None,
        verification=verification,
        regeneration_attempted=True,
        failure_kind=failure_kind,
    )


def _records_by_id(envelope: ContextEnvelope) -> dict[str, ProvenanceRecord]:
    records = (*envelope.citations, *envelope.facts)
    return {record.provenance_id: record for record in records}


def _sentences(candidate_text: str) -> tuple[_Sentence, ...]:
    """Split prose and Markdown list lines without detaching trailing citations."""

    sentences: list[_Sentence] = []
    for line in candidate_text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        sentences.extend(_line_sentences(stripped, start_index=len(sentences) + 1))
    return tuple(sentences)


def _line_sentences(line: str, *, start_index: int) -> tuple[_Sentence, ...]:
    sentences: list[_Sentence] = []
    start = 0
    position = 0
    while position < len(line):
        if line[position] in ".!?" and _is_sentence_boundary(line, position):
            end = _sentence_end_after_closers(line, position)
            end = _consume_trailing_citations(line, end)
            sentence = line[start:end].strip()
            if sentence:
                sentences.append(
                    _Sentence(index=start_index + len(sentences), text=sentence)
                )
            start = _skip_whitespace(line, end)
            position = start
            continue
        position += 1
    trailing = line[start:].strip()
    if trailing:
        sentences.append(_Sentence(index=start_index + len(sentences), text=trailing))
    return tuple(sentences)


def _is_sentence_boundary(text: str, position: int) -> bool:
    if text[position] == ".":
        if (
            position > 0
            and position + 1 < len(text)
            and text[position - 1].isdigit()
            and text[position + 1].isdigit()
        ):
            return False
        token_start = position
        while token_start > 0 and not text[token_start - 1].isspace():
            token_start -= 1
        if text[token_start : position + 1].casefold() in _ABBREVIATIONS:
            return False
    end = _sentence_end_after_closers(text, position)
    return end == len(text) or text[end].isspace()


def _sentence_end_after_closers(text: str, position: int) -> int:
    end = position + 1
    while end < len(text) and text[end] in _SENTENCE_CLOSERS:
        end += 1
    return end


def _consume_trailing_citations(text: str, position: int) -> int:
    cursor = position
    while True:
        whitespace_end = _skip_whitespace(text, cursor)
        match = _CITATION_PATTERN.match(text, whitespace_end)
        if match is None:
            return cursor
        cursor = match.end()


def _skip_whitespace(text: str, position: int) -> int:
    while position < len(text) and text[position].isspace():
        position += 1
    return position


def _figures(text: str) -> tuple[str, ...]:
    return tuple(match.group(0) for match in _FIGURE_PATTERN.finditer(text))


def _require_candidate_text(value: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("candidate_text must be a non-blank string")
    if len(value) > MAX_CANDIDATE_TEXT_LENGTH:
        raise ValueError(
            f"candidate_text must not exceed {MAX_CANDIDATE_TEXT_LENGTH} characters"
        )
