"""The sole audited gateway for generative model calls.

This module deliberately owns the Anthropic SDK boundary.  Callers render a
versioned prompt asset, then call :meth:`GatewayClient.complete`; the gateway
selects a tier, enforces resilience controls, validates the structured answer,
and persists an append-only receipt for each provider attempt.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import random
import re
import time
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import Enum
from pathlib import Path
from typing import Final, Protocol, TypeVar, cast
from uuid import UUID

from anthropic import (
    APIConnectionError,
    APIStatusError,
    APITimeoutError,
    AsyncAnthropic,
)
from anthropic.types import TextBlock
from jinja2 import StrictUndefined, meta
from jinja2.exceptions import TemplateError
from jinja2.sandbox import SandboxedEnvironment
from pydantic import BaseModel, ValidationError


_PROMPT_NAME_PATTERN: Final = re.compile(r"^[a-z][a-z0-9._-]*$")
_PROMPT_VERSION_PATTERN: Final = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
_FRONT_MATTER_DELIMITER: Final = "---"
_CACHE_BOUNDARY: Final = "<!-- resident-os:dynamic -->"
_PROMPT_ROOT: Final = Path(__file__).resolve().parents[1] / "prompts"


class GatewayError(RuntimeError):
    """Base class for failures raised by the model gateway."""


class PromptLoadError(GatewayError):
    """A prompt asset is missing, malformed, or has an unsafe identity."""


class PromptRenderError(GatewayError):
    """A prompt could not be rendered with the supplied structured inputs."""


class PromptVersionConflict(GatewayError):
    """A source-controlled prompt version disagrees with its immutable DB row."""


class CircuitOpenError(GatewayError):
    """The provider has exceeded its failure threshold and is cooling down."""


class GatewayTimeoutError(GatewayError):
    """A provider attempt did not complete within the configured deadline."""


class ProviderCallError(GatewayError):
    """A provider rejected a request or suffered a retryable service failure."""

    def __init__(self, message: str, *, retryable: bool) -> None:
        super().__init__(message)
        self.retryable = retryable


class SchemaValidationError(GatewayError):
    """The provider answer was not valid for the requested output schema.

    The raw response is retained only in memory so a caller may make one
    schema-repair attempt. It is never written to the append-only audit row.
    ``validation_errors`` excludes Pydantic's ``input`` field for the same reason.
    """

    def __init__(
        self,
        message: str,
        *,
        response_text: str,
        validation_errors: tuple[dict[str, object], ...],
    ) -> None:
        super().__init__(message)
        self.response_text = response_text
        self.validation_errors = validation_errors


class ModelTier(str, Enum):
    """Cost/quality tier selected by task class, rather than by each caller."""

    SMALL = "small"
    MID = "mid"
    LARGE = "large"


class TaskClass(str, Enum):
    """Stable task classes used by the planned resident-maintenance agents."""

    SAFETY_SECOND_OPINION = "safety_second_opinion"
    INTAKE_NORMALIZATION = "intake_normalization"
    POLICY_AUDIT = "policy_audit"
    COMMUNICATION_DRAFT = "communication_draft"
    DIAGNOSIS = "diagnosis"
    DISPATCH_PLANNING = "dispatch_planning"
    COUNCIL_REVIEW = "council_review"
    JUDGE_REVIEW = "judge_review"
    ESCALATED_REVIEW = "escalated_review"


TASK_TIER_ROUTING: Final[Mapping[TaskClass, ModelTier]] = {
    TaskClass.SAFETY_SECOND_OPINION: ModelTier.SMALL,
    TaskClass.INTAKE_NORMALIZATION: ModelTier.SMALL,
    TaskClass.POLICY_AUDIT: ModelTier.SMALL,
    TaskClass.COMMUNICATION_DRAFT: ModelTier.SMALL,
    TaskClass.DIAGNOSIS: ModelTier.MID,
    TaskClass.DISPATCH_PLANNING: ModelTier.MID,
    TaskClass.COUNCIL_REVIEW: ModelTier.MID,
    TaskClass.JUDGE_REVIEW: ModelTier.MID,
    TaskClass.ESCALATED_REVIEW: ModelTier.LARGE,
}


@dataclass(frozen=True, slots=True)
class ModelRoute:
    """A pinned provider/model identity for one model tier."""

    provider: str
    model_name: str
    model_version: str
    max_output_tokens: int = 1_024

    def __post_init__(self) -> None:
        if not self.provider.strip():
            raise ValueError("provider must be non-blank")
        if not self.model_name.strip():
            raise ValueError("model_name must be non-blank")
        if not self.model_version.strip():
            raise ValueError("model_version must be non-blank")
        if self.max_output_tokens <= 0:
            raise ValueError("max_output_tokens must be positive")


@dataclass(frozen=True, slots=True)
class PromptTemplate:
    """An immutable, source-controlled prompt asset and its content hash."""

    name: str
    version: str
    template_uri: str
    body: str
    content_sha256: str
    variables: frozenset[str]

    def render(
        self,
        values: Mapping[str, object] | None = None,
        *,
        schema: type[BaseModel] | None = None,
    ) -> RenderedPrompt:
        """Render a prompt, keeping its static prefix cacheable by the provider."""

        context = dict(values or {})
        if "schema_json" in context:
            raise PromptRenderError("schema_json is owned by PromptTemplate.render")
        schema_digest: str | None = None
        if schema is not None:
            if "schema_json" not in self.variables:
                raise PromptRenderError(
                    f"prompt {self.name!r} must include {{ schema_json }} for structured output"
                )
            schema_json = _schema_json(schema)
            context["schema_json"] = schema_json
            schema_digest = _sha256(schema_json)

        try:
            rendered = _jinja_environment().from_string(self.body).render(**context)
        except TemplateError as exc:
            raise PromptRenderError(f"could not render prompt {self.name!r}") from exc

        static_prefix, separator, dynamic_suffix = rendered.partition(_CACHE_BOUNDARY)
        if not static_prefix.strip():
            raise PromptRenderError(
                f"prompt {self.name!r} needs a non-blank static prefix before the cache boundary"
            )
        if separator and not dynamic_suffix.strip():
            raise PromptRenderError(
                f"prompt {self.name!r} needs dynamic request content after the cache boundary"
            )
        return RenderedPrompt(
            template=self,
            static_prefix=static_prefix,
            dynamic_suffix=dynamic_suffix,
            schema_digest=schema_digest,
        )


@dataclass(frozen=True, slots=True)
class RenderedPrompt:
    """A concrete request split at the explicit provider-cache boundary."""

    template: PromptTemplate
    static_prefix: str
    dynamic_suffix: str
    schema_digest: str | None

    @property
    def content(self) -> str:
        """Return the complete rendered prompt without retaining duplicate copies."""

        return f"{self.static_prefix}{self.dynamic_suffix}"


class PromptCatalog:
    """Loads versioned Markdown/Jinja assets and hashes their exact file bytes."""

    def __init__(
        self, root: Path, *, template_uri_prefix: str = "brain/prompts"
    ) -> None:
        self._root = root.resolve()
        self._template_uri_prefix = template_uri_prefix.rstrip("/")

    def load(self, name: str) -> PromptTemplate:
        """Load one source-controlled ``*.md.j2`` prompt without path traversal."""

        if _PROMPT_NAME_PATTERN.fullmatch(name) is None:
            raise PromptLoadError(
                "prompt name must be lowercase letters, digits, dots, hyphens, or underscores"
            )
        path = (self._root / f"{name}.md.j2").resolve()
        if path.parent != self._root:
            raise PromptLoadError(
                "prompt path must stay within the configured prompt directory"
            )
        try:
            source_bytes = path.read_bytes()
            source = source_bytes.decode("utf-8")
        except FileNotFoundError as exc:
            raise PromptLoadError(f"prompt asset not found: {name}") from exc
        except UnicodeDecodeError as exc:
            raise PromptLoadError(f"prompt asset must be UTF-8: {name}") from exc

        metadata, body = _parse_front_matter(source, name)
        if body.count(_CACHE_BOUNDARY) > 1:
            raise PromptLoadError(f"prompt {name!r} has more than one cache boundary")
        try:
            parsed = _jinja_environment().parse(body)
            variables = frozenset(meta.find_undeclared_variables(parsed))
            static_source = body.split(_CACHE_BOUNDARY, maxsplit=1)[0]
            static_variables = meta.find_undeclared_variables(
                _jinja_environment().parse(static_source)
            )
        except TemplateError as exc:
            raise PromptLoadError(f"invalid Jinja in prompt {name!r}") from exc
        if static_variables:
            raise PromptLoadError(
                f"prompt {name!r} has variables before the cache boundary: "
                f"{', '.join(sorted(static_variables))}"
            )

        return PromptTemplate(
            name=metadata["name"],
            version=metadata["version"],
            template_uri=f"{self._template_uri_prefix}/{path.name}",
            body=body,
            content_sha256=_sha256_bytes(source_bytes),
            variables=variables,
        )


def load_builtin_prompt(name: str) -> PromptTemplate:
    """Load a repository-owned prompt asset from ``brain/prompts``."""

    return PromptCatalog(_PROMPT_ROOT).load(name)


@dataclass(frozen=True, slots=True)
class CallContext:
    """The mandatory org/run/step scope for an auditable model invocation."""

    org_id: UUID
    agent_run_id: UUID
    agent_step_id: UUID


@dataclass(frozen=True, slots=True)
class ProviderCompletion:
    """Provider-neutral result metadata; no raw content is persisted in audit rows."""

    output_text: str
    input_tokens: int = 0
    output_tokens: int = 0
    cached_input_tokens: int = 0
    cost_microusd: int = 0

    def __post_init__(self) -> None:
        if any(
            value < 0
            for value in (
                self.input_tokens,
                self.output_tokens,
                self.cached_input_tokens,
                self.cost_microusd,
            )
        ):
            raise ValueError("provider usage counters must be non-negative")


class ModelProvider(Protocol):
    """The small adapter surface that keeps SDKs behind this module boundary."""

    name: str

    async def invoke(
        self, *, route: ModelRoute, prompt: RenderedPrompt
    ) -> ProviderCompletion:
        """Send a fully rendered request to the model provider."""


class AnthropicProvider:
    """The only production adapter allowed to call the Anthropic SDK."""

    name: Final[str] = "anthropic"

    def __init__(self, client: AsyncAnthropic) -> None:
        self._client = client

    async def invoke(
        self, *, route: ModelRoute, prompt: RenderedPrompt
    ) -> ProviderCompletion:
        if route.provider != self.name:
            raise ProviderCallError(
                f"AnthropicProvider cannot serve provider {route.provider!r}",
                retryable=False,
            )
        if not prompt.dynamic_suffix.strip():
            raise ProviderCallError(
                "a model prompt requires dynamic request content", retryable=False
            )
        try:
            response = await self._client.messages.create(
                model=route.model_name,
                max_tokens=route.max_output_tokens,
                system=[
                    {
                        "type": "text",
                        "text": prompt.static_prefix,
                        "cache_control": {"type": "ephemeral"},
                    }
                ],
                messages=[{"role": "user", "content": prompt.dynamic_suffix}],
            )
        except (APITimeoutError, APIConnectionError) as exc:
            raise ProviderCallError(str(exc), retryable=True) from exc
        except APIStatusError as exc:
            retryable = exc.status_code in {408, 409, 429} or exc.status_code >= 500
            raise ProviderCallError(str(exc), retryable=retryable) from exc

        output_text = "".join(
            block.text for block in response.content if isinstance(block, TextBlock)
        )
        if not output_text.strip():
            raise ProviderCallError(
                "Anthropic response did not contain text content", retryable=False
            )
        usage = response.usage
        return ProviderCompletion(
            output_text=output_text,
            input_tokens=usage.input_tokens,
            output_tokens=usage.output_tokens,
            cached_input_tokens=(
                getattr(usage, "cache_read_input_tokens", 0)
                + getattr(usage, "cache_creation_input_tokens", 0)
            ),
        )


@dataclass(frozen=True, slots=True)
class PromptVersion:
    """The immutable prompt row needed by a later ``llm_calls`` receipt."""

    id: UUID
    prompt_name: str
    version: str
    content_sha256: str
    template_uri: str


@dataclass(frozen=True, slots=True)
class LlmCallRecord:
    """A raw-content-free, append-only row for one provider attempt."""

    context: CallContext
    prompt_version_id: UUID
    task_kind: TaskClass
    route: ModelRoute
    request_digest: str
    response_digest: str | None
    input_tokens: int
    output_tokens: int
    cached_input_tokens: int
    latency_ms: int
    cost_microusd: int
    attempt_number: int
    outcome: str
    started_at: datetime
    completed_at: datetime


class LlmCallAudit(Protocol):
    """Persistence boundary; implementations run inside the caller's RLS scope."""

    async def ensure_prompt_version(
        self, *, context: CallContext, prompt: PromptTemplate
    ) -> PromptVersion:
        """Insert an immutable source-prompt identity or verify the existing one."""

    async def write_llm_call(self, record: LlmCallRecord) -> None:
        """Append one auditable attempt receipt without prompt/response text."""


class AsyncpgConnection(Protocol):
    """Narrow asyncpg interface used so this module remains easy to test."""

    async def execute(self, query: str, *args: object) -> str:
        """Execute a statement without returning rows."""

    async def fetchrow(self, query: str, *args: object) -> Mapping[str, object] | None:
        """Fetch at most one record."""


class AsyncpgLlmCallAudit:
    """PostgreSQL implementation for the append-only prompt and call receipts.

    The connection must already be inside a transaction with the repository's
    tenant RLS setting applied.  This class neither broadens the RLS scope nor
    stores raw prompt or response bodies.
    """

    def __init__(self, connection: AsyncpgConnection) -> None:
        self._connection = connection

    async def ensure_prompt_version(
        self, *, context: CallContext, prompt: PromptTemplate
    ) -> PromptVersion:
        row = await self._connection.fetchrow(
            """
            INSERT INTO prompt_versions (
                org_id, prompt_name, version, template_uri, content_sha256
            )
            VALUES ($1, $2, $3, $4, $5)
            ON CONFLICT (org_id, prompt_name, version) DO NOTHING
            RETURNING id, prompt_name, version, content_sha256, template_uri
            """,
            context.org_id,
            prompt.name,
            prompt.version,
            prompt.template_uri,
            prompt.content_sha256,
        )
        if row is None:
            row = await self._connection.fetchrow(
                """
                SELECT id, prompt_name, version, content_sha256, template_uri
                FROM prompt_versions
                WHERE org_id = $1 AND prompt_name = $2 AND version = $3
                """,
                context.org_id,
                prompt.name,
                prompt.version,
            )
        if row is None:
            raise PromptVersionConflict("prompt version was not persisted")

        stored_hash = cast(str, row["content_sha256"])
        stored_uri = cast(str, row["template_uri"])
        if stored_hash != prompt.content_sha256 or stored_uri != prompt.template_uri:
            raise PromptVersionConflict(
                "prompt source changed without a new prompt version: "
                f"{prompt.name}@{prompt.version}"
            )
        return PromptVersion(
            id=cast(UUID, row["id"]),
            prompt_name=cast(str, row["prompt_name"]),
            version=cast(str, row["version"]),
            content_sha256=stored_hash,
            template_uri=stored_uri,
        )

    async def write_llm_call(self, record: LlmCallRecord) -> None:
        await self._connection.execute(
            """
            INSERT INTO llm_calls (
                org_id, agent_run_id, agent_step_id, prompt_version_id,
                task_kind, provider, model_name, model_version, request_digest,
                response_digest, input_tokens, output_tokens, cached_input_tokens,
                latency_ms, cost_microusd, attempt_number, outcome, started_at,
                completed_at
            )
            VALUES (
                $1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13,
                $14, $15, $16, $17, $18, $19
            )
            """,
            record.context.org_id,
            record.context.agent_run_id,
            record.context.agent_step_id,
            record.prompt_version_id,
            record.task_kind.value,
            record.route.provider,
            record.route.model_name,
            record.route.model_version,
            record.request_digest,
            record.response_digest,
            record.input_tokens,
            record.output_tokens,
            record.cached_input_tokens,
            record.latency_ms,
            record.cost_microusd,
            record.attempt_number,
            record.outcome,
            record.started_at,
            record.completed_at,
        )


@dataclass(frozen=True, slots=True)
class CircuitBreakerSettings:
    """Bounded, provider-local breaker settings for temporary model outages."""

    failure_threshold: int = 3
    recovery_timeout_seconds: float = 30.0

    def __post_init__(self) -> None:
        if self.failure_threshold <= 0:
            raise ValueError("failure_threshold must be positive")
        if self.recovery_timeout_seconds <= 0:
            raise ValueError("recovery_timeout_seconds must be positive")


@dataclass(slots=True)
class _CircuitState:
    failures: int = 0
    opened_at_monotonic: float | None = None
    half_open_in_flight: bool = False


class _CircuitBreaker:
    def __init__(self, settings: CircuitBreakerSettings) -> None:
        self._settings = settings
        self._states: dict[str, _CircuitState] = {}
        self._lock = asyncio.Lock()

    async def allow(self, provider: str) -> bool:
        """Allow a closed circuit or one trial after its cooldown expires."""

        now = time.monotonic()
        async with self._lock:
            state = self._states.setdefault(provider, _CircuitState())
            if state.opened_at_monotonic is None:
                return True
            if (
                now - state.opened_at_monotonic
                < self._settings.recovery_timeout_seconds
            ):
                return False
            if state.half_open_in_flight:
                return False
            state.half_open_in_flight = True
            return True

    async def record_success(self, provider: str) -> None:
        async with self._lock:
            self._states[provider] = _CircuitState()

    async def record_failure(self, provider: str) -> None:
        now = time.monotonic()
        async with self._lock:
            state = self._states.setdefault(provider, _CircuitState())
            state.half_open_in_flight = False
            state.failures += 1
            if (
                state.opened_at_monotonic is not None
                or state.failures >= self._settings.failure_threshold
            ):
                state.opened_at_monotonic = now


ResultModel = TypeVar("ResultModel", bound=BaseModel)


class GatewayClient:
    """Routes and audits every structured generative completion for one agent step."""

    def __init__(
        self,
        *,
        context: CallContext,
        providers: Mapping[str, ModelProvider],
        tier_routes: Mapping[ModelTier, ModelRoute],
        audit: LlmCallAudit,
        timeout_seconds: float = 20.0,
        retry_base_seconds: float = 0.25,
        retry_jitter_seconds: float = 0.25,
        circuit_breaker: CircuitBreakerSettings | None = None,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        random_value: Callable[[], float] = random.random,
    ) -> None:
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        if retry_base_seconds < 0 or retry_jitter_seconds < 0:
            raise ValueError("retry timings must be non-negative")
        missing_tiers = set(ModelTier) - set(tier_routes)
        if missing_tiers:
            raise ValueError(
                f"missing routes for tiers: {sorted(tier.value for tier in missing_tiers)}"
            )
        for tier, route in tier_routes.items():
            if route.provider not in providers:
                raise ValueError(f"route for {tier.value} has no provider adapter")
            if providers[route.provider].name != route.provider:
                raise ValueError(
                    f"provider adapter identity mismatch for {route.provider!r}"
                )
        self._context = context
        self._providers = dict(providers)
        self._tier_routes = dict(tier_routes)
        self._audit = audit
        self._timeout_seconds = timeout_seconds
        self._retry_base_seconds = retry_base_seconds
        self._retry_jitter_seconds = retry_jitter_seconds
        self._breaker = _CircuitBreaker(circuit_breaker or CircuitBreakerSettings())
        self._sleep = sleep
        self._random_value = random_value

    async def complete(
        self,
        task: TaskClass,
        prompt: RenderedPrompt,
        schema: type[ResultModel],
    ) -> ResultModel:
        """Return a schema-validated completion after recording every attempt.

        ``prompt`` must have been rendered with the exact same Pydantic schema;
        this prevents an untracked inline formatting instruction from becoming a
        second prompt source.
        """

        schema_digest = _sha256(_schema_json(schema))
        if prompt.schema_digest != schema_digest:
            raise PromptRenderError(
                "prompt must be rendered with the same schema passed to complete"
            )
        if not prompt.dynamic_suffix.strip():
            raise PromptRenderError(
                "model prompts require non-blank dynamic request content"
            )

        route = self._tier_routes[TASK_TIER_ROUTING[task]]
        provider = self._providers[route.provider]
        prompt_version = await self._audit.ensure_prompt_version(
            context=self._context, prompt=prompt.template
        )
        request_digest = _sha256(
            json.dumps(
                {
                    "task": task.value,
                    "model_name": route.model_name,
                    "model_version": route.model_version,
                    "prompt": prompt.content,
                    "schema_sha256": schema_digest,
                },
                ensure_ascii=True,
                separators=(",", ":"),
                sort_keys=True,
            )
        )
        if not await self._breaker.allow(route.provider):
            await self._write_receipt(
                prompt_version_id=prompt_version.id,
                task=task,
                route=route,
                request_digest=request_digest,
                attempt_number=1,
                outcome="circuit_open",
                started_at=_utc_now(),
                completed_at=_utc_now(),
            )
            raise CircuitOpenError(f"provider circuit is open: {route.provider}")

        last_error: GatewayError | None = None
        for attempt_number in range(1, 4):
            started_at = _utc_now()
            started_monotonic = time.monotonic()
            error: GatewayError
            try:
                completion = await asyncio.wait_for(
                    provider.invoke(route=route, prompt=prompt),
                    timeout=self._timeout_seconds,
                )
            except TimeoutError:
                completed_at = _utc_now()
                await self._write_receipt(
                    prompt_version_id=prompt_version.id,
                    task=task,
                    route=route,
                    request_digest=request_digest,
                    attempt_number=attempt_number,
                    outcome="timeout",
                    started_at=started_at,
                    completed_at=completed_at,
                    latency_ms=_latency_ms(started_monotonic),
                )
                error = GatewayTimeoutError(
                    f"provider {route.provider} timed out after {self._timeout_seconds}s"
                )
            except ProviderCallError as exc:
                completed_at = _utc_now()
                await self._write_receipt(
                    prompt_version_id=prompt_version.id,
                    task=task,
                    route=route,
                    request_digest=request_digest,
                    attempt_number=attempt_number,
                    outcome="provider_error",
                    started_at=started_at,
                    completed_at=completed_at,
                    latency_ms=_latency_ms(started_monotonic),
                )
                if not exc.retryable:
                    raise
                error = exc
            else:
                completed_at = _utc_now()
                response_digest = _sha256(completion.output_text)
                try:
                    result = schema.model_validate_json(completion.output_text)
                except ValidationError as exc:
                    await self._write_receipt(
                        prompt_version_id=prompt_version.id,
                        task=task,
                        route=route,
                        request_digest=request_digest,
                        response_digest=response_digest,
                        attempt_number=attempt_number,
                        outcome="schema_invalid",
                        started_at=started_at,
                        completed_at=completed_at,
                        input_tokens=completion.input_tokens,
                        output_tokens=completion.output_tokens,
                        cached_input_tokens=completion.cached_input_tokens,
                        cost_microusd=completion.cost_microusd,
                        latency_ms=_latency_ms(started_monotonic),
                    )
                    raise SchemaValidationError(
                        "provider response failed output schema validation",
                        response_text=completion.output_text,
                        validation_errors=_safe_validation_errors(exc),
                    ) from exc
                await self._write_receipt(
                    prompt_version_id=prompt_version.id,
                    task=task,
                    route=route,
                    request_digest=request_digest,
                    response_digest=response_digest,
                    attempt_number=attempt_number,
                    outcome="completed",
                    started_at=started_at,
                    completed_at=completed_at,
                    input_tokens=completion.input_tokens,
                    output_tokens=completion.output_tokens,
                    cached_input_tokens=completion.cached_input_tokens,
                    cost_microusd=completion.cost_microusd,
                    latency_ms=_latency_ms(started_monotonic),
                )
                await self._breaker.record_success(route.provider)
                return result

            await self._breaker.record_failure(route.provider)
            last_error = error
            if attempt_number < 3:
                await self._sleep(self._retry_delay_seconds(attempt_number))

        if last_error is None:
            raise AssertionError("all provider attempts should leave a gateway error")
        raise last_error

    async def _write_receipt(
        self,
        *,
        prompt_version_id: UUID,
        task: TaskClass,
        route: ModelRoute,
        request_digest: str,
        attempt_number: int,
        outcome: str,
        started_at: datetime,
        completed_at: datetime,
        response_digest: str | None = None,
        input_tokens: int = 0,
        output_tokens: int = 0,
        cached_input_tokens: int = 0,
        cost_microusd: int = 0,
        latency_ms: int = 0,
    ) -> None:
        await self._audit.write_llm_call(
            LlmCallRecord(
                context=self._context,
                prompt_version_id=prompt_version_id,
                task_kind=task,
                route=route,
                request_digest=request_digest,
                response_digest=response_digest,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                cached_input_tokens=cached_input_tokens,
                latency_ms=latency_ms,
                cost_microusd=cost_microusd,
                attempt_number=attempt_number,
                outcome=outcome,
                started_at=started_at,
                completed_at=completed_at,
            )
        )

    def _retry_delay_seconds(self, attempt_number: int) -> float:
        jitter = self._random_value()
        if not 0.0 <= jitter <= 1.0:
            raise ValueError("random_value must return a number in [0, 1]")
        return self._retry_base_seconds * (2 ** (attempt_number - 1)) + (
            self._retry_jitter_seconds * jitter
        )


def _parse_front_matter(source: str, expected_name: str) -> tuple[dict[str, str], str]:
    normalized = source.replace("\r\n", "\n")
    opening = f"{_FRONT_MATTER_DELIMITER}\n"
    closing = f"\n{_FRONT_MATTER_DELIMITER}\n"
    if not normalized.startswith(opening):
        raise PromptLoadError("prompt must begin with YAML-style front matter")
    closing_index = normalized.find(closing, len(opening))
    if closing_index < 0:
        raise PromptLoadError("prompt front matter is missing its closing delimiter")
    header = normalized[len(opening) : closing_index]
    body = normalized[closing_index + len(closing) :]
    metadata: dict[str, str] = {}
    for line in header.splitlines():
        key, separator, value = line.partition(":")
        if not separator or not key.strip() or not value.strip():
            raise PromptLoadError("prompt front matter must contain key: value pairs")
        key = key.strip()
        if key in metadata:
            raise PromptLoadError(f"prompt front matter repeats {key!r}")
        metadata[key] = value.strip().strip("\"'")
    if set(metadata) != {"name", "version"}:
        raise PromptLoadError(
            "prompt front matter must contain exactly name and version"
        )
    if metadata["name"] != expected_name:
        raise PromptLoadError("prompt metadata name must match its filename")
    if _PROMPT_NAME_PATTERN.fullmatch(metadata["name"]) is None:
        raise PromptLoadError("prompt metadata name is invalid")
    if _PROMPT_VERSION_PATTERN.fullmatch(metadata["version"]) is None:
        raise PromptLoadError("prompt metadata version is invalid")
    if not body.strip():
        raise PromptLoadError("prompt body must be non-blank")
    return metadata, body


def _jinja_environment() -> SandboxedEnvironment:
    return SandboxedEnvironment(
        autoescape=False,
        undefined=StrictUndefined,
        keep_trailing_newline=True,
    )


def _schema_json(schema: type[BaseModel]) -> str:
    return json.dumps(
        schema.model_json_schema(),
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    )


def _sha256(value: str) -> str:
    return _sha256_bytes(value.encode("utf-8"))


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _utc_now() -> datetime:
    return datetime.now(tz=UTC)


def _latency_ms(started_monotonic: float) -> int:
    return max(0, round((time.monotonic() - started_monotonic) * 1_000))


def _safe_validation_errors(exc: ValidationError) -> tuple[dict[str, object], ...]:
    """Return repair-relevant validation metadata without invalid input values."""

    return tuple(
        {
            "loc": list(cast(tuple[object, ...], issue["loc"])),
            "type": cast(str, issue["type"]),
            "msg": cast(str, issue["msg"]),
        }
        for issue in exc.errors(include_url=False)
    )
