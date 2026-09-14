"""Version-safe ingestion of Markdown knowledge into retrieval storage.

Ingestion is the boundary between untrusted source files and the knowledge
index. It validates a deliberately small YAML front-matter schema, refuses an
unknown authority instead of silently choosing precedence, preserves immutable
document versions, and delegates vector generation to the typed embedding
adapter. It never promotes a temporary fixture to a production index.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import re
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime
from enum import Enum
from pathlib import Path
from typing import Final, Protocol, TypeAlias

import asyncpg  # type: ignore[import-untyped]

from brain.retrieval.chunking import Chunk, CorpusKind, chunk_markdown
from brain.retrieval.embed import (
    EMBEDDING_MODEL,
    Embedding,
    EmbeddingCache,
    EmbeddingProvider,
    embed_texts,
)


_FRONT_MATTER_DELIMITER: Final = re.compile(r"^---[ \t]*(?:\r?\n|$)", re.MULTILINE)
_FRONT_MATTER_KEY: Final = re.compile(r"^[a-z][a-z0-9_]*$")
_TITLE_PATTERN: Final = re.compile(r"^#[ \t]+(?P<title>.*?)[ \t]*$", re.MULTILINE)
_DATABASE_DOCUMENT_STATUSES: Final = frozenset(
    {"draft", "active", "superseded", "retired"}
)

FrontMatterValue: TypeAlias = str | bool | None


class FrontMatterValidationError(ValueError):
    """Raised when front matter is missing, malformed, or outside the contract."""


class AuthorityValidationError(FrontMatterValidationError):
    """Raised when a source claims an authority outside the frozen enum."""


class DocumentEligibilityError(ValueError):
    """Raised when source lifecycle metadata prohibits the requested ingestion."""


class DocumentVersionConflict(ValueError):
    """Raised when content changes without a new immutable document version."""


class Authority(str, Enum):
    """Values of the database ``authority`` enum and their fixed precedence."""

    STATUTE = "statute"
    LEASE = "lease"
    INTERNAL_SOP = "internal_sop"
    VENDOR_CONTRACT = "vendor_contract"


@dataclass(frozen=True, slots=True)
class KnowledgeDocument:
    """Validated Markdown source metadata plus the immutable raw source text."""

    document_key: str
    version: str
    title: str
    authority: Authority
    jurisdiction: str
    source_uri: str
    effective_from: datetime
    effective_to: datetime | None
    source_status: str
    production_eligible: bool
    corpus: CorpusKind
    source_path: Path
    markdown: str
    content_sha256: str


@dataclass(frozen=True, slots=True)
class ExistingKnowledgeDocument:
    """Minimum persisted state needed to decide whether to skip an ingestion."""

    document_id: uuid.UUID
    content_sha256: str


@dataclass(frozen=True, slots=True)
class EmbeddedChunk:
    """A citation-ready chunk paired with its validated embedding."""

    chunk: Chunk
    embedding: Embedding


@dataclass(frozen=True, slots=True)
class IngestionResult:
    """Outcome suitable for audit logging without retaining raw document text."""

    document_key: str
    version: str
    content_sha256: str
    document_id: uuid.UUID | None
    chunk_count: int
    skipped_unchanged: bool


class KnowledgeRepository(Protocol):
    """Persistence contract; callers provide a tenant-scoped implementation."""

    async def get_document(
        self,
        *,
        org_id: uuid.UUID,
        document_key: str,
        version: str,
    ) -> ExistingKnowledgeDocument | None:
        """Return a persisted document identity and hash, if it exists."""

    async def upsert_document_and_chunks(
        self,
        *,
        org_id: uuid.UUID,
        document: KnowledgeDocument,
        database_status: str,
        chunks: Sequence[EmbeddedChunk],
    ) -> uuid.UUID:
        """Persist a new immutable document version and its chunks atomically."""


@dataclass(slots=True)
class KnowledgeIngestor:
    """Coordinates validation, chunking, embedding, and an atomic repository write."""

    repository: KnowledgeRepository
    embedding_provider: EmbeddingProvider
    embedding_cache: EmbeddingCache
    org_id: uuid.UUID
    allow_temporary_fixtures: bool = False
    embedding_model: str = EMBEDDING_MODEL

    async def ingest_file(
        self,
        source_path: Path,
        *,
        corpus: CorpusKind | None = None,
    ) -> IngestionResult:
        """Read one UTF-8 Markdown source and ingest it under the configured tenant."""

        if source_path.suffix.lower() != ".md":
            raise ValueError("knowledge ingestion accepts Markdown (.md) files only")
        markdown = await asyncio.to_thread(source_path.read_text, encoding="utf-8")
        return await self.ingest_markdown(
            markdown=markdown,
            source_path=source_path,
            corpus=corpus,
        )

    async def ingest_markdown(
        self,
        *,
        markdown: str,
        source_path: Path,
        corpus: CorpusKind | None = None,
    ) -> IngestionResult:
        """Ingest a single raw Markdown source without logging its content."""

        document = parse_knowledge_document(
            markdown=markdown,
            source_path=source_path,
            corpus=corpus,
        )
        database_status = _database_status_for(
            document, allow_temporary_fixtures=self.allow_temporary_fixtures
        )
        existing = await self.repository.get_document(
            org_id=self.org_id,
            document_key=document.document_key,
            version=document.version,
        )
        if existing is not None:
            if existing.content_sha256 == document.content_sha256:
                return IngestionResult(
                    document_key=document.document_key,
                    version=document.version,
                    content_sha256=document.content_sha256,
                    document_id=existing.document_id,
                    chunk_count=0,
                    skipped_unchanged=True,
                )
            raise DocumentVersionConflict(
                "knowledge document content changed without a new version"
            )

        chunks = chunk_markdown(
            markdown=document.markdown,
            corpus=document.corpus,
            document_title=document.title,
        )
        embeddings = await embed_texts(
            provider=self.embedding_provider,
            cache=self.embedding_cache,
            texts=tuple(chunk.content for chunk in chunks),
            model=self.embedding_model,
        )
        embedded_chunks = tuple(
            EmbeddedChunk(chunk=chunk, embedding=embedding)
            for chunk, embedding in zip(chunks, embeddings, strict=True)
        )
        document_id = await self.repository.upsert_document_and_chunks(
            org_id=self.org_id,
            document=document,
            database_status=database_status,
            chunks=embedded_chunks,
        )
        return IngestionResult(
            document_key=document.document_key,
            version=document.version,
            content_sha256=document.content_sha256,
            document_id=document_id,
            chunk_count=len(embedded_chunks),
            skipped_unchanged=False,
        )


def parse_knowledge_document(
    *,
    markdown: str,
    source_path: Path,
    corpus: CorpusKind | None = None,
) -> KnowledgeDocument:
    """Parse the strict source contract and select a deterministic chunk strategy."""

    metadata, body_start = _parse_front_matter(markdown)
    document_key = _required_string(metadata, "id")
    version = _required_string(metadata, "version")
    jurisdiction = _required_string(metadata, "jurisdiction")
    source_uri = _required_string(metadata, "source_uri")
    source_status = _required_string(metadata, "status")
    production_eligible = _required_boolean(metadata, "production_eligible")
    authority = _parse_authority(metadata)
    effective_from = _parse_effective_timestamp(
        _required_string(metadata, "effective_from"), "effective_from"
    )
    if "effective_to" not in metadata:
        raise FrontMatterValidationError("front matter 'effective_to' is required")
    effective_to = _parse_optional_effective_timestamp(metadata["effective_to"])
    if effective_to is not None and effective_to <= effective_from:
        raise FrontMatterValidationError(
            "effective_to must be later than effective_from"
        )

    title = _markdown_title(markdown, body_start) or document_key
    selected_corpus = corpus or _select_corpus(
        authority=authority, document_key=document_key, source_path=source_path
    )
    return KnowledgeDocument(
        document_key=document_key,
        version=version,
        title=title,
        authority=authority,
        jurisdiction=jurisdiction,
        source_uri=source_uri,
        effective_from=effective_from,
        effective_to=effective_to,
        source_status=source_status,
        production_eligible=production_eligible,
        corpus=selected_corpus,
        source_path=source_path,
        markdown=markdown,
        content_sha256=hashlib.sha256(markdown.encode("utf-8")).hexdigest(),
    )


class AsyncpgKnowledgeRepository:
    """Atomic PostgreSQL implementation for ``kb_documents`` and ``kb_chunks``.

    The caller must supply a transaction-safe connection with tenant context
    already established. This repository still binds ``org_id`` explicitly on
    every statement; it never uses a service-role or cross-tenant query.
    """

    def __init__(self, connection: asyncpg.Connection) -> None:
        self._connection = connection

    async def get_document(
        self,
        *,
        org_id: uuid.UUID,
        document_key: str,
        version: str,
    ) -> ExistingKnowledgeDocument | None:
        row = await self._connection.fetchrow(
            """
            SELECT id, content_sha256
            FROM kb_documents
            WHERE org_id = $1 AND document_key = $2 AND version = $3
            """,
            org_id,
            document_key,
            version,
        )
        if row is None:
            return None
        document_id = row["id"]
        content_sha256 = row["content_sha256"]
        if not isinstance(document_id, uuid.UUID) or not isinstance(
            content_sha256, str
        ):
            raise RuntimeError("kb_documents returned an invalid identity row")
        return ExistingKnowledgeDocument(
            document_id=document_id,
            content_sha256=content_sha256,
        )

    async def upsert_document_and_chunks(
        self,
        *,
        org_id: uuid.UUID,
        document: KnowledgeDocument,
        database_status: str,
        chunks: Sequence[EmbeddedChunk],
    ) -> uuid.UUID:
        """Persist a source and chunks in one transaction without version mutation."""

        async with self._connection.transaction():
            document_id = await self._connection.fetchval(
                """
                INSERT INTO kb_documents (
                    org_id, document_key, version, title, authority,
                    jurisdiction_code, source_uri, content_sha256, status,
                    effective_from, effective_to
                )
                VALUES ($1, $2, $3, $4, $5::text::authority, $6, $7, $8, $9::text::kb_document_status, $10, $11)
                ON CONFLICT (org_id, document_key, version) DO UPDATE
                SET updated_at = kb_documents.updated_at
                WHERE kb_documents.content_sha256 = EXCLUDED.content_sha256
                RETURNING id
                """,
                org_id,
                document.document_key,
                document.version,
                document.title,
                document.authority.value,
                document.jurisdiction,
                document.source_uri,
                document.content_sha256,
                database_status,
                document.effective_from,
                document.effective_to,
            )
            if not isinstance(document_id, uuid.UUID):
                raise DocumentVersionConflict(
                    "knowledge document content changed without a new version"
                )

            rows = [
                (
                    org_id,
                    document_id,
                    item.chunk.index,
                    item.chunk.heading_path,
                    item.chunk.source_start,
                    item.chunk.source_end,
                    item.chunk.content,
                    item.chunk.content_sha256,
                    item.chunk.token_count,
                    item.embedding.model,
                    item.embedding.as_halfvec_literal(),
                )
                for item in chunks
            ]
            await self._connection.executemany(
                """
                INSERT INTO kb_chunks (
                    org_id, kb_document_id, chunk_index, heading_path,
                    source_start, source_end, content, content_sha256,
                    token_count, embedding_model, embedding
                )
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11::text::halfvec)
                ON CONFLICT (org_id, kb_document_id, chunk_index) DO UPDATE
                SET heading_path = EXCLUDED.heading_path,
                    source_start = EXCLUDED.source_start,
                    source_end = EXCLUDED.source_end,
                    content = EXCLUDED.content,
                    content_sha256 = EXCLUDED.content_sha256,
                    token_count = EXCLUDED.token_count,
                    embedding_model = EXCLUDED.embedding_model,
                    embedding = EXCLUDED.embedding
                WHERE kb_chunks.content_sha256 = EXCLUDED.content_sha256
                """,
                rows,
            )
            return document_id


def _parse_front_matter(markdown: str) -> tuple[dict[str, FrontMatterValue], int]:
    opening = _FRONT_MATTER_DELIMITER.match(markdown)
    if opening is None:
        raise FrontMatterValidationError(
            "knowledge document must start with YAML front matter"
        )
    closing = _FRONT_MATTER_DELIMITER.search(markdown, opening.end())
    if closing is None:
        raise FrontMatterValidationError(
            "knowledge front matter is missing a closing delimiter"
        )

    metadata: dict[str, FrontMatterValue] = {}
    for line_number, line in enumerate(
        markdown[opening.end() : closing.start()].splitlines(), start=2
    ):
        if not line.strip():
            continue
        if ":" not in line:
            raise FrontMatterValidationError(
                f"front matter line {line_number} must be a key-value pair"
            )
        key, raw_value = line.split(":", maxsplit=1)
        key = key.strip()
        if not _FRONT_MATTER_KEY.fullmatch(key):
            raise FrontMatterValidationError(
                f"front matter line {line_number} has an invalid key"
            )
        if key in metadata:
            raise FrontMatterValidationError(f"front matter key {key!r} is duplicated")
        metadata[key] = _parse_front_matter_scalar(raw_value.strip(), line_number)
    return metadata, closing.end()


def _parse_front_matter_scalar(raw_value: str, line_number: int) -> FrontMatterValue:
    if raw_value == "null":
        return None
    if raw_value == "true":
        return True
    if raw_value == "false":
        return False
    if raw_value.startswith('"'):
        try:
            parsed = json.loads(raw_value)
        except json.JSONDecodeError as error:
            raise FrontMatterValidationError(
                f"front matter line {line_number} has an invalid quoted string"
            ) from error
        if not isinstance(parsed, str):
            raise FrontMatterValidationError(
                f"front matter line {line_number} must contain a scalar value"
            )
        return parsed
    if raw_value.startswith(("[", "{")):
        raise FrontMatterValidationError(
            f"front matter line {line_number} must contain a scalar value"
        )
    if not raw_value:
        raise FrontMatterValidationError(
            f"front matter line {line_number} has no value"
        )
    return raw_value


def _required_string(metadata: dict[str, FrontMatterValue], field_name: str) -> str:
    value = metadata.get(field_name)
    if not isinstance(value, str) or not value.strip():
        raise FrontMatterValidationError(
            f"front matter {field_name!r} must be a non-blank string"
        )
    return value.strip()


def _required_boolean(metadata: dict[str, FrontMatterValue], field_name: str) -> bool:
    value = metadata.get(field_name)
    if not isinstance(value, bool):
        raise FrontMatterValidationError(
            f"front matter {field_name!r} must be true or false"
        )
    return value


def _parse_authority(metadata: dict[str, FrontMatterValue]) -> Authority:
    raw_authority = _required_string(metadata, "authority")
    try:
        return Authority(raw_authority)
    except ValueError as error:
        allowed = ", ".join(authority.value for authority in Authority)
        raise AuthorityValidationError(
            f"front matter authority {raw_authority!r} is invalid; expected one of: {allowed}"
        ) from error


def _parse_effective_timestamp(value: str, field_name: str) -> datetime:
    try:
        parsed = date.fromisoformat(value)
    except ValueError as error:
        raise FrontMatterValidationError(
            f"front matter {field_name!r} must use an ISO-8601 date"
        ) from error
    return datetime(parsed.year, parsed.month, parsed.day, tzinfo=UTC)


def _parse_optional_effective_timestamp(
    value: FrontMatterValue | None,
) -> datetime | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise FrontMatterValidationError(
            "front matter 'effective_to' must be a date or null"
        )
    return _parse_effective_timestamp(value, "effective_to")


def _markdown_title(markdown: str, body_start: int) -> str | None:
    match = _TITLE_PATTERN.search(markdown, body_start)
    if match is None:
        return None
    title = match.group("title").strip().rstrip("#").rstrip()
    return title or None


def _select_corpus(
    *, authority: Authority, document_key: str, source_path: Path
) -> CorpusKind:
    if authority is Authority.LEASE:
        return CorpusKind.LEASE
    if document_key.startswith("POL-COMM-") or "community" in {
        part.casefold() for part in source_path.parts
    }:
        return CorpusKind.COMMUNITY_RULES
    return CorpusKind.SOP


def _database_status_for(
    document: KnowledgeDocument, *, allow_temporary_fixtures: bool
) -> str:
    if document.source_status == "temporary_fixture":
        if not allow_temporary_fixtures:
            raise DocumentEligibilityError(
                "temporary_fixture documents are excluded from production ingestion"
            )
        return "draft"
    if not document.production_eligible:
        raise DocumentEligibilityError(
            "knowledge document is not eligible for production ingestion"
        )
    if document.source_status not in _DATABASE_DOCUMENT_STATUSES:
        raise FrontMatterValidationError(
            "front matter status must be a database document status or temporary_fixture"
        )
    return document.source_status
