"""Contract tests for the sole audited generative-model gateway."""

from __future__ import annotations

import hashlib
from collections.abc import Awaitable, Callable, Mapping
from pathlib import Path
from uuid import uuid4

import pytest
from pydantic import BaseModel

from brain.gateway.client import (
    TASK_TIER_ROUTING,
    CallContext,
    CircuitBreakerSettings,
    CircuitOpenError,
    GatewayClient,
    LlmCallRecord,
    ModelRoute,
    ModelTier,
    PromptLoadError,
    RenderedPrompt,
    PromptTemplate,
    PromptVersion,
    ProviderCallError,
    ProviderCompletion,
    PromptCatalog,
    SchemaValidationError,
    TaskClass,
    load_builtin_prompt,
)


class _Decision(BaseModel):
    action: str


class _Provider:
    name = "anthropic"

    def __init__(self, responses: list[ProviderCompletion | Exception]) -> None:
        self._responses = iter(responses)
        self.prompts: list[RenderedPrompt] = []

    async def invoke(
        self, *, route: ModelRoute, prompt: RenderedPrompt
    ) -> ProviderCompletion:
        self.prompts.append(prompt)
        response = next(self._responses)
        if isinstance(response, Exception):
            raise response
        return response


class _Audit:
    def __init__(self) -> None:
        self.prompt_templates: list[PromptTemplate] = []
        self.records: list[LlmCallRecord] = []
        self.prompt_version_id = uuid4()

    async def ensure_prompt_version(
        self, *, context: CallContext, prompt: PromptTemplate
    ) -> PromptVersion:
        self.prompt_templates.append(prompt)
        return PromptVersion(
            id=self.prompt_version_id,
            prompt_name=prompt.name,
            version=prompt.version,
            content_sha256=prompt.content_sha256,
            template_uri=prompt.template_uri,
        )

    async def write_llm_call(self, record: LlmCallRecord) -> None:
        self.records.append(record)


async def _no_sleep(_: float) -> None:
    return None


def _write_prompt(root: Path, *, body: str | None = None) -> PromptCatalog:
    root.mkdir()
    template_body = body or (
        "You are a maintenance decision agent. Follow the evidence and output rules.\n"
        "<!-- resident-os:dynamic -->\n"
        "Resident request:\n{{ request }}\n\n"
        "Return JSON matching this schema exactly:\n{{ schema_json }}\n"
    )
    (root / "diagnosis.md.j2").write_text(
        "---\nname: diagnosis\nversion: 2026.09.15\n---\n" + template_body,
        encoding="utf-8",
    )
    return PromptCatalog(root, template_uri_prefix="brain/prompts")


def _rendered_prompt(tmp_path: Path) -> RenderedPrompt:
    catalog = _write_prompt(tmp_path / "prompts")
    return catalog.load("diagnosis").render(
        {"request": "Water is leaking beneath the kitchen sink."}, schema=_Decision
    )


def _gateway(
    *,
    provider: _Provider,
    audit: _Audit,
    circuit_breaker: CircuitBreakerSettings | None = None,
    sleep: Callable[[float], Awaitable[None]] = _no_sleep,
    random_value: Callable[[], float] = lambda: 0.0,
) -> GatewayClient:
    route = ModelRoute(
        provider="anthropic",
        model_name="claude-test-model",
        model_version="claude-test-model@2026-09-15",
        max_output_tokens=256,
    )
    return GatewayClient(
        context=CallContext(uuid4(), uuid4(), uuid4()),
        providers={"anthropic": provider},
        tier_routes={tier: route for tier in ModelTier},
        audit=audit,
        circuit_breaker=circuit_breaker,
        retry_base_seconds=0.1,
        retry_jitter_seconds=0.2,
        sleep=sleep,
        random_value=random_value,
    )


def test_task_classes_have_explicit_cost_quality_tiers() -> None:
    assert TASK_TIER_ROUTING[TaskClass.SAFETY_SECOND_OPINION] is ModelTier.SMALL
    assert TASK_TIER_ROUTING[TaskClass.DIAGNOSIS] is ModelTier.MID
    assert TASK_TIER_ROUTING[TaskClass.ESCALATED_REVIEW] is ModelTier.LARGE
    assert set(TASK_TIER_ROUTING) == set(TaskClass)


def test_prompt_catalog_hashes_exact_source_and_forbids_dynamic_cache_prefix(
    tmp_path: Path,
) -> None:
    root = tmp_path / "prompts"
    catalog = _write_prompt(root)

    loaded = catalog.load("diagnosis")

    assert (
        loaded.content_sha256
        == hashlib.sha256((root / "diagnosis.md.j2").read_bytes()).hexdigest()
    )
    assert loaded.template_uri == "brain/prompts/diagnosis.md.j2"
    assert "request" in loaded.variables
    assert "schema_json" in loaded.variables

    invalid_root = tmp_path / "invalid"
    _write_prompt(
        invalid_root,
        body="Classify {{ request }} before the cache boundary.\n"
        "<!-- resident-os:dynamic -->\n{{ schema_json }}\n",
    )
    with pytest.raises(PromptLoadError, match="variables before the cache boundary"):
        PromptCatalog(invalid_root).load("diagnosis")


def test_builtin_grounding_prompt_is_versioned_asset() -> None:
    prompt = load_builtin_prompt("grounding")

    assert prompt.version == "1"
    assert prompt.template_uri == "brain/prompts/grounding.md.j2"
    assert "Every factual claim" in prompt.render().content


@pytest.mark.asyncio
async def test_complete_uses_cacheable_static_prefix_and_writes_full_audit_receipt(
    tmp_path: Path,
) -> None:
    prompt = _rendered_prompt(tmp_path)
    provider = _Provider(
        [
            ProviderCompletion(
                output_text='{"action":"dispatch plumber"}',
                input_tokens=125,
                output_tokens=12,
                cached_input_tokens=90,
                cost_microusd=321,
            )
        ]
    )
    audit = _Audit()

    result = await _gateway(provider=provider, audit=audit).complete(
        TaskClass.DIAGNOSIS, prompt, _Decision
    )

    assert result.action == "dispatch plumber"
    sent_prompt = provider.prompts[0]
    assert getattr(sent_prompt, "static_prefix").startswith("You are a maintenance")
    assert "{{ request }}" not in getattr(sent_prompt, "static_prefix")
    assert "Water is leaking" in getattr(sent_prompt, "dynamic_suffix")
    assert len(audit.prompt_templates) == 1
    assert len(audit.records) == 1
    receipt = audit.records[0]
    assert receipt.outcome == "completed"
    assert receipt.task_kind is TaskClass.DIAGNOSIS
    assert receipt.prompt_version_id == audit.prompt_version_id
    assert receipt.request_digest != prompt.template.content_sha256
    assert len(receipt.request_digest) == 64
    assert receipt.input_tokens == 125
    assert receipt.output_tokens == 12
    assert receipt.cached_input_tokens == 90
    assert receipt.cost_microusd == 321
    assert receipt.response_digest is not None


@pytest.mark.asyncio
async def test_complete_retries_transient_provider_failures_with_jitter_and_audits_each_attempt(
    tmp_path: Path,
) -> None:
    prompt = _rendered_prompt(tmp_path)
    provider = _Provider(
        [
            ProviderCallError("temporary network failure", retryable=True),
            ProviderCallError("provider is overloaded", retryable=True),
            ProviderCompletion(output_text='{"action":"monitor"}'),
        ]
    )
    audit = _Audit()
    delays: list[float] = []

    async def record_delay(value: float) -> None:
        delays.append(value)

    result = await _gateway(
        provider=provider,
        audit=audit,
        sleep=record_delay,
        random_value=lambda: 0.5,
    ).complete(TaskClass.DIAGNOSIS, prompt, _Decision)

    assert result.action == "monitor"
    assert delays == pytest.approx([0.2, 0.3])
    assert [record.outcome for record in audit.records] == [
        "provider_error",
        "provider_error",
        "completed",
    ]
    assert [record.attempt_number for record in audit.records] == [1, 2, 3]


@pytest.mark.asyncio
async def test_schema_failure_is_audited_but_not_retried(tmp_path: Path) -> None:
    prompt = _rendered_prompt(tmp_path)
    provider = _Provider([ProviderCompletion(output_text="not valid json")])
    audit = _Audit()

    with pytest.raises(SchemaValidationError) as raised:
        await _gateway(provider=provider, audit=audit).complete(
            TaskClass.DIAGNOSIS, prompt, _Decision
        )

    assert len(provider.prompts) == 1
    assert [record.outcome for record in audit.records] == ["schema_invalid"]
    assert audit.records[0].response_digest is not None
    assert raised.value.response_text == "not valid json"
    assert raised.value.validation_errors


@pytest.mark.asyncio
async def test_circuit_breaker_is_provider_scoped_and_audits_rejection(
    tmp_path: Path,
) -> None:
    prompt = _rendered_prompt(tmp_path)
    provider = _Provider([ProviderCallError("connection reset", retryable=True)] * 3)
    audit = _Audit()
    gateway = _gateway(
        provider=provider,
        audit=audit,
        circuit_breaker=CircuitBreakerSettings(
            failure_threshold=3, recovery_timeout_seconds=60
        ),
    )

    with pytest.raises(ProviderCallError):
        await gateway.complete(TaskClass.DIAGNOSIS, prompt, _Decision)
    with pytest.raises(CircuitOpenError):
        await gateway.complete(TaskClass.DIAGNOSIS, prompt, _Decision)

    assert len(provider.prompts) == 3
    assert [record.outcome for record in audit.records] == [
        "provider_error",
        "provider_error",
        "provider_error",
        "circuit_open",
    ]


class _RowConnection:
    def __init__(self, rows: list[Mapping[str, object] | None]) -> None:
        self._rows = iter(rows)
        self.queries: list[str] = []

    async def execute(self, query: str, *args: object) -> str:
        self.queries.append(query)
        return "INSERT 0 1"

    async def fetchrow(self, query: str, *args: object) -> Mapping[str, object] | None:
        self.queries.append(query)
        return next(self._rows)


@pytest.mark.asyncio
async def test_prompt_version_conflict_is_detected_before_any_model_attempt(
    tmp_path: Path,
) -> None:
    # This narrow contract lives at the database boundary; the gateway fails closed
    # if a version name exists with a different immutable source hash.
    from brain.gateway.client import AsyncpgLlmCallAudit, PromptVersionConflict

    prompt = _rendered_prompt(tmp_path).template
    connection = _RowConnection(
        [
            None,
            {
                "id": uuid4(),
                "prompt_name": prompt.name,
                "version": prompt.version,
                "content_sha256": "0" * 64,
                "template_uri": prompt.template_uri,
            },
        ]
    )
    audit = AsyncpgLlmCallAudit(connection)

    with pytest.raises(
        PromptVersionConflict, match="changed without a new prompt version"
    ):
        await audit.ensure_prompt_version(
            context=CallContext(uuid4(), uuid4(), uuid4()), prompt=prompt
        )
