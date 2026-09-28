"""PII detection and redaction at the model-input boundary.

Regex rules cover the regulated shapes that must work without external model
assets. Presidio augments those deterministic rules when its local NLP engine is
available. Both detectors return positions only; the original value is never
included in a finding, audit result, exception, or log message.
"""

from __future__ import annotations

import hashlib
import importlib.util
import logging
import re
from collections.abc import Sequence
from dataclasses import dataclass, field
from enum import Enum
from typing import Final, Protocol, cast

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


MAX_REDACTION_INPUT_LENGTH: Final = 50_000
_LOGGER = logging.getLogger(__name__)
_SSN_PATTERN: Final = re.compile(
    r"(?<!\d)(?!000|666|9\d{2})\d{3}[- ]?(?!00)\d{2}[- ]?(?!0000)\d{4}(?!\d)"
)
_CARD_CANDIDATE_PATTERN: Final = re.compile(r"(?<!\d)(?:\d[ -]?){12,18}\d(?!\d)")
_PHONE_PATTERN: Final = re.compile(
    r"(?<![\w+])(?:\+?1[-.\s]?)?(?:\(?[2-9]\d{2}\)?[-.\s]?)\d{3}[-.\s]\d{4}(?!\w)"
)
_EMAIL_PATTERN: Final = re.compile(
    r"(?<![\w.+-])[A-Z0-9][A-Z0-9._%+-]{0,63}@[A-Z0-9-]+(?:\.[A-Z0-9-]+)+(?![\w.-])",
    re.IGNORECASE,
)
_DOB_PATTERN: Final = re.compile(
    r"\b(?:date\s+of\s+birth|dob|birth(?:date)?|born)\s*"
    r"(?:(?::|is)\s*)?(?P<date>"
    r"(?:0?[1-9]|1[0-2])[/-](?:0?[1-9]|[12]\d|3[01])[/-](?:18|19|20)\d{2}"
    r"|(?:18|19|20)\d{2}-(?:0[1-9]|1[0-2])-(?:0[1-9]|[12]\d|3[01])"
    r"|(?:jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|"
    r"jul(?:y)?|aug(?:ust)?|sep(?:t(?:ember)?)?|oct(?:ober)?|nov(?:ember)?|"
    r"dec(?:ember)?)\s+(?:0?[1-9]|[12]\d|3[01]),?\s+(?:18|19|20)\d{2})\b",
    re.IGNORECASE,
)


class PiiKind(str, Enum):
    """Sensitive identifier classes removed before prompt construction."""

    SSN = "ssn"
    CREDIT_CARD = "credit_card"
    PHONE = "phone"
    EMAIL = "email"
    DATE_OF_BIRTH = "date_of_birth"


class PiiDetector(str, Enum):
    """Detector that contributed a redaction span."""

    REGEX = "regex"
    PRESIDIO = "presidio"


class PiiFinding(BaseModel):
    """A content-free matched span used to explain a redaction."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    kind: PiiKind
    start: int = Field(ge=0)
    end: int = Field(gt=0)
    detector: PiiDetector

    @model_validator(mode="after")
    def _validate_span(self) -> PiiFinding:
        if self.end <= self.start:
            raise ValueError("PII finding end must follow start")
        return self


class RedactionResult(BaseModel):
    """Redacted text and safe operational metadata for one transient input."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    redacted_text: str = Field(min_length=1, max_length=MAX_REDACTION_INPUT_LENGTH)
    input_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    findings: tuple[PiiFinding, ...]
    presidio_degraded: bool = False

    @field_validator("redacted_text")
    @classmethod
    def _require_non_blank_redaction(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("redacted_text must be non-blank")
        return value


@dataclass(frozen=True, slots=True)
class PresidioMatch:
    """The minimal, content-free result returned by a Presidio adapter."""

    entity_type: str
    start: int
    end: int
    score: float


class PiiAnalyzer(Protocol):
    """Optional semantic detector that augments the mandatory regex rules."""

    def analyze(self, text: str) -> Sequence[PresidioMatch]:
        """Return PII spans without retaining or logging ``text``."""


class _PresidioEngine(Protocol):
    def analyze(
        self,
        *,
        text: str,
        entities: Sequence[str],
        language: str,
    ) -> Sequence[object]:
        """Match the narrow Presidio engine operation this module uses."""


@dataclass(slots=True)
class PresidioAnalyzer:
    """Lazy adapter around the pinned ``presidio-analyzer`` dependency.

    Some local/CI environments intentionally omit Presidio's large spaCy model.
    In that case the caller falls back to the deterministic regex boundary rather
    than allowing PII through or failing the maintenance request.
    """

    _engine: _PresidioEngine | None = None
    _initialization_error: BaseException | None = field(default=None, init=False)

    def analyze(self, text: str) -> Sequence[PresidioMatch]:
        engine = self._get_engine()
        raw_matches = engine.analyze(
            text=text,
            entities=["US_SSN", "CREDIT_CARD", "PHONE_NUMBER", "EMAIL_ADDRESS"],
            language="en",
        )
        matches: list[PresidioMatch] = []
        for match in raw_matches:
            entity_type = getattr(match, "entity_type", None)
            start = getattr(match, "start", None)
            end = getattr(match, "end", None)
            score = getattr(match, "score", None)
            if (
                isinstance(entity_type, str)
                and isinstance(start, int)
                and isinstance(end, int)
                and isinstance(score, (int, float))
            ):
                matches.append(
                    PresidioMatch(
                        entity_type=entity_type,
                        start=start,
                        end=end,
                        score=float(score),
                    )
                )
        return tuple(matches)

    def _get_engine(self) -> _PresidioEngine:
        if self._engine is not None:
            return self._engine
        if self._initialization_error is not None:
            raise RuntimeError(
                "Presidio analyzer is unavailable"
            ) from self._initialization_error
        try:
            # ``AnalyzerEngine`` otherwise attempts an implicit model download
            # when its spaCy asset is missing. Prompt assembly must not add
            # network I/O, mutable dependencies, or request latency, so a
            # deployment supplies this optional model in its immutable image.
            if importlib.util.find_spec("en_core_web_lg") is None:
                raise RuntimeError("Presidio spaCy model is not installed")
            from presidio_analyzer import AnalyzerEngine

            self._engine = cast(_PresidioEngine, AnalyzerEngine())
        except Exception as error:
            self._initialization_error = error
            raise RuntimeError("Presidio analyzer is unavailable") from error
        return self._engine


_DEFAULT_PRESIDIO_ANALYZER: Final[PresidioAnalyzer] = PresidioAnalyzer()
_PRESIDIO_KIND_MAP: Final[dict[str, PiiKind]] = {
    "US_SSN": PiiKind.SSN,
    "CREDIT_CARD": PiiKind.CREDIT_CARD,
    "PHONE_NUMBER": PiiKind.PHONE,
    "EMAIL_ADDRESS": PiiKind.EMAIL,
}


def redact_pii(text: str, *, analyzer: PiiAnalyzer | None = None) -> RedactionResult:
    """Redact PII before a string can be inserted into a model prompt.

    The mandatory regex pass runs whether or not Presidio succeeds. The analyzer
    is therefore an additive detector, never the sole privacy control. Its safe
    degradation is logged with only the input SHA-256 digest.
    """

    _require_text(text)
    digest = input_digest(text)
    findings = list(_regex_findings(text))
    active_analyzer = analyzer if analyzer is not None else _DEFAULT_PRESIDIO_ANALYZER
    presidio_degraded = False
    try:
        findings.extend(_presidio_findings(text, active_analyzer))
    except Exception:
        presidio_degraded = True
        _LOGGER.warning("pii_analyzer_degraded input_digest=%s", digest)

    selected = _non_overlapping_findings(findings)
    return RedactionResult(
        redacted_text=_apply_redactions(text, selected),
        input_digest=digest,
        findings=selected,
        presidio_degraded=presidio_degraded,
    )


def input_digest(text: str) -> str:
    """Return the SHA-256 value safe to store in ``agent_steps.input_digest``."""

    _require_text(text)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _regex_findings(text: str) -> tuple[PiiFinding, ...]:
    findings: list[PiiFinding] = []
    findings.extend(_find_matches(PiiKind.SSN, _SSN_PATTERN, text))
    findings.extend(_card_findings(text))
    findings.extend(_find_matches(PiiKind.PHONE, _PHONE_PATTERN, text))
    findings.extend(_find_matches(PiiKind.EMAIL, _EMAIL_PATTERN, text))
    for match in _DOB_PATTERN.finditer(text):
        findings.append(
            PiiFinding(
                kind=PiiKind.DATE_OF_BIRTH,
                start=match.start("date"),
                end=match.end("date"),
                detector=PiiDetector.REGEX,
            )
        )
    return tuple(findings)


def _find_matches(
    kind: PiiKind, expression: re.Pattern[str], text: str
) -> tuple[PiiFinding, ...]:
    return tuple(
        PiiFinding(
            kind=kind,
            start=match.start(),
            end=match.end(),
            detector=PiiDetector.REGEX,
        )
        for match in expression.finditer(text)
    )


def _card_findings(text: str) -> tuple[PiiFinding, ...]:
    findings: list[PiiFinding] = []
    for match in _CARD_CANDIDATE_PATTERN.finditer(text):
        digits = re.sub(r"[ -]", "", match.group())
        if _passes_luhn(digits):
            findings.append(
                PiiFinding(
                    kind=PiiKind.CREDIT_CARD,
                    start=match.start(),
                    end=match.end(),
                    detector=PiiDetector.REGEX,
                )
            )
    return tuple(findings)


def _passes_luhn(digits: str) -> bool:
    if not 13 <= len(digits) <= 19 or not digits.isascii() or not digits.isdigit():
        return False
    total = 0
    for index, char in enumerate(reversed(digits)):
        value = int(char)
        if index % 2:
            value *= 2
            if value > 9:
                value -= 9
        total += value
    return total % 10 == 0


def _presidio_findings(text: str, analyzer: PiiAnalyzer) -> tuple[PiiFinding, ...]:
    findings: list[PiiFinding] = []
    for match in analyzer.analyze(text):
        kind = _PRESIDIO_KIND_MAP.get(match.entity_type)
        if kind is None or match.score < 0.5:
            continue
        if not (0 <= match.start < match.end <= len(text)):
            continue
        findings.append(
            PiiFinding(
                kind=kind,
                start=match.start,
                end=match.end,
                detector=PiiDetector.PRESIDIO,
            )
        )
    return tuple(findings)


def _non_overlapping_findings(
    findings: Sequence[PiiFinding],
) -> tuple[PiiFinding, ...]:
    """Select a stable non-overlapping set, preferring regex on exact ties."""

    selected: list[PiiFinding] = []
    for finding in sorted(
        findings,
        key=lambda item: (
            item.start,
            -(item.end - item.start),
            0 if item.detector is PiiDetector.REGEX else 1,
            item.kind.value,
        ),
    ):
        if selected and finding.start < selected[-1].end:
            continue
        selected.append(finding)
    return tuple(selected)


def _apply_redactions(text: str, findings: Sequence[PiiFinding]) -> str:
    redacted = text
    for finding in reversed(findings):
        replacement = f"[REDACTED:{finding.kind.value.upper()}]"
        redacted = redacted[: finding.start] + replacement + redacted[finding.end :]
    return redacted


def _require_text(text: str) -> None:
    if not isinstance(text, str) or not text.strip():
        raise ValueError("PII redaction input must be a non-blank string")
    if len(text) > MAX_REDACTION_INPUT_LENGTH:
        raise ValueError(
            f"PII redaction input must not exceed {MAX_REDACTION_INPUT_LENGTH} characters"
        )
