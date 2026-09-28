"""Typed context assembly for untrusted model inputs.

Prompt-injection classifiers are only a signal. The enforceable control is that
every dynamic string is explicitly labelled, defaults to untrusted, and is
rejected before prompt assembly when the recipient has write-tool capability.
"""

from __future__ import annotations

import html
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from enum import Enum
from typing import Final

from brain.guardrails.pii import redact_pii


_SOURCE_PATTERN: Final = re.compile(r"^[a-z][a-z0-9_-]{0,63}$")
_PROMPT_VARIABLE_PATTERN: Final = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,127}$")


class TrustLevel(str, Enum):
    """Authority level assigned to every dynamic string in prompt context."""

    TRUSTED = "trusted"
    UNTRUSTED = "untrusted"


class AgentCapability(str, Enum):
    """Whether an agent receiving context can invoke a write-capable tool."""

    NO_WRITE_TOOLS = "no_write_tools"
    WRITE_TOOLS = "write_tools"


class PromptContextError(ValueError):
    """Context was not safe to render into a versioned model prompt."""


class PromptInjectionPattern(str, Enum):
    """Conservative injection signals carried as metadata, never authority."""

    INSTRUCTION_OVERRIDE = "instruction_override"
    ROLE_IMPERSONATION = "role_impersonation"
    SECRET_EXTRACTION = "secret_extraction"
    TOOL_INVOCATION = "tool_invocation"
    DELIMITER_ESCAPE = "delimiter_escape"


class PromptInjectionScan:
    """Content-free scanner result for one untrusted text value."""

    def __init__(self, patterns: tuple[PromptInjectionPattern, ...]) -> None:
        self.patterns = patterns

    @property
    def suspicious(self) -> bool:
        """Whether one or more advisory injection patterns matched."""

        return bool(self.patterns)


@dataclass(frozen=True, slots=True)
class ContextText:
    """One dynamic string with an explicit trust level and origin label."""

    value: str = field(repr=False)
    trust: TrustLevel
    source: str

    def __post_init__(self) -> None:
        if not isinstance(self.value, str) or not self.value.strip():
            raise PromptContextError("context text must be a non-blank string")
        if _SOURCE_PATTERN.fullmatch(self.source) is None:
            raise PromptContextError("context source must be a lowercase identifier")


@dataclass(frozen=True, slots=True)
class PromptContext:
    """A structured prompt context that is safe to render for one agent class."""

    values: Mapping[str, object]
    capability: AgentCapability = AgentCapability.NO_WRITE_TOOLS

    @classmethod
    def from_untrusted(
        cls,
        values: Mapping[str, object],
        *,
        source: str = "dynamic_input",
        capability: AgentCapability,
    ) -> PromptContext:
        """Mark all dynamic strings untrusted; this is the secure default path."""

        if _SOURCE_PATTERN.fullmatch(source) is None:
            raise PromptContextError("context source must be a lowercase identifier")
        return cls(
            values={
                key: _mark_strings(value, trust=TrustLevel.UNTRUSTED, source=source)
                for key, value in values.items()
            },
            capability=capability,
        )


def trusted_text(value: str, *, source: str) -> ContextText:
    """Mark a source-controlled dynamic string trusted explicitly."""

    return ContextText(value=value, trust=TrustLevel.TRUSTED, source=source)


def untrusted_text(value: str, *, source: str) -> ContextText:
    """Mark a dynamic string untrusted explicitly."""

    return ContextText(value=value, trust=TrustLevel.UNTRUSTED, source=source)


def prepare_prompt_values(context: PromptContext) -> dict[str, object]:
    """Redact, scan, label, and validate every dynamic value before rendering.

    Raw strings are prohibited in a manually constructed ``PromptContext``.
    ``PromptContext.from_untrusted`` is the deliberate convenience constructor
    for agent input and recursively assigns the untrusted trust level.
    """

    prepared: dict[str, object] = {}
    for variable_name, value in context.values.items():
        if _PROMPT_VARIABLE_PATTERN.fullmatch(variable_name) is None:
            raise PromptContextError("prompt variable names must be safe identifiers")
        prepared[variable_name] = _prepare_value(value, capability=context.capability)
    return prepared


def scan_prompt_injection(text: str) -> PromptInjectionScan:
    """Return advisory injection indicators without copying text into the result."""

    if not isinstance(text, str):
        raise PromptContextError("prompt-injection scan input must be a string")
    patterns = tuple(
        pattern
        for pattern, expression in _INJECTION_PATTERNS
        if expression.search(text) is not None
    )
    return PromptInjectionScan(patterns)


def _prepare_value(value: object, *, capability: AgentCapability) -> object:
    if isinstance(value, ContextText):
        return _prepare_text(value, capability=capability)
    if isinstance(value, Mapping):
        raise PromptContextError(
            "nested prompt-context mappings must be serialized to ContextText"
        )
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return tuple(_prepare_value(item, capability=capability) for item in value)
    if isinstance(value, (str, bytes, bytearray)):
        raise PromptContextError(
            "raw strings are forbidden in prompt context; use ContextText or "
            "PromptContext.from_untrusted"
        )
    if value is None or isinstance(value, (bool, int, float)):
        return value
    raise PromptContextError(
        "prompt context values must be ContextText, scalar values, or nested sequences"
    )


def _prepare_text(value: ContextText, *, capability: AgentCapability) -> str:
    if (
        value.trust is TrustLevel.UNTRUSTED
        and capability is AgentCapability.WRITE_TOOLS
    ):
        raise PromptContextError(
            "untrusted context cannot be rendered for an agent with write tools"
        )
    redaction = redact_pii(value.value)
    if value.trust is TrustLevel.TRUSTED:
        return redaction.redacted_text

    scan = scan_prompt_injection(redaction.redacted_text)
    signal_value = ",".join(pattern.value for pattern in scan.patterns) or "none"
    escaped_text = html.escape(redaction.redacted_text, quote=False)
    return (
        f'<untrusted_content source="{value.source}" '
        f'injection_signals="{signal_value}">\n'
        f"{escaped_text}\n"
        "</untrusted_content>"
    )


def _mark_strings(
    value: object,
    *,
    trust: TrustLevel,
    source: str,
) -> object:
    if isinstance(value, ContextText):
        return value
    if isinstance(value, str):
        return ContextText(value=value, trust=trust, source=source)
    if isinstance(value, Mapping):
        raise PromptContextError(
            "nested prompt-context mappings must be serialized to a string first"
        )
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return tuple(_mark_strings(item, trust=trust, source=source) for item in value)
    if value is None or isinstance(value, (bool, int, float)):
        return value
    raise PromptContextError(
        "prompt context values must be strings, scalar values, mappings, or sequences"
    )


_INJECTION_PATTERNS: Final[
    tuple[tuple[PromptInjectionPattern, re.Pattern[str]], ...]
] = (
    (
        PromptInjectionPattern.INSTRUCTION_OVERRIDE,
        re.compile(
            r"\b(?:ignore|disregard|forget|override)\b.{0,80}\b"
            r"(?:previous|prior|above|system|developer)\b.{0,80}\b"
            r"(?:instructions?|rules?|prompts?|messages?)\b",
            re.IGNORECASE | re.DOTALL,
        ),
    ),
    (
        PromptInjectionPattern.ROLE_IMPERSONATION,
        re.compile(
            r"\b(?:you are now|act as|system message|developer message|assistant message)\b",
            re.IGNORECASE,
        ),
    ),
    (
        PromptInjectionPattern.SECRET_EXTRACTION,
        re.compile(
            r"\b(?:reveal|show|print|exfiltrate|give)\b.{0,80}\b"
            r"(?:system prompt|secret|api[ _-]?key|password|token|credential)\b",
            re.IGNORECASE | re.DOTALL,
        ),
    ),
    (
        PromptInjectionPattern.TOOL_INVOCATION,
        re.compile(
            r"\b(?:call|invoke|run|use)\b.{0,40}\b(?:tool|function|command|browser)\b",
            re.IGNORECASE | re.DOTALL,
        ),
    ),
    (
        PromptInjectionPattern.DELIMITER_ESCAPE,
        re.compile(r"</?untrusted_content\b|<!--\s*resident-os:", re.IGNORECASE),
    ),
)
