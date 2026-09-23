"""Deterministic extractive selection for citation-bearing source text.

Policy, lease, and safety language is selected verbatim rather than summarized.
Every returned selection is an exact substring of an input source and retains
its source-relative character offsets. This module has no model, database, or
network dependency; callers remain responsible for source authorization,
parent-section expansion, and the later token-budget decision.
"""

from __future__ import annotations

import math
import re
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Final


DEFAULT_MAX_SENTENCES: Final = 6
_TOKEN_PATTERN: Final = re.compile(r"\w+(?:['’_-]\w+)*", re.UNICODE)
_PARAGRAPH_BREAK_PATTERN: Final = re.compile(r"\n[ \t]*\n+")
_LIST_OR_TABLE_PATTERN: Final = re.compile(r"^[ \t]*(?:[-*+] |\d+[.)] |\|)")
_HEADING_PATTERN: Final = re.compile(r"^[ \t]*#{1,6}[ \t]+")
_SENTENCE_ABBREVIATIONS: Final = frozenset(
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
        "u.k.",
        "u.s.",
        "vs.",
    }
)
_QUERY_STOP_WORDS: Final = frozenset(
    {
        "a",
        "an",
        "and",
        "are",
        "as",
        "at",
        "be",
        "can",
        "do",
        "does",
        "for",
        "from",
        "how",
        "i",
        "in",
        "is",
        "it",
        "me",
        "my",
        "of",
        "on",
        "or",
        "please",
        "the",
        "this",
        "to",
        "was",
        "what",
        "when",
        "where",
        "which",
        "who",
        "will",
        "with",
        "would",
    }
)


@dataclass(frozen=True, slots=True)
class ExtractiveSource:
    """One already-authorized source span eligible for sentence selection.

    ``source_start`` is an optional offset into the parent document. It lets a
    caller pass an expanded parent section while preserving offsets suitable for
    a later citation verifier.
    """

    source_id: str
    text: str
    source_start: int = 0

    def __post_init__(self) -> None:
        _require_non_blank(self.source_id, "source_id")
        _require_non_blank(self.text, "text")
        if type(self.source_start) is not int or self.source_start < 0:
            raise ValueError("source_start must be a non-negative integer")


@dataclass(frozen=True, slots=True)
class ExtractiveSentence:
    """A verbatim source sentence with absolute source offsets and relevance."""

    source_id: str
    source_start: int
    source_end: int
    text: str
    relevance_score: float

    def __post_init__(self) -> None:
        _require_non_blank(self.source_id, "source_id")
        _require_non_blank(self.text, "text")
        if type(self.source_start) is not int or self.source_start < 0:
            raise ValueError("source_start must be a non-negative integer")
        if type(self.source_end) is not int or self.source_end <= self.source_start:
            raise ValueError("source_end must be greater than source_start")
        if not math.isfinite(self.relevance_score) or self.relevance_score <= 0:
            raise ValueError("relevance_score must be finite and positive")


@dataclass(frozen=True, slots=True)
class _SentenceCandidate:
    source: ExtractiveSource
    source_order: int
    local_start: int
    local_end: int
    text: str
    relevance_score: float


def select_extractive_sentences(
    *,
    query: str,
    sources: Sequence[ExtractiveSource],
    max_sentences: int = DEFAULT_MAX_SENTENCES,
) -> tuple[ExtractiveSentence, ...]:
    """Return the most query-supported, verbatim source sentences.

    The function never rewrites, concatenates, completes, or otherwise creates
    policy text. A zero-overlap query returns no selections, which is safer than
    carrying unrelated policy into a downstream model context. Ties are resolved
    by input source order and original source position for reproducible traces.
    """

    normalized_query = _require_non_blank(query, "query")
    _validate_max_sentences(max_sentences)
    if not sources:
        return ()

    query_terms = _query_terms(normalized_query)
    if not query_terms:
        return ()
    candidates = tuple(
        candidate
        for source_order, source in enumerate(sources)
        for candidate in _scored_source_sentences(
            source=source,
            source_order=source_order,
            query_terms=query_terms,
        )
        if candidate.relevance_score > 0
    )
    ranked = sorted(
        candidates,
        key=lambda candidate: (
            -candidate.relevance_score,
            candidate.source_order,
            candidate.local_start,
        ),
    )
    return tuple(
        ExtractiveSentence(
            source_id=candidate.source.source_id,
            source_start=candidate.source.source_start + candidate.local_start,
            source_end=candidate.source.source_start + candidate.local_end,
            text=candidate.text,
            relevance_score=candidate.relevance_score,
        )
        for candidate in ranked[:max_sentences]
    )


def _scored_source_sentences(
    *,
    source: ExtractiveSource,
    source_order: int,
    query_terms: Counter[str],
) -> tuple[_SentenceCandidate, ...]:
    identifier_terms = Counter(_tokens(source.source_id))
    return tuple(
        _SentenceCandidate(
            source=source,
            source_order=source_order,
            local_start=local_start,
            local_end=local_end,
            text=sentence,
            relevance_score=_relevance_score(
                sentence=sentence,
                query_terms=query_terms,
                identifier_terms=identifier_terms,
            ),
        )
        for local_start, local_end, sentence in _source_sentences(source.text)
    )


def _relevance_score(
    *,
    sentence: str,
    query_terms: Counter[str],
    identifier_terms: Counter[str],
) -> float:
    sentence_terms = Counter(_tokens(sentence))
    shared_terms = set(query_terms).intersection(sentence_terms)
    if not shared_terms:
        return 0.0

    coverage = sum(query_terms[term] for term in shared_terms) / sum(
        query_terms.values()
    )
    term_frequency = sum(
        min(query_terms[term], sentence_terms[term]) for term in shared_terms
    )
    identifier_overlap = len(set(query_terms).intersection(identifier_terms))
    return (coverage * 100) + term_frequency + (identifier_overlap * 0.01)


def _query_terms(query: str) -> Counter[str]:
    return Counter(
        token
        for token in _tokens(query)
        if token not in _QUERY_STOP_WORDS and len(token) > 1
    )


def _tokens(text: str) -> tuple[str, ...]:
    return tuple(match.group(0).casefold() for match in _TOKEN_PATTERN.finditer(text))


def _source_sentences(text: str) -> tuple[tuple[int, int, str], ...]:
    """Split prose and Markdown list/table lines without changing source text."""

    spans: list[tuple[int, int, str]] = []
    block_start = 0
    for paragraph_break in _PARAGRAPH_BREAK_PATTERN.finditer(text):
        spans.extend(_block_sentences(text, block_start, paragraph_break.start()))
        block_start = paragraph_break.end()
    spans.extend(_block_sentences(text, block_start, len(text)))
    return tuple(spans)


def _block_sentences(
    text: str, start: int, end: int
) -> tuple[tuple[int, int, str], ...]:
    start, end = _trim_span(text, start, end)
    if start >= end:
        return ()
    block = text[start:end]
    lines = tuple(_line_spans(text, start, end))
    if _HEADING_PATTERN.match(block):
        return ()
    if len(lines) > 1 and all(
        _LIST_OR_TABLE_PATTERN.match(text[line_start:line_end]) is not None
        for line_start, line_end in lines
    ):
        return tuple(
            sentence
            for line_start, line_end in lines
            if (sentence := _span_sentence(text, line_start, line_end)) is not None
        )
    return _prose_sentences(text, start, end)


def _line_spans(text: str, start: int, end: int) -> tuple[tuple[int, int], ...]:
    spans: list[tuple[int, int]] = []
    line_start = start
    while line_start < end:
        newline = text.find("\n", line_start, end)
        line_end = end if newline == -1 else newline
        trimmed_start, trimmed_end = _trim_span(text, line_start, line_end)
        if trimmed_start < trimmed_end:
            spans.append((trimmed_start, trimmed_end))
        line_start = end if newline == -1 else newline + 1
    return tuple(spans)


def _prose_sentences(
    text: str, start: int, end: int
) -> tuple[tuple[int, int, str], ...]:
    sentences: list[tuple[int, int, str]] = []
    sentence_start = start
    position = start
    while position < end:
        if text[position] in ".!?" and _is_sentence_boundary(text, position, end):
            sentence_end = _sentence_end_after_closers(text, position, end)
            sentence = _span_sentence(text, sentence_start, sentence_end)
            if sentence is not None:
                sentences.append(sentence)
            sentence_start = sentence_end
        position += 1
    trailing = _span_sentence(text, sentence_start, end)
    if trailing is not None:
        sentences.append(trailing)
    return tuple(sentences)


def _is_sentence_boundary(text: str, position: int, end: int) -> bool:
    if text[position] == ".":
        token_start = position
        while token_start > 0 and not text[token_start - 1].isspace():
            token_start -= 1
        token = text[token_start : position + 1].casefold()
        if token in _SENTENCE_ABBREVIATIONS:
            return False
        if position + 1 < end and text[position + 1].isdigit():
            return False
    after = _sentence_end_after_closers(text, position, end)
    return after == end or text[after].isspace()


def _sentence_end_after_closers(text: str, position: int, end: int) -> int:
    sentence_end = position + 1
    while sentence_end < end and text[sentence_end] in "\"'”’)]}":
        sentence_end += 1
    return sentence_end


def _span_sentence(text: str, start: int, end: int) -> tuple[int, int, str] | None:
    start, end = _trim_span(text, start, end)
    if start >= end:
        return None
    return start, end, text[start:end]


def _trim_span(text: str, start: int, end: int) -> tuple[int, int]:
    while start < end and text[start].isspace():
        start += 1
    while end > start and text[end - 1].isspace():
        end -= 1
    return start, end


def _validate_max_sentences(max_sentences: int) -> None:
    if type(max_sentences) is not int or max_sentences < 1:
        raise ValueError("max_sentences must be a positive integer")


def _require_non_blank(value: str, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must be a non-blank string")
    return value.strip()
