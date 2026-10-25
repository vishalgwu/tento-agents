"""Cache isolation, poisoned-value rejection and optional-store degradation."""

from uuid import uuid4

import pytest
from redis.exceptions import ConnectionError

from brain.retrieval.cache import RedisEmbeddingCache
from brain.retrieval.embed import EMBEDDING_DIMENSIONS, Embedding


class FakeRedis:
    def __init__(self) -> None:
        self.values: dict[str, str] = {}
        self.ttls: dict[str, int] = {}
        self.fail = False

    async def get(self, name: str) -> str | None:
        if self.fail:
            raise ConnectionError("unavailable")
        return self.values.get(name)

    async def setex(self, name: str, time: int, value: str) -> object:
        if self.fail:
            raise ConnectionError("unavailable")
        self.values[name] = value
        self.ttls[name] = time
        return True


@pytest.mark.asyncio
async def test_tenant_isolation_ttl_and_poisoned_cache() -> None:
    redis = FakeRedis()
    first = RedisEmbeddingCache(redis, org_id=uuid4(), ttl_seconds=60)
    second = RedisEmbeddingCache(redis, org_id=uuid4(), ttl_seconds=60)
    embedding = Embedding("digest:model", "model", (0.1,) * EMBEDDING_DIMENSIONS)
    await first.set(embedding.cache_key, embedding)
    assert await first.get(embedding.cache_key) == embedding
    assert await second.get(embedding.cache_key) is None
    assert redis.ttls[first.key(embedding.cache_key)] == 60
    for poisoned in (
        "not-json",
        "[]",
        '{"cache_key":"wrong"}',
        '{"cache_key":"digest:model","model":"model","values":[1]}',
    ):
        redis.values[first.key(embedding.cache_key)] = poisoned
        assert await first.get(embedding.cache_key) is None


@pytest.mark.asyncio
async def test_outage_is_a_miss_and_mismatched_writes_are_rejected() -> None:
    redis = FakeRedis()
    cache = RedisEmbeddingCache(redis, org_id=uuid4())
    embedding = Embedding("digest:model", "model", (0.1,) * EMBEDDING_DIMENSIONS)
    redis.fail = True
    assert await cache.get(embedding.cache_key) is None
    await cache.set(embedding.cache_key, embedding)
    with pytest.raises(ValueError, match="does not match"):
        await cache.set("wrong", embedding)


def test_cache_ttl_is_bounded() -> None:
    for ttl in (0, 59, 604801):
        with pytest.raises(ValueError):
            RedisEmbeddingCache(FakeRedis(), org_id=uuid4(), ttl_seconds=ttl)
