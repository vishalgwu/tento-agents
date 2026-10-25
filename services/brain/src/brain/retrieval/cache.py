"""Tenant-scoped Redis embedding cache; never a policy or answer cache."""

from __future__ import annotations

import json
from typing import Protocol
from uuid import UUID

from redis.exceptions import RedisError

from brain.retrieval.embed import EMBEDDING_DIMENSIONS, Embedding


class CacheRedis(Protocol):
    async def get(self, name: str) -> bytes | str | None: ...

    async def setex(self, name: str, time: int, value: str) -> object: ...


class RedisEmbeddingCache:
    """Cache only validated vectors and model/digest identities, never text.

    Tenant identity comes from the server. Redis failures become misses. Cached
    vectors do not bypass source lifecycle, jurisdiction or authority checks.
    """

    def __init__(
        self, client: CacheRedis, *, org_id: UUID, ttl_seconds: int = 86400
    ) -> None:
        if not 60 <= ttl_seconds <= 604800:
            raise ValueError("cache TTL must be between one minute and seven days")
        self.client = client
        self.org_id = org_id
        self.ttl_seconds = ttl_seconds

    def key(self, cache_key: str) -> str:
        if not cache_key or len(cache_key) > 256:
            raise ValueError("invalid embedding cache key")
        return f"tento:embedding:v1:{self.org_id}:{cache_key}"

    async def get(self, cache_key: str) -> Embedding | None:
        try:
            raw = await self.client.get(self.key(cache_key))
            if raw is None or len(raw) > 131072:
                return None
            value = json.loads(raw)
            if not isinstance(value, dict) or value.get("cache_key") != cache_key:
                return None
            if not isinstance(value.get("model"), str) or not isinstance(
                value.get("values"), list
            ):
                return None
            if len(value["values"]) != EMBEDDING_DIMENSIONS:
                return None
            if (
                ":model:" in cache_key
                and value["model"] != cache_key.rsplit(":model:", 1)[1]
            ):
                return None
            return Embedding(
                cache_key=cache_key,
                model=value["model"],
                values=tuple(float(item) for item in value["values"]),
            )
        except (RedisError, ValueError, TypeError, KeyError, OverflowError):
            return None

    async def set(self, cache_key: str, embedding: Embedding) -> None:
        if embedding.cache_key != cache_key:
            raise ValueError("cache key does not match embedding")
        value = json.dumps(
            {
                "cache_key": cache_key,
                "model": embedding.model,
                "values": embedding.values,
            },
            allow_nan=False,
        )
        try:
            await self.client.setex(self.key(cache_key), self.ttl_seconds, value)
        except RedisError:
            return
