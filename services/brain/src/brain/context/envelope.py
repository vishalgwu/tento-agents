"""Deterministic, citation-bearing context envelopes for model prompts.

An envelope is an evidence transport format, not a summarizer. It retains the
source metadata required to audit a model claim and assigns stable citation IDs
to caller-provided evidence in input order. Token allocation deliberately lives
in :mod:`brain.context.budget` so provenance is never lost while trimming a
prompt.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from enum import Enum
from typing import Final

from brain.gateway.client import load_builtin_prompt


class ProvenanceKind(str, Enum):
    """The two evidence classes that a model may cite."""

    CITATION = "C"
    FACT = "F"


GROUNDING_INSTRUCTIONS: Final = load_builtin_prompt("grounding").render().content
_PROVENANCE_ID_PATTERN: Final = re.compile(r"^\[(?:C|F)[1-9]\d*\]$")


@dataclass(frozen=True, slots=True)
class ProvenanceInput:
    """Verbatim evidence and the metadata required to audit its use."""

    source: str
    version: str
    effective_from: date
    effective_to: date | None
    section: str
    text: str

    def __post_init__(self) -> None:
        _require_non_blank(self.source, "source")
        _require_non_blank(self.version, "version")
        _require_date(self.effective_from, "effective_from")
        if self.effective_to is not None:
            _require_date(self.effective_to, "effective_to")
            if self.effective_to < self.effective_from:
                raise ValueError("effective_to must not be before effective_from")
        _require_non_blank(self.section, "section")
        _require_non_blank(self.text, "text")


@dataclass(frozen=True, slots=True)
class ProvenanceRecord:
    """A source span whose stable ID can be cited in generated text."""

    provenance_id: str
    kind: ProvenanceKind
    source: str
    version: str
    effective_from: date
    effective_to: date | None
    section: str
    text: str

    def __post_init__(self) -> None:
        if not isinstance(self.kind, ProvenanceKind):
            raise ValueError("kind must be a ProvenanceKind")
        _require_provenance_id(self.provenance_id, self.kind)
        _require_non_blank(self.source, "source")
        _require_non_blank(self.version, "version")
        _require_date(self.effective_from, "effective_from")
        if self.effective_to is not None:
            _require_date(self.effective_to, "effective_to")
            if self.effective_to < self.effective_from:
                raise ValueError("effective_to must not be before effective_from")
        _require_non_blank(self.section, "section")
        _require_non_blank(self.text, "text")

    def render(self) -> str:
        """Render the complete audit metadata and original source text."""

        effective_to = (
            self.effective_to.isoformat()
            if self.effective_to is not None
            else "ongoing"
        )
        return (
            f"{self.provenance_id}\n"
            f"source: {self.source}\n"
            f"version: {self.version}\n"
            f"effective_from: {self.effective_from.isoformat()}\n"
            f"effective_to: {effective_to}\n"
            f"section: {self.section}\n"
            "text:\n"
            f"{self.text}"
        )


@dataclass(frozen=True, slots=True)
class ContextEnvelope:
    """Evidence, explicit unknowns, and the grounding rule for one model call."""

    citations: tuple[ProvenanceRecord, ...]
    facts: tuple[ProvenanceRecord, ...]
    unknowns: tuple[str, ...] = ()
    grounding_instructions: str = GROUNDING_INSTRUCTIONS

    def __post_init__(self) -> None:
        _require_non_blank(self.grounding_instructions, "grounding_instructions")
        citations = tuple(self.citations)
        facts = tuple(self.facts)
        unknowns = tuple(self.unknowns)
        if any(not isinstance(record, ProvenanceRecord) for record in citations):
            raise ValueError("citations must contain only ProvenanceRecord values")
        if any(not isinstance(record, ProvenanceRecord) for record in facts):
            raise ValueError("facts must contain only ProvenanceRecord values")
        records = (*citations, *facts)
        provenance_ids = tuple(record.provenance_id for record in records)
        if len(provenance_ids) != len(set(provenance_ids)):
            raise ValueError("provenance IDs must be unique within an envelope")
        if any(record.kind is not ProvenanceKind.CITATION for record in citations):
            raise ValueError("citations must use citation provenance IDs")
        if any(record.kind is not ProvenanceKind.FACT for record in facts):
            raise ValueError("facts must use fact provenance IDs")
        for unknown in unknowns:
            _require_non_blank(unknown, "unknowns entries")
        object.__setattr__(self, "citations", citations)
        object.__setattr__(self, "facts", facts)
        object.__setattr__(self, "unknowns", unknowns)

    def render(self) -> str:
        """Render a standalone model-ready envelope without changing evidence text."""

        sections = [
            "## Grounding rules\n" + self.grounding_instructions,
            _render_records("Citations", self.citations),
            _render_records("Facts", self.facts),
            _render_unknowns(self.unknowns),
        ]
        return "\n\n".join(section for section in sections if section)


def assemble_context_envelope(
    *,
    citations: Sequence[ProvenanceInput] = (),
    facts: Sequence[ProvenanceInput] = (),
    unknowns: Sequence[str] = (),
) -> ContextEnvelope:
    """Assign deterministic IDs while preserving the caller's evidence order."""

    _validate_provenance_inputs(citations, "citations")
    _validate_provenance_inputs(facts, "facts")
    if isinstance(unknowns, (str, bytes)):
        raise ValueError("unknowns must be a sequence of strings")
    citation_records = _assign_provenance_ids(citations, ProvenanceKind.CITATION)
    fact_records = _assign_provenance_ids(facts, ProvenanceKind.FACT)
    return ContextEnvelope(
        citations=citation_records,
        facts=fact_records,
        unknowns=tuple(unknowns),
    )


def _assign_provenance_ids(
    inputs: Sequence[ProvenanceInput], kind: ProvenanceKind
) -> tuple[ProvenanceRecord, ...]:
    return tuple(
        ProvenanceRecord(
            provenance_id=f"[{kind.value}{index}]",
            kind=kind,
            source=item.source,
            version=item.version,
            effective_from=item.effective_from,
            effective_to=item.effective_to,
            section=item.section,
            text=item.text,
        )
        for index, item in enumerate(inputs, start=1)
    )


def _render_records(title: str, records: Sequence[ProvenanceRecord]) -> str:
    if not records:
        return ""
    return f"## {title}\n" + "\n\n".join(record.render() for record in records)


def _render_unknowns(unknowns: Sequence[str]) -> str:
    if not unknowns:
        return "## Unknowns\n- None recorded."
    return "## Unknowns\n" + "\n".join(f"- {unknown}" for unknown in unknowns)


def _validate_provenance_inputs(
    values: Sequence[ProvenanceInput], field_name: str
) -> None:
    if isinstance(values, (str, bytes)):
        raise ValueError(f"{field_name} must be a sequence of ProvenanceInput")
    if any(not isinstance(value, ProvenanceInput) for value in values):
        raise ValueError(f"{field_name} must contain only ProvenanceInput values")


def _require_provenance_id(value: str, kind: ProvenanceKind) -> None:
    if not isinstance(value, str) or _PROVENANCE_ID_PATTERN.fullmatch(value) is None:
        raise ValueError("provenance_id must be a bracketed C or F identifier")
    if not value.startswith(f"[{kind.value}"):
        raise ValueError("provenance_id prefix must match provenance kind")


def _require_date(value: date, field_name: str) -> None:
    if type(value) is not date:
        raise ValueError(f"{field_name} must be a date")


def _require_non_blank(value: str, field_name: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must be a non-blank string")
