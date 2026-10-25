"""Opt-in paired miss/hit benchmark against OpenAI embeddings and hosted Redis."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import time
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import TypedDict, cast
from uuid import uuid4

from dotenv import load_dotenv
from openai import AsyncOpenAI
from redis.asyncio import Redis

from brain.retrieval.cache import CacheRedis, RedisEmbeddingCache
from brain.retrieval.embed import (
    OpenAIEmbeddingProvider,
    embed_texts,
    embedding_cache_key,
)
from evals.model_benchmark import ROOT, percentile


class CachePair(TypedDict):
    case_id: str
    miss_ms: float
    hit_ms: float
    repeat_provider_calls: int


class CountedProvider(OpenAIEmbeddingProvider):
    calls: int = 0

    async def embed(
        self, *, texts: Sequence[str], model: str, dimensions: int
    ) -> Sequence[Sequence[float]]:
        self.calls += 1
        return await super().embed(texts=texts, model=model, dimensions=dimensions)


async def benchmark(samples: int) -> dict[str, object]:
    if not 1 <= samples <= 50:
        raise ValueError("samples must be in [1, 50]")
    if not os.environ.get("OPENAI_API_KEY") or not os.environ.get("REDIS_URL"):
        raise ValueError("OPENAI_API_KEY and REDIS_URL are required")
    redis = Redis.from_url(
        os.environ["REDIS_URL"], socket_connect_timeout=5, socket_timeout=5
    )
    cache = RedisEmbeddingCache(cast(CacheRedis, redis), org_id=uuid4(), ttl_seconds=60)
    # Random run marker ensures no pre-existing cache entries can bias misses.
    marker = uuid4().hex
    texts = [
        f"Synthetic maintenance evaluation {marker}: bathroom fan rattles; case {index}."
        for index in range(samples)
    ]
    keys = [cache.key(embedding_cache_key(value)) for value in texts]
    pairs: list[CachePair] = []
    try:
        async with AsyncOpenAI(max_retries=0, timeout=15) as client:
            provider = CountedProvider(client)
            for index, value in enumerate(texts):
                before = provider.calls
                started = time.perf_counter()
                first = await embed_texts(
                    provider=provider, cache=cache, texts=(value,)
                )
                miss_ms = (time.perf_counter() - started) * 1000
                miss_calls = provider.calls - before
                before = provider.calls
                started = time.perf_counter()
                second = await embed_texts(
                    provider=provider, cache=cache, texts=(value,)
                )
                hit_ms = (time.perf_counter() - started) * 1000
                if first != second or miss_calls != 1:
                    raise RuntimeError("paired embedding verification failed")
                pairs.append(
                    {
                        "case_id": f"cache-{index + 1:02}",
                        "miss_ms": round(miss_ms, 3),
                        "hit_ms": round(hit_ms, 3),
                        "repeat_provider_calls": provider.calls - before,
                    }
                )
    finally:
        try:
            await redis.delete(*keys)
        finally:
            await redis.aclose()
    repeat_calls = sum(int(row["repeat_provider_calls"]) for row in pairs)
    miss = [float(row["miss_ms"]) for row in pairs]
    hit = [float(row["hit_ms"]) for row in pairs]
    return {
        "scope": "paired synthetic single-text embedding misses/hits; not resident request latency",
        "created_at": datetime.now(UTC).isoformat(),
        "samples": samples,
        "model": "text-embedding-3-small",
        "dimensions": 1536,
        "cache_source_sha256": hashlib.sha256(
            (ROOT / "services/brain/src/brain/retrieval/cache.py").read_bytes()
        ).hexdigest(),
        "ttl_seconds": 60,
        "concurrency": 1,
        "cold_provider_calls": samples,
        "repeat_provider_calls": repeat_calls,
        "repeat_call_reduction_fraction": 1 - repeat_calls / samples,
        "p50_miss_ms": percentile(miss, 0.5),
        "p95_miss_ms": percentile(miss, 0.95),
        "p50_hit_ms": percentile(hit, 0.5),
        "p95_hit_ms": percentile(hit, 0.95),
        "max_miss_ms": max(miss),
        "max_hit_ms": max(hit),
        "pairs": pairs,
        "limitations": [
            "Paired miss-then-hit order; not a randomized load test.",
            "Cache TTL is shortened for this test; ingestion uses a 24-hour TTL.",
            "Measures existing-input reuse only, not novel queries or end-to-end inference cost.",
            "Synthetic vectors use a random tenant namespace and are removed after the test.",
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--samples", type=int, default=20)
    parser.add_argument(
        "--output",
        type=Path,
        default=ROOT / "output/benchmarks/part2-embedding-cache.json",
    )
    args = parser.parse_args()
    if not args.live:
        parser.error(
            "--live is required; this calls OpenAI and writes temporary Redis entries"
        )
    load_dotenv(ROOT / ".env", override=False)
    try:
        result = asyncio.run(benchmark(args.samples))
    except Exception as error:
        raise SystemExit(
            f"Cache benchmark failed ({type(error).__name__}); no secret values displayed"
        ) from None
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(f"Saved paired synthetic cache measurements: {args.output}")


if __name__ == "__main__":
    main()
