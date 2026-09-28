from __future__ import annotations

import hashlib

import pytest

from brain.guardrails.pii import (
    MAX_REDACTION_INPUT_LENGTH,
    PiiKind,
    PresidioMatch,
    redact_pii,
)


class _Analyzer:
    def __init__(self, matches: tuple[PresidioMatch, ...] = ()) -> None:
        self.matches = matches
        self.calls: list[str] = []

    def analyze(self, text: str) -> tuple[PresidioMatch, ...]:
        self.calls.append(text)
        return self.matches


class _UnavailableAnalyzer:
    def analyze(self, text: str) -> tuple[PresidioMatch, ...]:
        del text
        raise RuntimeError("unavailable")


def test_regex_redacts_required_pii_classes_and_returns_only_safe_metadata() -> None:
    raw = (
        "SSN 123-45-6789; card 4111 1111 1111 1111; call (415) 555-2671; "
        "email maya@example.com; DOB: 01/02/1990."
    )

    result = redact_pii(raw, analyzer=_Analyzer())

    assert result.input_digest == hashlib.sha256(raw.encode("utf-8")).hexdigest()
    assert {finding.kind for finding in result.findings} == {
        PiiKind.SSN,
        PiiKind.CREDIT_CARD,
        PiiKind.PHONE,
        PiiKind.EMAIL,
        PiiKind.DATE_OF_BIRTH,
    }
    assert "123-45-6789" not in result.redacted_text
    assert "4111 1111 1111 1111" not in result.redacted_text
    assert "(415) 555-2671" not in result.redacted_text
    assert "maya@example.com" not in result.redacted_text
    assert "01/02/1990" not in result.redacted_text
    assert "[REDACTED:SSN]" in result.redacted_text
    assert "[REDACTED:CREDIT_CARD]" in result.redacted_text
    assert "[REDACTED:PHONE]" in result.redacted_text
    assert "[REDACTED:EMAIL]" in result.redacted_text
    assert "[REDACTED:DATE_OF_BIRTH]" in result.redacted_text


def test_presidio_augments_the_regex_boundary_for_additional_shapes() -> None:
    raw = "The contact number is 4155552671."
    start = raw.index("4155552671")
    analyzer = _Analyzer(
        (
            PresidioMatch(
                entity_type="PHONE_NUMBER",
                start=start,
                end=start + len("4155552671"),
                score=0.91,
            ),
        )
    )

    result = redact_pii(raw, analyzer=analyzer)

    assert analyzer.calls == [raw]
    assert [finding.kind for finding in result.findings] == [PiiKind.PHONE]
    assert "4155552671" not in result.redacted_text
    assert result.presidio_degraded is False


def test_presidio_failure_degrades_to_regex_without_exposing_input(
    caplog: pytest.LogCaptureFixture,
) -> None:
    raw = "Please contact maya@example.com"

    result = redact_pii(raw, analyzer=_UnavailableAnalyzer())

    assert result.presidio_degraded is True
    assert result.findings[0].kind is PiiKind.EMAIL
    assert "maya@example.com" not in caplog.text
    assert result.input_digest in caplog.text


def test_redaction_rejects_empty_or_excessive_input() -> None:
    with pytest.raises(ValueError, match="non-blank"):
        redact_pii(" ", analyzer=_Analyzer())
    with pytest.raises(ValueError, match="must not exceed"):
        redact_pii("x" * (MAX_REDACTION_INPUT_LENGTH + 1), analyzer=_Analyzer())
