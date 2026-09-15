"""Tenant-scoped BM25/vector retrieval with post-fusion metadata filtering.

The candidate queries intentionally apply only the non-negotiable tenant boundary
and their respective search predicates. Document status, jurisdiction, authority,
embedding-model compatibility, and effective dates are evaluated *after*
reciprocal-rank fusion. Applying selective document metadata predicates to the
HNSW query would reduce recall by forcing pgvector to discard candidates before
it can fill the candidate budget.

This module is read-only. It does not embed a query, persist ``retrievals`` or
``retrieval_results``, call a model, or make an operational decision. A caller
provides a validated query embedding and a transaction-bound repository whose RLS
context is already set for the requesting organisation.
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from typing import Final, Protocol

import asyncpg  # type: ignore[import-untyped]

from brain.retrieval.embed import Embedding
from brain.retrieval.ingest import Authority


LEXICAL_CANDIDATE_LIMIT: Final = 30
VECTOR_CANDIDATE_LIMIT: Final = 30
RRF_K: Final = 60


class KnowledgeDocumentStatus(str, Enum):
    """The frozen database lifecycle values for knowledge documents."""

    DRAFT = "draft"
    ACTIVE = "active"
    SUPERSEDED = "superseded"
    RETIRED = "retired"


class RetrievalRepositoryError(RuntimeError):
    """Raised when a repository breaks the retrieval read contract."""


@dataclass(frozen=True, slots=True)
class RetrievalMetadataFilters:
    """Post-fusion controls for source eligibility and retrieval scope.

    ``ACTIVE`` is the production-safe default. Evaluation callers must opt into
    ``DRAFT`` explicitly; this prevents temporary fixtures from becoming
    searchable in a resident-facing path merely because they score highly.
    """

    jurisdiction_code: str | None = None
    authorities: frozenset[Authority] | None = None
    allowed_document_statuses: frozenset[KnowledgeDocumentStatus] = frozenset(
        {KnowledgeDocumentStatus.ACTIVE}
    )

    def __post_init__(self) -> None:
        if self.jurisdiction_code is not None and not self.jurisdiction_code.strip():
            raise ValueError("jurisdiction_code must be non-blank when provided")
        if not self.allowed_document_statuses:
            raise ValueError("allowed_document_statuses must not be empty")
        if not all(
            isinstance(status, KnowledgeDocumentStatus)
            for status in self.allowed_document_statuses
        ):
            raise ValueError("allowed_document_statuses must contain known statuses")
        if self.authorities is not None and not self.authorities:
            raise ValueError("authorities must not be empty when provided")
        if self.authorities is not None and not all(
            isinstance(authority, Authority) for authority in self.authorities
        ):
            raise ValueError("authorities must contain known authority values")

    @classmethod
    def evaluation_only(
        cls,
        *,
        jurisdiction_code: str | None = None,
        authorities: frozenset[Authority] | None = None,
    ) -> RetrievalMetadataFilters:
        """Make an explicit draft-only scope for offline fixture evaluation."""

        return cls(
            jurisdiction_code=jurisdiction_code,
            authorities=authorities,
            allowed_document_statuses=frozenset({KnowledgeDocumentStatus.DRAFT}),
        )


@dataclass(frozen=True, slots=True)
class HybridRetrievalRequest:
    """All caller-supplied values needed for one hybrid read."""

    org_id: uuid.UUID
    query: str
    query_embedding: Embedding
    ticket_timestamp: datetime
    filters: RetrievalMetadataFilters = field(default_factory=RetrievalMetadataFilters)


@dataclass(frozen=True, slots=True)
class RetrievedKnowledgeChunk:
    """A candidate chunk with the document metadata needed for eligibility."""

    chunk_id: uuid.UUID
    document_id: uuid.UUID
    document_key: str
    document_version: str
    title: str
    authority: Authority
    jurisdiction_code: str
    status: KnowledgeDocumentStatus
    effective_from: datetime
    effective_to: datetime | None
    heading_path: str
    source_start: int
    source_end: int
    content: str
    embedding_model: str | None

    def __post_init__(self) -> None:
        _require_non_blank(self.document_key, "document_key")
        _require_non_blank(self.document_version, "document_version")
        _require_non_blank(self.title, "title")
        _require_non_blank(self.jurisdiction_code, "jurisdiction_code")
        _require_non_blank(self.heading_path, "heading_path")
        _require_non_blank(self.content, "content")
        if self.embedding_model is not None:
            _require_non_blank(self.embedding_model, "embedding_model")
        if type(self.source_start) is not int or self.source_start < 0:
            raise ValueError("source_start must be a non-negative integer")
        if type(self.source_end) is not int or self.source_end <= self.source_start:
            raise ValueError("source_end must be greater than source_start")
        _require_timezone_aware(self.effective_from, "effective_from")
        if self.effective_to is not None:
            _require_timezone_aware(self.effective_to, "effective_to")
            if self.effective_to <= self.effective_from:
                raise ValueError("effective_to must be after effective_from")


@dataclass(frozen=True, slots=True)
class FusedCandidate:
    """A source ID and its rank contributions before metadata eligibility."""

    chunk_id: uuid.UUID
    bm25_rank: int | None
    vector_rank: int | None
    rrf_score: float


@dataclass(frozen=True, slots=True)
class HybridRetrievalHit:
    """An eligible, citation-ready result with both raw ranks and fused score."""

    chunk: RetrievedKnowledgeChunk
    bm25_rank: int | None
    vector_rank: int | None
    rrf_score: float
    final_rank: int


class HybridSearchRepository(Protocol):
    """Read-only persistence boundary for candidate collection and enrichment."""

    async def lexical_candidate_ids(
        self, *, org_id: uuid.UUID, query: str, limit: int
    ) -> Sequence[uuid.UUID]:
        """Return BM25-ranked chunk IDs without document metadata filtering."""

    async def vector_candidate_ids(
        self, *, org_id: uuid.UUID, embedding: Embedding, limit: int
    ) -> Sequence[uuid.UUID]:
        """Return HNSW-ranked chunk IDs without document metadata filtering."""

    async def fetch_chunks(
        self, *, org_id: uuid.UUID, chunk_ids: Sequence[uuid.UUID]
    ) -> Sequence[RetrievedKnowledgeChunk]:
        """Return document metadata for every fused candidate under tenant scope."""


@dataclass(slots=True)
class HybridRetriever:
    """Collect, fuse, enrich, then eligibility-filter lexical/vector candidates."""

    repository: HybridSearchRepository

    async def retrieve(
        self, request: HybridRetrievalRequest
    ) -> tuple[HybridRetrievalHit, ...]:
        """Return eligible candidates ordered by reciprocal-rank fusion score.

        The ticket timestamp is deliberately a required request value. This
        method never reads the wall clock: historical ticket retrieval must use
        the policy version that was effective for that ticket, not today.
        """

        query = _require_non_blank(request.query, "query")
        ticket_timestamp = _normalize_ticket_timestamp(request.ticket_timestamp)
        lexical_ids, vector_ids = await asyncio.gather(
            self.repository.lexical_candidate_ids(
                org_id=request.org_id,
                query=query,
                limit=LEXICAL_CANDIDATE_LIMIT,
            ),
            self.repository.vector_candidate_ids(
                org_id=request.org_id,
                embedding=request.query_embedding,
                limit=VECTOR_CANDIDATE_LIMIT,
            ),
        )
        fused_candidates = reciprocal_rank_fusion(
            lexical_ids=lexical_ids,
            vector_ids=vector_ids,
        )
        if not fused_candidates:
            return ()

        candidate_ids = tuple(candidate.chunk_id for candidate in fused_candidates)
        chunks = await self.repository.fetch_chunks(
            org_id=request.org_id,
            chunk_ids=candidate_ids,
        )
        chunks_by_id = _chunks_by_id(chunks=chunks, candidate_ids=candidate_ids)

        hits: list[HybridRetrievalHit] = []
        for candidate in fused_candidates:
            chunk = chunks_by_id[candidate.chunk_id]
            if not _matches_metadata_filters(
                chunk=chunk,
                filters=request.filters,
                query_embedding=request.query_embedding,
                ticket_timestamp=ticket_timestamp,
            ):
                continue
            hits.append(
                HybridRetrievalHit(
                    chunk=chunk,
                    bm25_rank=candidate.bm25_rank,
                    vector_rank=candidate.vector_rank,
                    rrf_score=candidate.rrf_score,
                    final_rank=len(hits) + 1,
                )
            )
        return tuple(hits)


def reciprocal_rank_fusion(
    *,
    lexical_ids: Sequence[uuid.UUID],
    vector_ids: Sequence[uuid.UUID],
) -> tuple[FusedCandidate, ...]:
    """Fuse up to 30 BM25 and 30 vector candidates using ``1 / (60 + rank)``."""

    lexical_ranks = _ranked_candidate_ids(
        candidate_ids=lexical_ids,
        limit=LEXICAL_CANDIDATE_LIMIT,
        channel_name="lexical",
    )
    vector_ranks = _ranked_candidate_ids(
        candidate_ids=vector_ids,
        limit=VECTOR_CANDIDATE_LIMIT,
        channel_name="vector",
    )
    candidates: list[FusedCandidate] = []
    for chunk_id in lexical_ranks.keys() | vector_ranks.keys():
        bm25_rank = lexical_ranks.get(chunk_id)
        vector_rank = vector_ranks.get(chunk_id)
        rrf_score = sum(
            1 / (RRF_K + rank) for rank in (bm25_rank, vector_rank) if rank is not None
        )
        candidates.append(
            FusedCandidate(
                chunk_id=chunk_id,
                bm25_rank=bm25_rank,
                vector_rank=vector_rank,
                rrf_score=rrf_score,
            )
        )
    return tuple(
        sorted(
            candidates,
            key=lambda candidate: (
                -candidate.rrf_score,
                min(
                    rank
                    for rank in (candidate.bm25_rank, candidate.vector_rank)
                    if rank is not None
                ),
                str(candidate.chunk_id),
            ),
        )
    )


class AsyncpgHybridSearchRepository:
    """PostgreSQL adapter using GIN and HNSW candidate queries.

    The caller owns the transaction and must establish RLS before constructing
    this adapter. ``org_id`` remains a bound predicate in every query as a
    defence in depth measure. No document metadata predicate appears in the
    candidate SQL; it is intentionally applied by ``HybridRetriever`` after
    fusion.
    """

    def __init__(self, connection: asyncpg.Connection) -> None:
        self._connection = connection

    async def lexical_candidate_ids(
        self, *, org_id: uuid.UUID, query: str, limit: int
    ) -> tuple[uuid.UUID, ...]:
        _validate_candidate_limit(limit, LEXICAL_CANDIDATE_LIMIT)
        rows = await self._connection.fetch(
            """
            WITH query_terms AS (
                SELECT websearch_to_tsquery('english', $2) AS value
            )
            SELECT chunk.id
            FROM kb_chunks AS chunk
            CROSS JOIN query_terms
            WHERE chunk.org_id = $1
              AND chunk.content_tsv @@ query_terms.value
            ORDER BY ts_rank_cd(chunk.content_tsv, query_terms.value) DESC
            LIMIT $3
            """,
            org_id,
            query,
            limit,
        )
        return _candidate_ids_from_rows(rows, channel_name="lexical")

    async def vector_candidate_ids(
        self, *, org_id: uuid.UUID, embedding: Embedding, limit: int
    ) -> tuple[uuid.UUID, ...]:
        _validate_candidate_limit(limit, VECTOR_CANDIDATE_LIMIT)
        rows = await self._connection.fetch(
            """
            SELECT chunk.id
            FROM kb_chunks AS chunk
            WHERE chunk.org_id = $1
              AND chunk.embedding IS NOT NULL
            ORDER BY chunk.embedding <=> $2::text::halfvec
            LIMIT $3
            """,
            org_id,
            embedding.as_halfvec_literal(),
            limit,
        )
        return _candidate_ids_from_rows(rows, channel_name="vector")

    async def fetch_chunks(
        self, *, org_id: uuid.UUID, chunk_ids: Sequence[uuid.UUID]
    ) -> tuple[RetrievedKnowledgeChunk, ...]:
        if not chunk_ids:
            return ()
        rows = await self._connection.fetch(
            """
            SELECT
                chunk.id AS chunk_id,
                document.id AS document_id,
                document.document_key,
                document.version AS document_version,
                document.title,
                document.authority,
                document.jurisdiction_code,
                document.status,
                document.effective_from,
                document.effective_to,
                chunk.heading_path,
                chunk.source_start,
                chunk.source_end,
                chunk.content,
                chunk.embedding_model
            FROM kb_chunks AS chunk
            JOIN kb_documents AS document
              ON document.org_id = chunk.org_id
             AND document.id = chunk.kb_document_id
            WHERE chunk.org_id = $1
              AND chunk.id = ANY($2::uuid[])
            """,
            org_id,
            list(chunk_ids),
        )
        return tuple(_chunk_from_row(row) for row in rows)


def _ranked_candidate_ids(
    *, candidate_ids: Sequence[uuid.UUID], limit: int, channel_name: str
) -> dict[uuid.UUID, int]:
    if len(candidate_ids) > limit:
        raise RetrievalRepositoryError(
            f"{channel_name} candidate query returned more than {limit} rows"
        )
    ranks: dict[uuid.UUID, int] = {}
    for rank, chunk_id in enumerate(candidate_ids, start=1):
        if not isinstance(chunk_id, uuid.UUID):
            raise RetrievalRepositoryError(
                f"{channel_name} candidate query returned an invalid chunk ID"
            )
        if chunk_id in ranks:
            raise RetrievalRepositoryError(
                f"{channel_name} candidate query returned a duplicate chunk ID"
            )
        ranks[chunk_id] = rank
    return ranks


def _chunks_by_id(
    *,
    chunks: Sequence[RetrievedKnowledgeChunk],
    candidate_ids: Sequence[uuid.UUID],
) -> dict[uuid.UUID, RetrievedKnowledgeChunk]:
    candidates = set(candidate_ids)
    chunks_by_id: dict[uuid.UUID, RetrievedKnowledgeChunk] = {}
    for chunk in chunks:
        if chunk.chunk_id not in candidates:
            raise RetrievalRepositoryError("repository returned a non-candidate chunk")
        if chunk.chunk_id in chunks_by_id:
            raise RetrievalRepositoryError("repository returned a duplicate chunk")
        chunks_by_id[chunk.chunk_id] = chunk
    missing_ids = candidates.difference(chunks_by_id)
    if missing_ids:
        raise RetrievalRepositoryError(
            "repository did not return metadata for every fused candidate"
        )
    return chunks_by_id


def _matches_metadata_filters(
    *,
    chunk: RetrievedKnowledgeChunk,
    filters: RetrievalMetadataFilters,
    query_embedding: Embedding,
    ticket_timestamp: datetime,
) -> bool:
    if chunk.embedding_model != query_embedding.model:
        return False
    if chunk.status not in filters.allowed_document_statuses:
        return False
    if (
        filters.jurisdiction_code is not None
        and chunk.jurisdiction_code != filters.jurisdiction_code
    ):
        return False
    if filters.authorities is not None and chunk.authority not in filters.authorities:
        return False
    if chunk.effective_from > ticket_timestamp:
        return False
    return chunk.effective_to is None or ticket_timestamp < chunk.effective_to


def _normalize_ticket_timestamp(ticket_timestamp: datetime) -> datetime:
    _require_timezone_aware(ticket_timestamp, "ticket_timestamp")
    return ticket_timestamp.astimezone(UTC)


def _validate_candidate_limit(limit: int, expected_limit: int) -> None:
    if type(limit) is not int or limit != expected_limit:
        raise ValueError(f"candidate limit must be exactly {expected_limit}")


def _candidate_ids_from_rows(
    rows: Sequence[asyncpg.Record], *, channel_name: str
) -> tuple[uuid.UUID, ...]:
    candidate_ids: list[uuid.UUID] = []
    for row in rows:
        chunk_id = row["id"]
        if not isinstance(chunk_id, uuid.UUID):
            raise RetrievalRepositoryError(
                f"{channel_name} candidate query returned an invalid chunk ID"
            )
        candidate_ids.append(chunk_id)
    return tuple(candidate_ids)


def _chunk_from_row(row: asyncpg.Record) -> RetrievedKnowledgeChunk:
    chunk_id = row["chunk_id"]
    document_id = row["document_id"]
    document_key = row["document_key"]
    document_version = row["document_version"]
    title = row["title"]
    authority_value = row["authority"]
    jurisdiction_code = row["jurisdiction_code"]
    status_value = row["status"]
    effective_from = row["effective_from"]
    effective_to = row["effective_to"]
    heading_path = row["heading_path"]
    source_start = row["source_start"]
    source_end = row["source_end"]
    content = row["content"]
    embedding_model = row["embedding_model"]

    if not isinstance(chunk_id, uuid.UUID) or not isinstance(document_id, uuid.UUID):
        raise RetrievalRepositoryError("knowledge query returned an invalid identity")
    if not all(
        isinstance(value, str)
        for value in (
            document_key,
            document_version,
            title,
            authority_value,
            jurisdiction_code,
            status_value,
            heading_path,
            content,
        )
    ):
        raise RetrievalRepositoryError("knowledge query returned invalid text metadata")
    if not isinstance(effective_from, datetime) or (
        effective_to is not None and not isinstance(effective_to, datetime)
    ):
        raise RetrievalRepositoryError(
            "knowledge query returned invalid effective dates"
        )
    if type(source_start) is not int or type(source_end) is not int:
        raise RetrievalRepositoryError("knowledge query returned invalid source spans")
    if embedding_model is not None and not isinstance(embedding_model, str):
        raise RetrievalRepositoryError(
            "knowledge query returned an invalid embedding model"
        )
    try:
        authority = Authority(authority_value)
        status = KnowledgeDocumentStatus(status_value)
    except ValueError as error:
        raise RetrievalRepositoryError(
            "knowledge query returned an unknown enum"
        ) from error
    return RetrievedKnowledgeChunk(
        chunk_id=chunk_id,
        document_id=document_id,
        document_key=document_key,
        document_version=document_version,
        title=title,
        authority=authority,
        jurisdiction_code=jurisdiction_code,
        status=status,
        effective_from=effective_from,
        effective_to=effective_to,
        heading_path=heading_path,
        source_start=source_start,
        source_end=source_end,
        content=content,
        embedding_model=embedding_model,
    )


def _require_non_blank(value: str, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must be a non-blank string")
    return value.strip()


def _require_timezone_aware(value: datetime, field_name: str) -> None:
    if (
        not isinstance(value, datetime)
        or value.tzinfo is None
        or value.utcoffset() is None
    ):
        raise ValueError(f"{field_name} must be timezone-aware")
