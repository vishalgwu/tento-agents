"""Deterministic, corpus-aware chunking with source-span preservation.

This module is deliberately pure: it reads no files, calls no model, and has no
database or tool authority. The caller is responsible for validating document
metadata and lifecycle eligibility before passing content here. Every Markdown
chunk's source offsets refer to the exact ``markdown`` argument supplied to
``chunk_markdown`` so a later citation verifier can recover the cited text.
"""

from __future__ import annotations

import hashlib
import math
import re
from dataclasses import dataclass
from enum import Enum
from typing import Final


SOP_MIN_TOKENS: Final = 300
SOP_MAX_TOKENS: Final = 600
SOP_OVERLAP_RATIO: Final = 0.15

_TOKEN_PATTERN: Final = re.compile(r"\w+(?:['’_-]\w+)*|[^\w\s]", re.UNICODE)
_HEADING_PATTERN: Final = re.compile(
    r"^(?P<marks>#{1,6})[ \t]+(?P<title>.*?)[ \t]*$", re.MULTILINE
)
_LIST_ITEM_PATTERN: Final = re.compile(
    r"^(?P<indent>[ \t]*)(?P<marker>[-*+]|\d+[.)])[ \t]+", re.MULTILINE
)
_FRONT_MATTER_DELIMITER: Final = re.compile(r"^---[ \t]*(?:\r?\n|$)", re.MULTILINE)


class CorpusKind(str, Enum):
    """Corpus strategies supported by the initial retrieval ingestion path."""

    LEASE = "lease"
    SOP = "sop"
    COMMUNITY_RULES = "community_rules"


@dataclass(frozen=True, slots=True)
class Chunk:
    """One citation-ready chunk, ready for a future ``kb_chunks`` insert.

    ``source_start`` and ``source_end`` are zero-based, end-exclusive character
    offsets. ``token_count`` uses this module's deterministic lexical estimator;
    it is intentionally not presented as a provider tokenizer count.
    """

    index: int
    heading_path: str
    source_start: int
    source_end: int
    content: str
    token_count: int
    content_sha256: str

    def __post_init__(self) -> None:
        if self.index < 0:
            raise ValueError("chunk index must be non-negative")
        if not self.heading_path.strip():
            raise ValueError("chunk heading_path must not be blank")
        if self.source_start < 0 or self.source_end <= self.source_start:
            raise ValueError("chunk source span must be non-empty and ordered")
        if not self.content:
            raise ValueError("chunk content must not be empty")
        if self.token_count != count_lexical_tokens(self.content):
            raise ValueError("chunk token_count must match its content")
        expected_hash = hashlib.sha256(self.content.encode("utf-8")).hexdigest()
        if self.content_sha256 != expected_hash:
            raise ValueError("chunk content_sha256 must match its content")


@dataclass(frozen=True, slots=True)
class _Section:
    """A Markdown heading scope with offsets into the original input."""

    heading_path: str
    source_start: int
    heading_end: int
    source_end: int


@dataclass(frozen=True, slots=True)
class _ChunkDraft:
    """A chunk before the document-wide, contiguous index is assigned."""

    heading_path: str
    source_start: int
    source_end: int
    content: str


def count_lexical_tokens(text: str) -> int:
    """Return a deterministic, dependency-free lexical-token estimate.

    This estimator gives stable 300–600 token SOP windows without coupling the
    ingestion contract to a specific embedding provider. Embedding execution may
    record its provider token usage separately; it must not alter chunk spans.
    """

    return len(_TOKEN_PATTERN.findall(text))


def chunk_markdown(
    *,
    markdown: str,
    corpus: CorpusKind,
    document_title: str,
) -> tuple[Chunk, ...]:
    """Chunk a Markdown policy document using its corpus-specific strategy.

    Optional YAML front matter at the start of ``markdown`` is excluded from
    chunk content, while returned source spans still point into the original raw
    input. ``document_title`` is used only as a fallback heading path when the
    document has no usable Markdown heading.
    """

    _require_non_blank(markdown, "markdown")
    title = _require_non_blank(document_title, "document_title")
    sections = _markdown_sections(markdown, title)

    if corpus is CorpusKind.LEASE:
        drafts = _lease_drafts(markdown, sections)
    elif corpus is CorpusKind.SOP:
        drafts = _sop_drafts(markdown, sections)
    elif corpus is CorpusKind.COMMUNITY_RULES:
        drafts = _community_rule_drafts(markdown, sections)
    else:
        raise ValueError(f"unsupported corpus strategy: {corpus!r}")

    if not drafts:
        raise ValueError("markdown did not contain chunkable content")
    return _finalize(drafts)


def chunk_work_order_history(
    *,
    ticket_id: str,
    symptom: str,
    resolution: str,
) -> tuple[Chunk, ...]:
    """Create exactly one embedding payload for a resolved ticket's history.

    The payload deliberately contains symptom plus resolution, not a generated
    summary. Callers must provide authorised, redacted fields and keep the
    resulting record tenant-scoped. Source positions refer to this constructed,
    immutable payload rather than a Markdown document.
    """

    normalized_ticket_id = _require_non_blank(ticket_id, "ticket_id")
    normalized_symptom = _require_non_blank(symptom, "symptom")
    normalized_resolution = _require_non_blank(resolution, "resolution")
    content = f"Symptom: {normalized_symptom}\nResolution: {normalized_resolution}"
    draft = _ChunkDraft(
        heading_path=f"ticket:{normalized_ticket_id}",
        source_start=0,
        source_end=len(content),
        content=content,
    )
    return _finalize((draft,))


def _require_non_blank(value: str, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must be a non-blank string")
    return value.strip()


def _markdown_sections(markdown: str, document_title: str) -> tuple[_Section, ...]:
    body_start = _front_matter_body_start(markdown)
    headings = list(_HEADING_PATTERN.finditer(markdown, body_start))
    if not headings:
        section = _section_if_non_empty(
            heading_path=document_title,
            source_start=body_start,
            heading_end=body_start,
            source_end=len(markdown),
            markdown=markdown,
        )
        return (section,) if section is not None else ()

    sections: list[_Section] = []
    prefix = _section_if_non_empty(
        heading_path=document_title,
        source_start=body_start,
        heading_end=body_start,
        source_end=headings[0].start(),
        markdown=markdown,
    )
    if prefix is not None:
        sections.append(prefix)

    path_parts: list[str] = []
    for position, heading in enumerate(headings):
        level = len(heading.group("marks"))
        heading_title = heading.group("title").strip().rstrip("#").rstrip()
        if not heading_title:
            heading_title = document_title

        if level == 1:
            path_parts = [heading_title]
        elif path_parts:
            path_parts = path_parts[: min(level - 1, len(path_parts))]
            path_parts.append(heading_title)
        else:
            path_parts = [document_title, heading_title]

        next_heading_start = (
            headings[position + 1].start()
            if position + 1 < len(headings)
            else len(markdown)
        )
        section = _section_if_non_empty(
            heading_path=" > ".join(path_parts),
            source_start=heading.start(),
            heading_end=_line_end(markdown, heading.end()),
            source_end=next_heading_start,
            markdown=markdown,
        )
        if section is not None:
            sections.append(section)

    if sections:
        return tuple(sections)

    fallback = _section_if_non_empty(
        heading_path=document_title,
        source_start=body_start,
        heading_end=body_start,
        source_end=len(markdown),
        markdown=markdown,
    )
    return (fallback,) if fallback is not None else ()


def _front_matter_body_start(markdown: str) -> int:
    """Return the first body offset, preserving original offsets for citations."""

    first_delimiter = _FRONT_MATTER_DELIMITER.match(markdown)
    if first_delimiter is None:
        return 0
    closing_delimiter = _FRONT_MATTER_DELIMITER.search(markdown, first_delimiter.end())
    return closing_delimiter.end() if closing_delimiter is not None else 0


def _line_end(markdown: str, offset: int) -> int:
    newline = markdown.find("\n", offset)
    return len(markdown) if newline == -1 else newline + 1


def _section_if_non_empty(
    *,
    heading_path: str,
    source_start: int,
    heading_end: int,
    source_end: int,
    markdown: str,
) -> _Section | None:
    if not markdown[heading_end:source_end].strip():
        return None
    start, end = _trim_span(markdown, source_start, source_end)
    if start >= end:
        return None
    return _Section(
        heading_path=heading_path,
        source_start=start,
        heading_end=heading_end,
        source_end=end,
    )


def _lease_drafts(
    markdown: str, sections: tuple[_Section, ...]
) -> tuple[_ChunkDraft, ...]:
    """Keep each Markdown clause/section intact and retain its full path."""

    return tuple(
        draft
        for section in sections
        if (
            draft := _draft_from_span(
                markdown, section.heading_path, section.source_start, section.source_end
            )
        )
        is not None
    )


def _sop_drafts(
    markdown: str, sections: tuple[_Section, ...]
) -> tuple[_ChunkDraft, ...]:
    """Split within heading scopes into 300–600 lexical-token windows."""

    drafts: list[_ChunkDraft] = []
    for section in sections:
        token_matches = list(
            _TOKEN_PATTERN.finditer(markdown, section.source_start, section.source_end)
        )
        token_total = len(token_matches)
        if token_total <= SOP_MAX_TOKENS:
            draft = _draft_from_span(
                markdown, section.heading_path, section.source_start, section.source_end
            )
            if draft is not None:
                drafts.append(draft)
            continue

        window_count = _sop_window_count(token_total)
        window_tokens = math.ceil(
            token_total / (1 + (window_count - 1) * (1 - SOP_OVERLAP_RATIO))
        )
        overlap_tokens = math.floor(window_tokens * SOP_OVERLAP_RATIO)
        stride = window_tokens - overlap_tokens

        for window_index in range(window_count):
            first_token = window_index * stride
            if first_token >= token_total:
                break
            last_token = min(first_token + window_tokens, token_total)
            draft = _draft_from_span(
                markdown,
                section.heading_path,
                token_matches[first_token].start(),
                token_matches[last_token - 1].end(),
            )
            if draft is not None:
                drafts.append(draft)
    return tuple(drafts)


def _sop_window_count(token_total: int) -> int:
    """Choose the fewest windows that keep the target window at most 600 tokens."""

    window_count = 1
    while (
        math.ceil(token_total / (1 + (window_count - 1) * (1 - SOP_OVERLAP_RATIO)))
        > SOP_MAX_TOKENS
    ):
        window_count += 1
    return window_count


def _community_rule_drafts(
    markdown: str, sections: tuple[_Section, ...]
) -> tuple[_ChunkDraft, ...]:
    """Keep each top-level community rule in its own chunk.

    Introductory prose remains an independent chunk only when it contains text
    beyond the section heading. Nested list items stay with their parent rule.
    """

    drafts: list[_ChunkDraft] = []
    for section in sections:
        rules = _top_level_list_items(markdown, section.heading_end, section.source_end)
        if not rules:
            draft = _draft_from_span(
                markdown, section.heading_path, section.source_start, section.source_end
            )
            if draft is not None:
                drafts.append(draft)
            continue

        preamble = _draft_from_span(
            markdown,
            section.heading_path,
            section.source_start,
            rules[0].start(),
        )
        if (
            preamble is not None
            and markdown[section.heading_end : rules[0].start()].strip()
        ):
            drafts.append(preamble)

        for position, rule in enumerate(rules):
            rule_end = (
                rules[position + 1].start()
                if position + 1 < len(rules)
                else section.source_end
            )
            draft = _draft_from_span(
                markdown, section.heading_path, rule.start(), rule_end
            )
            if draft is not None:
                drafts.append(draft)
    return tuple(drafts)


def _top_level_list_items(
    markdown: str, start: int, end: int
) -> tuple[re.Match[str], ...]:
    matches = tuple(_LIST_ITEM_PATTERN.finditer(markdown, start, end))
    if not matches:
        return ()
    smallest_indent = min(_indent_width(match.group("indent")) for match in matches)
    return tuple(
        match
        for match in matches
        if _indent_width(match.group("indent")) == smallest_indent
    )


def _indent_width(indent: str) -> int:
    return len(indent.expandtabs(4))


def _draft_from_span(
    markdown: str, heading_path: str, start: int, end: int
) -> _ChunkDraft | None:
    trimmed_start, trimmed_end = _trim_span(markdown, start, end)
    if trimmed_start >= trimmed_end:
        return None
    return _ChunkDraft(
        heading_path=heading_path,
        source_start=trimmed_start,
        source_end=trimmed_end,
        content=markdown[trimmed_start:trimmed_end],
    )


def _trim_span(markdown: str, start: int, end: int) -> tuple[int, int]:
    while start < end and markdown[start].isspace():
        start += 1
    while end > start and markdown[end - 1].isspace():
        end -= 1
    return start, end


def _finalize(drafts: tuple[_ChunkDraft, ...]) -> tuple[Chunk, ...]:
    return tuple(
        Chunk(
            index=index,
            heading_path=draft.heading_path,
            source_start=draft.source_start,
            source_end=draft.source_end,
            content=draft.content,
            token_count=count_lexical_tokens(draft.content),
            content_sha256=hashlib.sha256(draft.content.encode("utf-8")).hexdigest(),
        )
        for index, draft in enumerate(drafts)
    )
