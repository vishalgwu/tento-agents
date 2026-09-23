"""Expand retrieval hits to the complete Markdown heading scope that contains them.

Chunks are deliberately small enough for ranking and reranking, but a matching
policy sentence may depend on another sentence in the same heading scope.  This
module expands selected chunks by reading every persisted chunk with the same
document ID and ``heading_path``.  It retains document-relative source offsets:
downstream extractive compression can therefore cite the exact selected text.

The raw Markdown body is not stored in ``kb_documents``.  This adapter therefore
merges the persisted chunks in a heading scope; any unavailable gap between
adjacent spans is represented as whitespace of identical length.  That preserves
absolute offsets without inventing policy language, while ``heading_path``
retains the enclosing-heading context.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol

import asyncpg  # type: ignore[import-untyped]

from brain.retrieval.hybrid import RetrievedKnowledgeChunk


class ParentExpansionError(RuntimeError):
    """Raised when a repository cannot safely provide a requested heading scope."""


@dataclass(frozen=True, slots=True)
class ParentSectionKey:
    """The document-local heading scope that contains one or more chunks."""

    document_id: uuid.UUID
    heading_path: str

    def __post_init__(self) -> None:
        if not isinstance(self.document_id, uuid.UUID):
            raise ValueError("document_id must be a UUID")
        if not isinstance(self.heading_path, str) or not self.heading_path.strip():
            raise ValueError("heading_path must be a non-blank string")


@dataclass(frozen=True, slots=True)
class ParentSectionChunk:
    """One persisted source span used to reconstruct a parent heading scope."""

    chunk_id: uuid.UUID
    document_id: uuid.UUID
    heading_path: str
    source_start: int
    source_end: int
    content: str

    def __post_init__(self) -> None:
        if not isinstance(self.chunk_id, uuid.UUID):
            raise ValueError("chunk_id must be a UUID")
        if not isinstance(self.document_id, uuid.UUID):
            raise ValueError("document_id must be a UUID")
        if not isinstance(self.heading_path, str) or not self.heading_path.strip():
            raise ValueError("heading_path must be a non-blank string")
        if type(self.source_start) is not int or self.source_start < 0:
            raise ValueError("source_start must be a non-negative integer")
        if type(self.source_end) is not int or self.source_end <= self.source_start:
            raise ValueError("source_end must be greater than source_start")
        if not isinstance(self.content, str) or not self.content:
            raise ValueError("content must be a non-blank string")
        if len(self.content) != self.source_end - self.source_start:
            raise ValueError("content length must match the source span")

    @property
    def key(self) -> ParentSectionKey:
        """Return the scope that owns this chunk."""

        return ParentSectionKey(
            document_id=self.document_id,
            heading_path=self.heading_path,
        )


@dataclass(frozen=True, slots=True)
class ExpandedParentSection:
    """A retrieved anchor expanded to its complete citation-preserving parent."""

    anchor: RetrievedKnowledgeChunk
    source_start: int
    source_end: int
    content: str
    source_chunk_ids: tuple[uuid.UUID, ...]

    def __post_init__(self) -> None:
        if type(self.source_start) is not int or self.source_start < 0:
            raise ValueError("source_start must be a non-negative integer")
        if type(self.source_end) is not int or self.source_end <= self.source_start:
            raise ValueError("source_end must be greater than source_start")
        if not isinstance(self.content, str) or not self.content:
            raise ValueError("content must be a non-blank string")
        if len(self.content) != self.source_end - self.source_start:
            raise ValueError("content length must match the source span")
        if not self.source_chunk_ids:
            raise ValueError("source_chunk_ids must not be empty")
        if len(self.source_chunk_ids) != len(set(self.source_chunk_ids)):
            raise ValueError("source_chunk_ids must not contain duplicates")
        if self.anchor.chunk_id not in self.source_chunk_ids:
            raise ValueError("parent section must include its retrieved anchor")
        if (
            self.anchor.source_start < self.source_start
            or self.anchor.source_end > self.source_end
        ):
            raise ValueError("parent section must contain the retrieved anchor span")
        local_start = self.anchor.source_start - self.source_start
        local_end = self.anchor.source_end - self.source_start
        if self.content[local_start:local_end] != self.anchor.content:
            raise ValueError(
                "parent section must preserve the retrieved anchor content"
            )


class ParentSectionRepository(Protocol):
    """Tenant-scoped read boundary for parent-heading reconstruction."""

    async def fetch_section_chunks(
        self,
        *,
        org_id: uuid.UUID,
        section_keys: Sequence[ParentSectionKey],
    ) -> Sequence[ParentSectionChunk]:
        """Return all chunks in each requested document-local heading scope."""


@dataclass(slots=True)
class ParentSectionExpander:
    """Expand selected retrieval chunks while preserving selection order and anchors."""

    repository: ParentSectionRepository

    async def expand(
        self,
        *,
        org_id: uuid.UUID,
        chunks: Sequence[RetrievedKnowledgeChunk],
    ) -> tuple[ExpandedParentSection, ...]:
        """Expand each chunk to all content under its containing heading path.

        The repository is queried once for the unique document-heading pairs, so
        multiple ranked chunks from the same policy section never cause N+1 reads.
        A partial or cross-scope response fails closed instead of emitting a
        truncated condition as if it were the complete policy section.
        """

        anchors = tuple(chunks)
        if not anchors:
            return ()
        _validate_anchors(anchors)
        keys = _unique_section_keys(anchors)
        section_chunks = await self.repository.fetch_section_chunks(
            org_id=org_id,
            section_keys=keys,
        )
        sections = _sections_by_key(section_chunks=section_chunks, requested_keys=keys)
        return tuple(
            _expand_anchor(anchor=anchor, section_chunks=sections[anchor_key(anchor)])
            for anchor in anchors
        )


class AsyncpgParentSectionRepository:
    """PostgreSQL adapter for parent expansion under the caller's RLS context."""

    def __init__(self, connection: asyncpg.Connection) -> None:
        self._connection = connection

    async def fetch_section_chunks(
        self,
        *,
        org_id: uuid.UUID,
        section_keys: Sequence[ParentSectionKey],
    ) -> tuple[ParentSectionChunk, ...]:
        """Fetch only the requested heading scopes, ordered by source position."""

        keys = tuple(section_keys)
        if not keys:
            return ()
        _validate_section_keys(keys)
        rows = await self._connection.fetch(
            """
            WITH requested(kb_document_id, heading_path) AS (
                SELECT *
                FROM unnest($2::uuid[], $3::text[])
                    AS value(kb_document_id, heading_path)
            )
            SELECT
                chunk.id AS chunk_id,
                chunk.kb_document_id AS document_id,
                chunk.heading_path,
                chunk.source_start,
                chunk.source_end,
                chunk.content
            FROM kb_chunks AS chunk
            JOIN requested
              ON requested.kb_document_id = chunk.kb_document_id
             AND requested.heading_path = chunk.heading_path
            WHERE chunk.org_id = $1
            ORDER BY
                chunk.kb_document_id,
                chunk.heading_path,
                chunk.source_start,
                chunk.source_end,
                chunk.id
            """,
            org_id,
            [key.document_id for key in keys],
            [key.heading_path for key in keys],
        )
        return tuple(_parent_section_chunk_from_row(row) for row in rows)


def _validate_anchors(anchors: Sequence[RetrievedKnowledgeChunk]) -> None:
    chunk_ids: set[uuid.UUID] = set()
    for anchor in anchors:
        if anchor.chunk_id in chunk_ids:
            raise ValueError("retrieved chunks must not repeat a chunk_id")
        chunk_ids.add(anchor.chunk_id)


def _unique_section_keys(
    anchors: Sequence[RetrievedKnowledgeChunk],
) -> tuple[ParentSectionKey, ...]:
    keys: list[ParentSectionKey] = []
    seen: set[ParentSectionKey] = set()
    for anchor in anchors:
        key = anchor_key(anchor)
        if key not in seen:
            seen.add(key)
            keys.append(key)
    return tuple(keys)


def anchor_key(anchor: RetrievedKnowledgeChunk) -> ParentSectionKey:
    """Return the document heading scope that contains a retrieved chunk."""

    return ParentSectionKey(
        document_id=anchor.document_id,
        heading_path=anchor.heading_path,
    )


def _validate_section_keys(section_keys: Sequence[ParentSectionKey]) -> None:
    if len(section_keys) != len(set(section_keys)):
        raise ValueError("section_keys must not contain duplicates")


def _sections_by_key(
    *,
    section_chunks: Sequence[ParentSectionChunk],
    requested_keys: Sequence[ParentSectionKey],
) -> dict[ParentSectionKey, tuple[ParentSectionChunk, ...]]:
    requested = set(requested_keys)
    grouped: dict[ParentSectionKey, list[ParentSectionChunk]] = {}
    chunk_ids: set[uuid.UUID] = set()
    for chunk in section_chunks:
        if chunk.key not in requested:
            raise ParentExpansionError(
                "repository returned an unrequested section chunk"
            )
        if chunk.chunk_id in chunk_ids:
            raise ParentExpansionError("repository returned a duplicate section chunk")
        chunk_ids.add(chunk.chunk_id)
        grouped.setdefault(chunk.key, []).append(chunk)

    missing = requested.difference(grouped)
    if missing:
        raise ParentExpansionError("repository did not return every requested section")
    return {
        key: tuple(
            sorted(
                values,
                key=lambda chunk: (
                    chunk.source_start,
                    chunk.source_end,
                    str(chunk.chunk_id),
                ),
            )
        )
        for key, values in grouped.items()
    }


def _expand_anchor(
    *,
    anchor: RetrievedKnowledgeChunk,
    section_chunks: Sequence[ParentSectionChunk],
) -> ExpandedParentSection:
    anchor_chunk = next(
        (chunk for chunk in section_chunks if chunk.chunk_id == anchor.chunk_id), None
    )
    if anchor_chunk is None:
        raise ParentExpansionError("repository did not return the retrieved anchor")
    if (
        anchor_chunk.document_id != anchor.document_id
        or anchor_chunk.heading_path != anchor.heading_path
        or anchor_chunk.source_start != anchor.source_start
        or anchor_chunk.source_end != anchor.source_end
        or anchor_chunk.content != anchor.content
    ):
        raise ParentExpansionError(
            "repository returned an anchor that does not match retrieval"
        )

    source_start = min(chunk.source_start for chunk in section_chunks)
    source_end = max(chunk.source_end for chunk in section_chunks)
    content = _reconstruct_content(
        section_chunks=section_chunks,
        source_start=source_start,
        source_end=source_end,
    )
    return ExpandedParentSection(
        anchor=anchor,
        source_start=source_start,
        source_end=source_end,
        content=content,
        source_chunk_ids=tuple(chunk.chunk_id for chunk in section_chunks),
    )


def _reconstruct_content(
    *,
    section_chunks: Sequence[ParentSectionChunk],
    source_start: int,
    source_end: int,
) -> str:
    """Merge overlapping source spans without changing any persisted characters."""

    characters: list[str | None] = [None] * (source_end - source_start)
    for chunk in section_chunks:
        for position, character in enumerate(chunk.content, start=chunk.source_start):
            index = position - source_start
            existing = characters[index]
            if existing is not None and existing != character:
                raise ParentExpansionError(
                    "overlapping chunks disagree about source content"
                )
            characters[index] = character
    return "".join(
        character if character is not None else " " for character in characters
    )


def _parent_section_chunk_from_row(row: asyncpg.Record) -> ParentSectionChunk:
    chunk_id = row["chunk_id"]
    document_id = row["document_id"]
    heading_path = row["heading_path"]
    source_start = row["source_start"]
    source_end = row["source_end"]
    content = row["content"]
    if not isinstance(chunk_id, uuid.UUID) or not isinstance(document_id, uuid.UUID):
        raise ParentExpansionError("parent section query returned an invalid identity")
    if not isinstance(heading_path, str) or not isinstance(content, str):
        raise ParentExpansionError("parent section query returned invalid text")
    if type(source_start) is not int or type(source_end) is not int:
        raise ParentExpansionError("parent section query returned invalid source spans")
    try:
        return ParentSectionChunk(
            chunk_id=chunk_id,
            document_id=document_id,
            heading_path=heading_path,
            source_start=source_start,
            source_end=source_end,
            content=content,
        )
    except ValueError as error:
        raise ParentExpansionError(
            "parent section query returned an invalid chunk"
        ) from error
