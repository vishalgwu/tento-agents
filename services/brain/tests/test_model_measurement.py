"""Routing, billing arithmetic and real stream-boundary regression contracts."""

from types import SimpleNamespace
from typing import cast
from unittest.mock import AsyncMock

import pytest
from openai import AsyncOpenAI

from brain.gateway.client import (
    ModelRoute,
    ModelTier,
    OpenAIProvider,
    ProviderCallError,
    RenderedPrompt,
    load_builtin_prompt,
)
from brain.gateway.config import openai_routes
from brain.gateway.pricing import estimate_microusd


def make_route() -> ModelRoute:
    return ModelRoute("openai", "gpt-4.1-mini", "gpt-4.1-mini", max_output_tokens=100)


def make_prompt() -> RenderedPrompt:
    return RenderedPrompt(
        load_builtin_prompt("intake-normalize"),
        "Return JSON only.",
        'Return {"status":"ok"}.',
        "0" * 64,
    )


def test_prices_cached_input_once_and_preserves_unknowns() -> None:
    assert (
        estimate_microusd(
            "gpt-4.1-mini", input_tokens=1000, cached_tokens=500, output_tokens=100
        )
        == 410
    )
    assert (
        estimate_microusd(
            "unpriced-model", input_tokens=1000, cached_tokens=0, output_tokens=100
        )
        is None
    )
    with pytest.raises(ValueError):
        estimate_microusd(
            "gpt-4.1-mini", input_tokens=2, cached_tokens=3, output_tokens=1
        )


def test_routes_use_deployment_tiers_and_explicit_temperature() -> None:
    routes = openai_routes(
        {
            "OPENAI_MODEL": "gpt-4.1-mini",
            "OPENAI_MODEL_MID": "pinned-model",
            "OPENAI_TEMPERATURE": "0",
            "OPENAI_MAX_OUTPUT_TOKENS": "512",
        }
    )
    assert routes[ModelTier.SMALL].model_name == "gpt-4.1-mini"
    assert routes[ModelTier.MID].model_name == "pinned-model"
    assert routes[ModelTier.SMALL].temperature == 0
    assert routes[ModelTier.MID].max_output_tokens == 512
    for bad in ("nan", "inf", "-0.1", "2.1"):
        with pytest.raises(ValueError):
            openai_routes({"OPENAI_MODEL": "gpt-4.1-mini", "OPENAI_TEMPERATURE": bad})


class _Stream:
    def __init__(self, *, finish: str = "stop", usage: bool = True) -> None:
        self.closed = False
        self.chunks = [
            SimpleNamespace(
                usage=None,
                choices=[
                    SimpleNamespace(
                        delta=SimpleNamespace(content=None, refusal=None),
                        finish_reason=None,
                    )
                ],
            ),
            SimpleNamespace(
                usage=None,
                choices=[
                    SimpleNamespace(
                        delta=SimpleNamespace(content='{"status":', refusal=None),
                        finish_reason=None,
                    )
                ],
            ),
            SimpleNamespace(
                usage=None,
                choices=[
                    SimpleNamespace(
                        delta=SimpleNamespace(content='"ok"}', refusal=None),
                        finish_reason=finish,
                    )
                ],
            ),
        ]
        if usage:
            self.chunks.append(
                SimpleNamespace(
                    choices=[],
                    usage=SimpleNamespace(
                        prompt_tokens=1000,
                        completion_tokens=100,
                        prompt_tokens_details=SimpleNamespace(cached_tokens=500),
                    ),
                )
            )

    async def __aenter__(self) -> "_Stream":
        return self

    async def __aexit__(self, *args: object) -> None:
        self.closed = True

    def __aiter__(self) -> "_Stream":
        return self

    async def __anext__(self) -> SimpleNamespace:
        if not self.chunks:
            raise StopAsyncIteration
        return self.chunks.pop(0)


@pytest.mark.asyncio
@pytest.mark.parametrize("usage", [True, False])
async def test_stream_first_content_usage_and_cleanup(usage: bool) -> None:
    stream = _Stream(usage=usage)
    create = AsyncMock(return_value=stream)
    client = SimpleNamespace(
        chat=SimpleNamespace(completions=SimpleNamespace(create=create))
    )
    completion = await OpenAIProvider(cast(AsyncOpenAI, client), streaming=True).invoke(
        route=make_route(), prompt=make_prompt()
    )
    assert completion.output_text == '{"status":"ok"}'
    assert completion.first_token_ms is not None
    assert completion.first_token_ms >= 0
    assert completion.cost_microusd == (410 if usage else 0)
    assert (completion.pricing_version is not None) == usage
    assert stream.closed
    assert create.await_args is not None
    assert create.await_args.kwargs["stream_options"] == {"include_usage": True}


@pytest.mark.asyncio
async def test_truncated_stream_never_becomes_accepted_json() -> None:
    stream = _Stream(finish="length")
    client = SimpleNamespace(
        chat=SimpleNamespace(
            completions=SimpleNamespace(create=AsyncMock(return_value=stream))
        )
    )
    with pytest.raises(ProviderCallError, match="incomplete"):
        await OpenAIProvider(cast(AsyncOpenAI, client), streaming=True).invoke(
            route=ModelRoute("openai", "gpt-4.1-mini", "gpt-4.1-mini", temperature=0),
            prompt=make_prompt(),
        )
    assert stream.closed
