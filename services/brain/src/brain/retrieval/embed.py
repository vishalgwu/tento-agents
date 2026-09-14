"""OpenAI embedding generation with deterministic cache and storage boundaries.

The module has no database authority. It turns already-authorised, redacted
retrieval text into validated vectors and returns a parameter-safe halfvec
literal for a future repository to bind to PostgreSQL. Callers must enforce
tenant scope and document lifecycle eligibility before invoking a provider.
"""

from __future__ import annotations

import asyncio
import hashlib
import math
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Final, Protocol

from openai import AsyncOpenAI


EMBEDDING_MODEL: Final = "text-embedding-3-small"
EMBEDDING_DIMENSIONS: Final = 1536
MAX_EMBEDDING_BATCH_SIZE: Final = 128


class EmbeddingProvider(Protocol):
    """The narrow provider contract used by embedding orchestration."""

    async def embed(
        self,
        *,
        texts: Sequence[str],
        model: str,
        dimensions: int,
    ) -> Sequence[Sequence[float]]:
        """Return one embedding, in input order, for every text."""


class EmbeddingCache(Protocol):
    """A cache keyed only by a text digest and embedding-model identifier."""

    async def get(self, cache_key: str) -> Embedding | None:
        """Return a cached embedding, if available."""

    async def set(self, cache_key: str, embedding: Embedding) -> None:
        """Store a validated embedding under ``cache_key``."""


@dataclass(frozen=True, slots=True)
class Embedding:
    """A validated 1536-dimensional vector for the existing halfvec schema."""

    cache_key: str
    model: str
    values: tuple[float, ...]

    def __post_init__(self) -> None:
        if not self.cache_key:
            raise ValueError("embedding cache_key must not be blank")
        if not self.model.strip():
            raise ValueError("embedding model must not be blank")
        if len(self.values) != EMBEDDING_DIMENSIONS:
            raise ValueError(
                f"embedding dimension must be {EMBEDDING_DIMENSIONS}, got {len(self.values)}"
            )
        if not all(math.isfinite(value) for value in self.values):
            raise ValueError("embedding values must be finite")

    def as_halfvec_literal(self) -> str:
        """Serialize for a *bound* PostgreSQL parameter cast to ``halfvec``.

        The database schema performs the float16 conversion when the parameter
        is bound as ``$n::halfvec``. This method never interpolates SQL and must
        not be used to construct a query string.
        """

        return "[" + ",".join(format(value, ".9g") for value in self.values) + "]"


class InMemoryEmbeddingCache:
    """Process-local cache for a worker's embedding batch path.

    Keys contain only ``sha256(text)`` plus the model name. A future durable
    cache adapter may implement ``EmbeddingCache`` without changing callers.
    """

    def __init__(self) -> None:
        self._entries: dict[str, Embedding] = {}
        self._lock = asyncio.Lock()

    async def get(self, cache_key: str) -> Embedding | None:
        async with self._lock:
            return self._entries.get(cache_key)

    async def set(self, cache_key: str, embedding: Embedding) -> None:
        if embedding.cache_key != cache_key:
            raise ValueError("embedding cache key does not match the stored embedding")
        async with self._lock:
            self._entries[cache_key] = embedding


@dataclass(slots=True)
class OpenAIEmbeddingProvider:
    """Adapter for OpenAI's asynchronous embeddings endpoint."""

    client: AsyncOpenAI

    async def embed(
        self,
        *,
        texts: Sequence[str],
        model: str,
        dimensions: int,
    ) -> Sequence[Sequence[float]]:
        response = await self.client.embeddings.create(
            input=list(texts),
            model=model,
            dimensions=dimensions,
            encoding_format="float",
        )
        return tuple(tuple(item.embedding) for item in response.data)


def embedding_cache_key(text: str, model: str = EMBEDDING_MODEL) -> str:
    """Return a stable cache key from the exact text bytes and model identifier.

    The text itself is intentionally absent from the key. Whitespace is not
    normalized: any content change must produce a new embedding and cache entry.
    """

    _require_non_blank_text(text)
    normalized_model = _require_model(model)
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
    return f"sha256:{digest}:model:{normalized_model}"


async def embed_texts(
    *,
    provider: EmbeddingProvider,
    cache: EmbeddingCache,
    texts: Sequence[str],
    model: str = EMBEDDING_MODEL,
) -> tuple[Embedding, ...]:
    """Embed text in batches, deduplicating and caching by digest plus model.

    Text is preserved exactly for model input and is never written to a cache
    key or exception message. The provider is called only for cache misses;
    duplicate text in one request shares a single provider result.
    """

    normalized_model = _require_model(model)
    if not texts:
        return ()

    keyed_texts: list[tuple[str, str]] = []
    unique_missing: dict[str, str] = {}
    resolved: dict[str, Embedding] = {}

    for text in texts:
        _require_non_blank_text(text)
        cache_key = embedding_cache_key(text, normalized_model)
        keyed_texts.append((cache_key, text))
        if cache_key in resolved or cache_key in unique_missing:
            continue
        cached = await cache.get(cache_key)
        if cached is None:
            unique_missing[cache_key] = text
            continue
        _validate_cached_embedding(cached, cache_key, normalized_model)
        resolved[cache_key] = cached

    missing_items = tuple(unique_missing.items())
    for batch_start in range(0, len(missing_items), MAX_EMBEDDING_BATCH_SIZE):
        batch = missing_items[batch_start : batch_start + MAX_EMBEDDING_BATCH_SIZE]
        vectors = await provider.embed(
            texts=tuple(text for _, text in batch),
            model=normalized_model,
            dimensions=EMBEDDING_DIMENSIONS,
        )
        if len(vectors) != len(batch):
            raise ValueError("embedding provider returned an unexpected vector count")

        for (cache_key, _), vector in zip(batch, vectors, strict=True):
            embedding = Embedding(
                cache_key=cache_key,
                model=normalized_model,
                values=tuple(float(value) for value in vector),
            )
            await cache.set(cache_key, embedding)
            resolved[cache_key] = embedding

    return tuple(resolved[cache_key] for cache_key, _ in keyed_texts)


def _require_non_blank_text(text: str) -> None:
    if not isinstance(text, str) or not text.strip():
        raise ValueError("embedding text must be a non-blank string")


def _require_model(model: str) -> str:
    if not isinstance(model, str) or not model.strip():
        raise ValueError("embedding model must be a non-blank string")
    return model.strip()


def _validate_cached_embedding(
    embedding: Embedding,
    expected_cache_key: str,
    expected_model: str,
) -> None:
    if embedding.cache_key != expected_cache_key:
        raise ValueError("cached embedding key does not match its lookup key")
    if embedding.model != expected_model:
        raise ValueError("cached embedding model does not match the requested model")
