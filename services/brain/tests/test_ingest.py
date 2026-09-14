"""Regression coverage for safe, versioned knowledge ingestion."""

from __future__ import annotations

import hashlib
import uuid
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path

import pytest

from brain.retrieval.embed import EMBEDDING_DIMENSIONS, InMemoryEmbeddingCache
from brain.retrieval.ingest import (
    Authority,
    AuthorityValidationError,
    DocumentEligibilityError,
    DocumentVersionConflict,
    EmbeddedChunk,
    ExistingKnowledgeDocument,
    FrontMatterValidationError,
    KnowledgeDocument,
    KnowledgeIngestor,
    parse_knowledge_document,
)


@dataclass
class FakeEmbeddingProvider:
    calls: list[tuple[tuple[str, ...], str, int]] = field(default_factory=list)

    async def embed(
        self,
        *,
        texts: Sequence[str],
        model: str,
        dimensions: int,
    ) -> tuple[tuple[float, ...], ...]:
        self.calls.append((tuple(texts), model, dimensions))
        return tuple((0.5,) * dimensions for _ in texts)


@dataclass
class FakeKnowledgeRepository:
    existing: ExistingKnowledgeDocument | None = None
    documents: list[tuple[uuid.UUID, KnowledgeDocument, str]] = field(
        default_factory=list
    )
    chunks: list[EmbeddedChunk] = field(default_factory=list)

    async def get_document(
        self,
        *,
        org_id: uuid.UUID,
        document_key: str,
        version: str,
    ) -> ExistingKnowledgeDocument | None:
        return self.existing

    async def upsert_document_and_chunks(
        self,
        *,
        org_id: uuid.UUID,
        document: KnowledgeDocument,
        database_status: str,
        chunks: Sequence[EmbeddedChunk],
    ) -> uuid.UUID:
        document_id = uuid.uuid5(
            uuid.NAMESPACE_URL, f"{org_id}:{document.document_key}"
        )
        self.documents.append((document_id, document, database_status))
        self.chunks.extend(chunks)
        return document_id


def _knowledge_markdown(
    *,
    authority: str = "lease",
    status: str = "active",
    production_eligible: str = "true",
    version: str = "1",
    body: str = "# Lease fixture\n\n## §7.3 Maintenance\nOwner pays normal wear and tear.\n",
) -> str:
    return f"""---
id: LEASE-TEST-01
version: "{version}"
effective_from: "2026-01-01"
effective_to: null
jurisdiction: "US-VA"
authority: {authority}
status: {status}
production_eligible: {production_eligible}
source_uri: "project://tests/LEASE-TEST-01"
---
{body}"""


@pytest.mark.asyncio
async def test_ingestion_parses_chunks_embeds_and_upserts_a_new_document() -> None:
    repository = FakeKnowledgeRepository()
    provider = FakeEmbeddingProvider()
    ingestor = KnowledgeIngestor(
        repository=repository,
        embedding_provider=provider,
        embedding_cache=InMemoryEmbeddingCache(),
        org_id=uuid.UUID("33333333-3333-3333-3333-333333333333"),
    )
    markdown = _knowledge_markdown()

    result = await ingestor.ingest_markdown(
        markdown=markdown,
        source_path=Path("knowledge/leases/lease-template.md"),
    )

    assert result.skipped_unchanged is False
    assert result.chunk_count == 1
    assert repository.documents[0][1].authority is Authority.LEASE
    assert repository.documents[0][2] == "active"
    assert provider.calls[0][2] == EMBEDDING_DIMENSIONS
    assert (
        repository.chunks[0].chunk.content_sha256
        == hashlib.sha256(
            repository.chunks[0].chunk.content.encode("utf-8")
        ).hexdigest()
    )
    assert len(repository.chunks[0].embedding.values) == EMBEDDING_DIMENSIONS


@pytest.mark.asyncio
async def test_ingestion_skips_unchanged_content_before_chunking_or_embedding() -> None:
    markdown = _knowledge_markdown()
    document = parse_knowledge_document(
        markdown=markdown,
        source_path=Path("knowledge/leases/lease-template.md"),
    )
    existing = ExistingKnowledgeDocument(
        document_id=uuid.UUID("44444444-4444-4444-4444-444444444444"),
        content_sha256=document.content_sha256,
    )
    repository = FakeKnowledgeRepository(existing=existing)
    provider = FakeEmbeddingProvider()
    ingestor = KnowledgeIngestor(
        repository=repository,
        embedding_provider=provider,
        embedding_cache=InMemoryEmbeddingCache(),
        org_id=uuid.UUID("55555555-5555-5555-5555-555555555555"),
    )

    result = await ingestor.ingest_markdown(
        markdown=markdown,
        source_path=Path("knowledge/leases/lease-template.md"),
    )

    assert result.skipped_unchanged is True
    assert result.chunk_count == 0
    assert result.document_id == existing.document_id
    assert provider.calls == []
    assert repository.documents == []


@pytest.mark.asyncio
async def test_ingestion_rejects_changed_content_for_an_existing_version() -> None:
    markdown = _knowledge_markdown()
    repository = FakeKnowledgeRepository(
        existing=ExistingKnowledgeDocument(
            document_id=uuid.UUID("66666666-6666-6666-6666-666666666666"),
            content_sha256="0" * 64,
        )
    )
    provider = FakeEmbeddingProvider()
    ingestor = KnowledgeIngestor(
        repository=repository,
        embedding_provider=provider,
        embedding_cache=InMemoryEmbeddingCache(),
        org_id=uuid.UUID("77777777-7777-7777-7777-777777777777"),
    )

    with pytest.raises(DocumentVersionConflict, match="new version"):
        await ingestor.ingest_markdown(
            markdown=markdown,
            source_path=Path("knowledge/leases/lease-template.md"),
        )

    assert provider.calls == []
    assert repository.documents == []


def test_invalid_authority_fails_loudly_without_a_default() -> None:
    markdown = _knowledge_markdown(authority="property_policy")

    with pytest.raises(AuthorityValidationError, match="property_policy"):
        parse_knowledge_document(
            markdown=markdown,
            source_path=Path("knowledge/leases/lease-template.md"),
        )


def test_front_matter_requires_an_explicit_effective_to_value() -> None:
    markdown = _knowledge_markdown().replace("effective_to: null\n", "")

    with pytest.raises(FrontMatterValidationError, match="effective_to"):
        parse_knowledge_document(
            markdown=markdown,
            source_path=Path("knowledge/leases/lease-template.md"),
        )


def test_all_current_knowledge_fixtures_satisfy_the_ingestion_contract() -> None:
    repository_root = Path(__file__).resolve().parents[3]
    fixture_paths = tuple(sorted((repository_root / "knowledge").rglob("*.md")))
    content_paths = tuple(path for path in fixture_paths if path.name != "README.md")

    documents = tuple(
        parse_knowledge_document(
            markdown=path.read_text(encoding="utf-8"), source_path=path
        )
        for path in content_paths
    )

    assert len(documents) == 11
    assert all(document.source_status == "temporary_fixture" for document in documents)
    assert all(document.production_eligible is False for document in documents)
    assert {document.authority for document in documents} == set(Authority)


@pytest.mark.asyncio
async def test_temporary_fixture_requires_explicit_evaluation_mode() -> None:
    markdown = _knowledge_markdown(
        status="temporary_fixture", production_eligible="false"
    )
    repository = FakeKnowledgeRepository()
    provider = FakeEmbeddingProvider()
    production_ingestor = KnowledgeIngestor(
        repository=repository,
        embedding_provider=provider,
        embedding_cache=InMemoryEmbeddingCache(),
        org_id=uuid.UUID("88888888-8888-8888-8888-888888888888"),
    )

    with pytest.raises(DocumentEligibilityError, match="temporary_fixture"):
        await production_ingestor.ingest_markdown(
            markdown=markdown,
            source_path=Path("knowledge/leases/lease-template.md"),
        )

    evaluation_ingestor = KnowledgeIngestor(
        repository=repository,
        embedding_provider=provider,
        embedding_cache=InMemoryEmbeddingCache(),
        org_id=uuid.UUID("99999999-9999-9999-9999-999999999999"),
        allow_temporary_fixtures=True,
    )
    result = await evaluation_ingestor.ingest_markdown(
        markdown=markdown,
        source_path=Path("knowledge/leases/lease-template.md"),
    )

    assert result.skipped_unchanged is False
    assert repository.documents[0][2] == "draft"
