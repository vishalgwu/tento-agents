"""Regression coverage for cached, halfvec-compatible embedding generation."""

from __future__ import annotations

import hashlib
from collections.abc import Sequence
from dataclasses import dataclass, field

import pytest

from brain.retrieval.embed import (
    EMBEDDING_DIMENSIONS,
    EMBEDDING_MODEL,
    Embedding,
    InMemoryEmbeddingCache,
    embed_texts,
    embedding_cache_key,
)


@dataclass
class FakeEmbeddingProvider:
    """Offline provider that exposes calls without retaining cache behavior."""

    calls: list[tuple[tuple[str, ...], str, int]] = field(default_factory=list)

    async def embed(
        self,
        *,
        texts: Sequence[str],
        model: str,
        dimensions: int,
    ) -> tuple[tuple[float, ...], ...]:
        self.calls.append((tuple(texts), model, dimensions))
        return tuple(
            tuple(float(position + offset) for offset in range(dimensions))
            for position, _ in enumerate(texts)
        )


@pytest.mark.asyncio
async def test_embed_texts_deduplicates_and_reuses_digest_model_cache() -> None:
    provider = FakeEmbeddingProvider()
    cache = InMemoryEmbeddingCache()
    texts = ("first source span", "second source span", "first source span")

    first = await embed_texts(provider=provider, cache=cache, texts=texts)
    second = await embed_texts(provider=provider, cache=cache, texts=texts)

    assert len(provider.calls) == 1
    assert provider.calls[0] == (
        ("first source span", "second source span"),
        EMBEDDING_MODEL,
        EMBEDDING_DIMENSIONS,
    )
    assert first == second
    assert first[0] == first[2]
    assert all(len(embedding.values) == EMBEDDING_DIMENSIONS for embedding in first)


def test_cache_key_uses_exact_text_digest_and_model() -> None:
    text = "A source span with meaningful whitespace."
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()

    assert embedding_cache_key(text) == f"sha256:{digest}:model:{EMBEDDING_MODEL}"
    assert embedding_cache_key(f" {text}") != embedding_cache_key(text)
    assert embedding_cache_key(text, "another-model") != embedding_cache_key(text)


def test_embedding_serializes_as_a_bound_halfvec_parameter_literal() -> None:
    values = (0.125,) * EMBEDDING_DIMENSIONS
    embedding = Embedding(
        cache_key="sha256:example:model:text-embedding-3-small",
        model=EMBEDDING_MODEL,
        values=values,
    )

    literal = embedding.as_halfvec_literal()

    assert literal.startswith("[")
    assert literal.endswith("]")
    assert literal.count(",") == EMBEDDING_DIMENSIONS - 1
    assert "0.125" in literal


@pytest.mark.asyncio
async def test_embed_texts_rejects_provider_dimension_mismatch() -> None:
    class ShortVectorProvider:
        async def embed(
            self,
            *,
            texts: Sequence[str],
            model: str,
            dimensions: int,
        ) -> tuple[tuple[float, ...], ...]:
            return tuple((0.0,) * (dimensions - 1) for _ in texts)

    with pytest.raises(ValueError, match="dimension"):
        await embed_texts(
            provider=ShortVectorProvider(),
            cache=InMemoryEmbeddingCache(),
            texts=("source",),
        )


@pytest.mark.asyncio
async def test_embed_texts_rejects_blank_text_without_calling_provider() -> None:
    provider = FakeEmbeddingProvider()

    with pytest.raises(ValueError, match="text"):
        await embed_texts(
            provider=provider,
            cache=InMemoryEmbeddingCache(),
            texts=("valid source", " "),
        )

    assert provider.calls == []
