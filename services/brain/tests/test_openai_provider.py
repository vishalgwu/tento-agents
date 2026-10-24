"""Unit tests for the OpenAI model provider adapter.

All provider responses are mocked.
No API credentials, network calls, or database connections required.
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock
from typing import cast
from openai import AsyncOpenAI
import httpx

import openai
import pytest

from brain.gateway.client import (
    ModelRoute,
    OpenAIProvider,
    ProviderCallError,
    RenderedPrompt,
    load_builtin_prompt,
)


def make_route() -> ModelRoute:
    return ModelRoute(
        provider="openai",
        model_name="gpt-4.1-mini",
        model_version="gpt-4.1-mini",
        max_output_tokens=100,
    )


def make_prompt() -> RenderedPrompt:
    return RenderedPrompt(
        template=load_builtin_prompt("intake-normalize"),
        static_prefix="Return valid JSON only.",
        dynamic_suffix='Return {"status":"ok"}.',
        schema_digest="0" * 64,
    )


@pytest.mark.asyncio
async def test_openai_provider_success() -> None:
    mock_client = SimpleNamespace(
        chat=SimpleNamespace(
            completions=SimpleNamespace(
                create=AsyncMock(
                    return_value=SimpleNamespace(
                        choices=[
                            SimpleNamespace(
                                finish_reason="stop",
                                message=SimpleNamespace(
                                    refusal=None, content='{"status":"ok"}'
                                ),
                            )
                        ],
                        usage=SimpleNamespace(
                            prompt_tokens=28,
                            completion_tokens=5,
                            prompt_tokens_details=SimpleNamespace(cached_tokens=8),
                        ),
                    )
                )
            )
        )
    )

    provider = OpenAIProvider(cast(AsyncOpenAI, mock_client))

    result = await provider.invoke(
        route=make_route(),
        prompt=make_prompt(),
    )

    assert result.output_text == '{"status":"ok"}'
    assert result.input_tokens == 28
    assert result.output_tokens == 5
    assert result.cached_input_tokens == 8
    arguments = mock_client.chat.completions.create.await_args.kwargs
    assert arguments["model"] == "gpt-4.1-mini"
    assert arguments["max_completion_tokens"] == 100
    assert arguments["response_format"] == {"type": "json_object"}
    assert [message["role"] for message in arguments["messages"]] == ["system", "user"]


@pytest.mark.asyncio
async def test_openai_provider_rejects_wrong_route() -> None:
    provider = OpenAIProvider(cast(AsyncOpenAI, SimpleNamespace()))

    route = ModelRoute(
        provider="anthropic",
        model_name="test-model",
        model_version="test-model",
    )

    with pytest.raises(ProviderCallError) as exc:
        await provider.invoke(
            route=route,
            prompt=make_prompt(),
        )

    assert exc.value.retryable is False


@pytest.mark.asyncio
async def test_openai_provider_rejects_empty_output() -> None:
    mock_client = SimpleNamespace(
        chat=SimpleNamespace(
            completions=SimpleNamespace(
                create=AsyncMock(
                    return_value=SimpleNamespace(
                        choices=[
                            SimpleNamespace(
                                finish_reason="stop",
                                message=SimpleNamespace(content="", refusal=None),
                            )
                        ],
                        usage=None,
                    )
                )
            )
        )
    )

    provider = OpenAIProvider(cast(AsyncOpenAI, mock_client))

    with pytest.raises(ProviderCallError) as exc:
        await provider.invoke(
            route=make_route(),
            prompt=make_prompt(),
        )

    assert exc.value.retryable is False


@pytest.mark.asyncio
async def test_openai_provider_rejects_blank_prompt() -> None:
    provider = OpenAIProvider(cast(AsyncOpenAI, SimpleNamespace()))

    prompt = RenderedPrompt(
        template=load_builtin_prompt("intake-normalize"),
        static_prefix="Return JSON.",
        dynamic_suffix="",
        schema_digest="0" * 64,
    )

    with pytest.raises(ProviderCallError) as exc:
        await provider.invoke(
            route=make_route(),
            prompt=prompt,
        )

    assert exc.value.retryable is False


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "finish_reason,refusal", [("length", None), ("stop", "Cannot comply")]
)
async def test_openai_provider_rejects_incomplete_or_refused_output(
    finish_reason: str, refusal: str | None
) -> None:
    response = SimpleNamespace(
        choices=[
            SimpleNamespace(
                finish_reason=finish_reason,
                message=SimpleNamespace(content="{}", refusal=refusal),
            )
        ],
        usage=None,
    )
    client = SimpleNamespace(
        chat=SimpleNamespace(
            completions=SimpleNamespace(create=AsyncMock(return_value=response))
        )
    )
    with pytest.raises(ProviderCallError) as error:
        await OpenAIProvider(cast(AsyncOpenAI, client)).invoke(
            route=make_route(), prompt=make_prompt()
        )
    assert not error.value.retryable


@pytest.mark.asyncio
async def test_openai_provider_rejects_missing_choice() -> None:
    client = SimpleNamespace(
        chat=SimpleNamespace(
            completions=SimpleNamespace(
                create=AsyncMock(return_value=SimpleNamespace(choices=[]))
            )
        )
    )
    with pytest.raises(ProviderCallError) as error:
        await OpenAIProvider(cast(AsyncOpenAI, client)).invoke(
            route=make_route(), prompt=make_prompt()
        )
    assert not error.value.retryable


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "status,retryable", [(400, False), (401, False), (429, True), (503, True)]
)
async def test_openai_provider_classifies_provider_errors(
    status: int, retryable: bool
) -> None:
    response = httpx.Response(
        status,
        request=httpx.Request("POST", "https://api.openai.com/v1/chat/completions"),
    )
    failure = openai.APIStatusError("mock provider failure", response=response, body={})
    client = SimpleNamespace(
        chat=SimpleNamespace(
            completions=SimpleNamespace(create=AsyncMock(side_effect=failure))
        )
    )
    with pytest.raises(ProviderCallError) as error:
        await OpenAIProvider(cast(AsyncOpenAI, client)).invoke(
            route=make_route(), prompt=make_prompt()
        )
    assert error.value.retryable is retryable


@pytest.mark.asyncio
async def test_openai_connection_failure_is_retryable() -> None:
    failure = openai.APIConnectionError(
        request=httpx.Request("POST", "https://api.openai.com/v1/chat/completions")
    )
    client = SimpleNamespace(
        chat=SimpleNamespace(
            completions=SimpleNamespace(create=AsyncMock(side_effect=failure))
        )
    )
    with pytest.raises(ProviderCallError) as error:
        await OpenAIProvider(cast(AsyncOpenAI, client)).invoke(
            route=make_route(), prompt=make_prompt()
        )
    assert error.value.retryable
