"""Import an explicitly production-eligible Markdown source and policy config.

Usage: python -m brain.ingest --org-id UUID --source path.md --claims policy.json
DATABASE_URL and OPENAI_API_KEY are read from the environment, never CLI flags.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
from pathlib import Path
from uuid import UUID, uuid5
from typing import cast
from redis.asyncio import Redis

from brain.retrieval.cache import CacheRedis, RedisEmbeddingCache

import asyncpg  # type: ignore[import-untyped]
from openai import AsyncOpenAI
from pydantic import BaseModel, ConfigDict, Field

from brain.retrieval.embed import InMemoryEmbeddingCache, OpenAIEmbeddingProvider
from brain.retrieval.ingest import (
    AsyncpgKnowledgeRepository,
    KnowledgeIngestor,
    parse_knowledge_document,
)


class SourcePolicy(BaseModel):
    """Immutable source-backed policy configuration, not model feedback."""

    model_config = ConfigDict(extra="forbid", strict=True)
    policy_key: str = Field(min_length=1, max_length=200)
    outcome: str = Field(min_length=1, max_length=2000)
    source_start: int = Field(ge=0)
    source_end: int = Field(gt=0)
    source_text: str = Field(min_length=1)


def load_source_policies(path: Path, markdown: str) -> tuple[SourcePolicy, ...]:
    decoded = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(decoded, list) or len(decoded) > 64:
        raise ValueError("policy configuration must be a list of at most 64 entries")
    values = tuple(SourcePolicy.model_validate(item) for item in decoded)
    identities = set()
    for item in values:
        if not item.policy_key.strip() or not item.outcome.strip():
            raise ValueError("policy values must be nonblank")
        if (
            item.source_end <= item.source_start
            or markdown[item.source_start : item.source_end] != item.source_text
        ):
            raise ValueError("policy text must exactly match its source span")
        identity = (item.policy_key, item.outcome, item.source_start, item.source_end)
        if identity in identities:
            raise ValueError("duplicate policy configuration")
        identities.add(identity)
    return values


async def ingest_source(*, org_id: UUID, source: Path, claims: Path | None) -> None:
    markdown = source.read_text(encoding="utf-8")
    document = parse_knowledge_document(markdown=markdown, source_path=source)
    if document.source_status != "active" or not document.production_eligible:
        raise ValueError(
            "only active, production-eligible source versions can be imported"
        )
    policies = load_source_policies(claims, markdown) if claims else ()
    if policies and document.authority.value == "vendor_contract":
        raise ValueError(
            "auditable policy configuration must use statute, lease, or internal_sop authority"
        )
    database_url = os.environ.get("DATABASE_URL", "").replace(
        "postgresql+asyncpg://", "postgresql://", 1
    )
    if not database_url or not os.environ.get("OPENAI_API_KEY", "").strip():
        raise ValueError("DATABASE_URL and OPENAI_API_KEY must be configured")
    connection = await asyncpg.connect(database_url)
    cache_client = (
        Redis.from_url(
            os.environ["REDIS_URL"], socket_connect_timeout=2, socket_timeout=2
        )
        if os.environ.get("REDIS_URL")
        else None
    )
    cache = (
        RedisEmbeddingCache(cast(CacheRedis, cache_client), org_id=org_id)
        if cache_client is not None
        else InMemoryEmbeddingCache()
    )
    try:
        async with connection.transaction():
            await connection.execute(
                "SELECT set_config('app.current_org_id',$1,true)", str(org_id)
            )
            await connection.execute(
                "SELECT set_config('app.current_person_id','',true)"
            )
            await connection.execute(
                "SELECT set_config('app.current_role','operations_admin',true)"
            )
            async with AsyncOpenAI() as client:
                result = await KnowledgeIngestor(
                    repository=AsyncpgKnowledgeRepository(connection),
                    embedding_provider=OpenAIEmbeddingProvider(client),
                    embedding_cache=cache,
                    org_id=org_id,
                ).ingest_file(source)
            if result.document_id is None:
                raise ValueError("source document identity was not persisted")
            existing = await connection.fetch(
                "SELECT policy_key,outcome,source_start,source_end FROM public.kb_policy_claims WHERE org_id=$1 AND kb_document_id=$2",
                org_id,
                result.document_id,
            )
            previous = {
                (
                    row["policy_key"],
                    row["outcome"],
                    row["source_start"],
                    row["source_end"],
                )
                for row in existing
            }
            expected = {
                (item.policy_key, item.outcome, item.source_start, item.source_end)
                for item in policies
            }
            if previous and previous != expected:
                raise ValueError(
                    "policy configuration changed; publish a new source version"
                )
            for item in policies:
                identifier = uuid5(
                    result.document_id,
                    json.dumps(
                        [
                            item.policy_key,
                            item.outcome,
                            item.source_start,
                            item.source_end,
                        ],
                        ensure_ascii=True,
                    ),
                )
                await connection.execute(
                    """INSERT INTO public.kb_policy_claims(id,org_id,kb_document_id,policy_key,outcome,source_start,source_end)
                    VALUES($1,$2,$3,$4,$5,$6,$7) ON CONFLICT(id) DO NOTHING""",
                    identifier,
                    org_id,
                    result.document_id,
                    item.policy_key,
                    item.outcome,
                    item.source_start,
                    item.source_end,
                )
        print(
            f"Imported source version; document_id={result.document_id}; chunks={result.chunk_count}; policies={len(policies)}; unchanged={result.skipped_unchanged}"
        )
    finally:
        await connection.close()
        if cache_client is not None:
            await cache_client.aclose()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--org-id", required=True, type=UUID)
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--claims", type=Path)
    args = parser.parse_args()
    try:
        asyncio.run(
            ingest_source(org_id=args.org_id, source=args.source, claims=args.claims)
        )
    except (ValueError, OSError) as error:
        parser.exit(1, f"Source import rejected: {error}\n")


if __name__ == "__main__":
    main()
