"""A bounded, fail-safe content-safety filter for untrusted text.

The shield is deliberately not an authority boundary.  It classifies material
for a caller that already has deterministic routing and no implied tool rights;
the orchestrator remains responsible for every consequential action.  The local
rules always run.  Optional managed providers can add a block but cannot turn a
local or peer block into an allow decision.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import re
from collections.abc import Collection, Sequence
from enum import Enum
from typing import Final, Protocol

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


DEFAULT_MANAGED_PROVIDER_TIMEOUT_SECONDS: Final = 0.25
LOCAL_SHIELD_NAME: Final = "local"
LOCAL_SHIELD_VERSION: Final = "local-v1"
DEGRADATION_INTERLOCK_NAME: Final = "degradation_interlock"
_PROVIDER_NAME_PATTERN: Final = re.compile(r"^[a-z][a-z0-9_-]{0,63}$")
_REASON_CODE_PATTERN: Final = re.compile(r"^[a-z][a-z0-9_]{0,79}$")
_LOGGER = logging.getLogger(__name__)


class ShieldStage(str, Enum):
    """Boundary at which untrusted text is being inspected."""

    API_INGRESS = "api_ingress"
    PRE_MODEL = "pre_model"
    POST_MODEL = "post_model"
    PRE_DECISION = "pre_decision"
    PRE_SEND = "pre_send"
    TOOL_INVOCATION = "tool_invocation"
    GATEWAY = "gateway"


# These boundaries can lead to an externally visible decision or communication.
# A managed classification outage therefore becomes a safe block rather than an
# unsafe allow. Pre-model filtering remains available in rules-only mode so an
# unavailable optional provider does not prevent a safe acknowledgement path.
DEFAULT_FAIL_CLOSED_DEGRADATION_STAGES: Final[frozenset[ShieldStage]] = frozenset(
    {ShieldStage.PRE_DECISION, ShieldStage.PRE_SEND}
)


class ShieldOutcome(str, Enum):
    """The only terminal classification values a shield provider may return."""

    ALLOW = "allow"
    BLOCK = "block"


class ShieldDegradationKind(str, Enum):
    """Audit-safe reason an optional provider did not contribute a finding."""

    INVALID_RESPONSE = "invalid_response"
    PROVIDER_FAILURE = "provider_failure"
    TIMEOUT = "timeout"


class ShieldRequest(BaseModel):
    """Transient text and its processing boundary.

    Content must never be logged, persisted in a shield result, or supplied to a
    tool-authorised component.  ``content_digest`` is the only audit reference
    exposed by the resulting assessment.
    """

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    content: str = Field(min_length=1, max_length=20_000, repr=False)
    stage: ShieldStage

    @field_validator("content")
    @classmethod
    def _require_non_blank_content(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("content must be non-blank")
        return value

    @property
    def content_digest(self) -> str:
        """Return the stable digest safe for a guardrail receipt or log."""

        return hashlib.sha256(self.content.encode("utf-8")).hexdigest()


class ShieldFinding(BaseModel):
    """A provider result that never echoes the inspected content."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    provider: str = Field(min_length=1, max_length=64)
    outcome: ShieldOutcome
    reason_codes: tuple[str, ...] = ()

    @field_validator("provider")
    @classmethod
    def _validate_provider(cls, value: str) -> str:
        if _PROVIDER_NAME_PATTERN.fullmatch(value) is None:
            raise ValueError("provider must be a lowercase stable identifier")
        return value

    @field_validator("reason_codes")
    @classmethod
    def _validate_reason_codes(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if len(value) != len(set(value)):
            raise ValueError("reason_codes must not contain duplicates")
        if any(_REASON_CODE_PATTERN.fullmatch(code) is None for code in value):
            raise ValueError("reason_codes must be lowercase stable identifiers")
        return value

    @model_validator(mode="after")
    def _match_reasons_to_outcome(self) -> ShieldFinding:
        if self.outcome is ShieldOutcome.BLOCK and not self.reason_codes:
            raise ValueError("a block finding needs at least one reason code")
        if self.outcome is ShieldOutcome.ALLOW and self.reason_codes:
            raise ValueError("an allow finding cannot contain reason codes")
        return self


class ShieldDegradation(BaseModel):
    """A safe record for an optional provider that could not be used."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    provider: str = Field(min_length=1, max_length=64)
    kind: ShieldDegradationKind

    @field_validator("provider")
    @classmethod
    def _validate_provider(cls, value: str) -> str:
        if _PROVIDER_NAME_PATTERN.fullmatch(value) is None:
            raise ValueError("provider must be a lowercase stable identifier")
        return value


class ShieldAssessment(BaseModel):
    """The pessimistic combined decision and audit-safe degradation state."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    content_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    outcome: ShieldOutcome
    findings: tuple[ShieldFinding, ...] = Field(min_length=1)
    degradations: tuple[ShieldDegradation, ...] = ()

    @model_validator(mode="after")
    def _validate_combined_outcome(self) -> ShieldAssessment:
        finding_names = tuple(finding.provider for finding in self.findings)
        if finding_names[0] != LOCAL_SHIELD_NAME:
            raise ValueError("the local shield finding must be first")
        if len(finding_names) != len(set(finding_names)):
            raise ValueError("findings must contain each provider at most once")
        degraded_names = tuple(item.provider for item in self.degradations)
        if len(degraded_names) != len(set(degraded_names)):
            raise ValueError("degradations must contain each provider at most once")
        if set(finding_names) & set(degraded_names):
            raise ValueError("a provider cannot both return a finding and degrade")
        expected = (
            ShieldOutcome.BLOCK
            if any(finding.outcome is ShieldOutcome.BLOCK for finding in self.findings)
            else ShieldOutcome.ALLOW
        )
        if self.outcome is not expected:
            raise ValueError("outcome must block when any provider blocks")
        return self


class ShieldProvider(Protocol):
    """The minimal interface for local and later managed content filters."""

    name: str

    async def inspect(self, request: ShieldRequest) -> ShieldFinding:
        """Return one content-safety finding without logging request content."""


class _LocalRule:
    def __init__(self, reason_code: str, expression: str) -> None:
        self.reason_code = reason_code
        self.expression = re.compile(expression, re.IGNORECASE | re.VERBOSE)


_LOCAL_RULES: Final[tuple[_LocalRule, ...]] = (
    _LocalRule(
        "credible_violence_threat",
        r"""
        \b(?:i|we)\s+(?:will|am\s+going\s+to|gonna)\s+
        (?:kill|shoot|stab|bomb|attack|hurt)\b
        """,
    ),
    _LocalRule(
        "imminent_weapon_threat",
        r"""
        \b(?:bring|use|fire)\s+(?:a\s+)?(?:gun|weapon|bomb)\b
        """,
    ),
    _LocalRule(
        "self_harm_instruction",
        r"""
        \b(?:how\s+to\s+kill\s+myself|how\s+to\s+self[\s-]?harm|suicide\s+method)\b
        """,
    ),
)


class LocalShield:
    """Always-on deterministic filter for a small set of urgent safety signals."""

    name: Final[str] = LOCAL_SHIELD_NAME
    version: Final[str] = LOCAL_SHIELD_VERSION

    async def inspect(self, request: ShieldRequest) -> ShieldFinding:
        """Classify locally without network I/O or content retention."""

        reason_codes = tuple(
            rule.reason_code
            for rule in _LOCAL_RULES
            if rule.expression.search(request.content) is not None
        )
        return ShieldFinding(
            provider=self.name,
            outcome=ShieldOutcome.BLOCK if reason_codes else ShieldOutcome.ALLOW,
            reason_codes=reason_codes,
        )


class Shield:
    """Run the local shield and bounded managed providers with pessimistic OR logic."""

    def __init__(
        self,
        managed_providers: Sequence[ShieldProvider] = (),
        *,
        managed_provider_timeout_seconds: float = DEFAULT_MANAGED_PROVIDER_TIMEOUT_SECONDS,
        fail_closed_on_degradation_stages: Collection[
            ShieldStage
        ] = DEFAULT_FAIL_CLOSED_DEGRADATION_STAGES,
        logger: logging.Logger | None = None,
    ) -> None:
        if (
            not isinstance(managed_provider_timeout_seconds, (float, int))
            or isinstance(managed_provider_timeout_seconds, bool)
            or managed_provider_timeout_seconds <= 0
        ):
            raise ValueError("managed_provider_timeout_seconds must be positive")
        self._managed_providers = tuple(managed_providers)
        self._timeout_seconds = float(managed_provider_timeout_seconds)
        self._fail_closed_on_degradation_stages = frozenset(
            fail_closed_on_degradation_stages
        )
        self._logger = logger or _LOGGER
        _validate_managed_provider_names(self._managed_providers)
        if any(
            not isinstance(stage, ShieldStage)
            for stage in self._fail_closed_on_degradation_stages
        ):
            raise ValueError(
                "fail_closed_on_degradation_stages must contain ShieldStage values"
            )

    async def inspect(self, request: ShieldRequest) -> ShieldAssessment:
        """Return a local-first, pessimistically combined content-safety result.

        A local block returns immediately and does not disclose the material to an
        optional managed provider. Managed providers otherwise run concurrently;
        a timeout or failure is observable as a degradation but leaves the local
        decision intact instead of failing the request.
        """

        local_finding = await LocalShield().inspect(request)
        if local_finding.outcome is ShieldOutcome.BLOCK:
            return ShieldAssessment(
                content_digest=request.content_digest,
                outcome=ShieldOutcome.BLOCK,
                findings=(local_finding,),
            )

        managed_results = await asyncio.gather(
            *(
                self._inspect_managed(provider, request)
                for provider in self._managed_providers
            )
        )
        findings = [local_finding]
        degradations: list[ShieldDegradation] = []
        for finding, degradation in managed_results:
            if finding is not None:
                findings.append(finding)
            if degradation is not None:
                degradations.append(degradation)
        if degradations and request.stage in self._fail_closed_on_degradation_stages:
            findings.append(
                ShieldFinding(
                    provider=DEGRADATION_INTERLOCK_NAME,
                    outcome=ShieldOutcome.BLOCK,
                    reason_codes=("managed_provider_degraded",),
                )
            )
            self._logger.warning(
                "shield_degradation_fail_closed stage=%s content_digest=%s",
                request.stage.value,
                request.content_digest,
            )
        outcome = (
            ShieldOutcome.BLOCK
            if any(finding.outcome is ShieldOutcome.BLOCK for finding in findings)
            else ShieldOutcome.ALLOW
        )
        return ShieldAssessment(
            content_digest=request.content_digest,
            outcome=outcome,
            findings=tuple(findings),
            degradations=tuple(degradations),
        )

    async def _inspect_managed(
        self, provider: ShieldProvider, request: ShieldRequest
    ) -> tuple[ShieldFinding | None, ShieldDegradation | None]:
        provider_name = provider.name
        try:
            finding = await asyncio.wait_for(
                provider.inspect(request), timeout=self._timeout_seconds
            )
        except asyncio.CancelledError:
            raise
        except TimeoutError:
            degradation = ShieldDegradation(
                provider=provider_name,
                kind=ShieldDegradationKind.TIMEOUT,
            )
            self._log_degradation(degradation, request)
            return None, degradation
        except Exception:
            degradation = ShieldDegradation(
                provider=provider_name,
                kind=ShieldDegradationKind.PROVIDER_FAILURE,
            )
            self._log_degradation(degradation, request)
            return None, degradation

        if not isinstance(finding, ShieldFinding) or finding.provider != provider_name:
            degradation = ShieldDegradation(
                provider=provider_name,
                kind=ShieldDegradationKind.INVALID_RESPONSE,
            )
            self._log_degradation(degradation, request)
            return None, degradation
        return finding, None

    def _log_degradation(
        self, degradation: ShieldDegradation, request: ShieldRequest
    ) -> None:
        self._logger.warning(
            "shield_provider_degraded provider=%s kind=%s stage=%s content_digest=%s",
            degradation.provider,
            degradation.kind.value,
            request.stage.value,
            request.content_digest,
        )


def _validate_managed_provider_names(providers: Sequence[ShieldProvider]) -> None:
    names: list[str] = []
    for provider in providers:
        name = getattr(provider, "name", None)
        if not isinstance(name, str) or _PROVIDER_NAME_PATTERN.fullmatch(name) is None:
            raise ValueError(
                "managed provider names must be lowercase stable identifiers"
            )
        if name == LOCAL_SHIELD_NAME:
            raise ValueError("managed providers cannot replace the local shield")
        if name == DEGRADATION_INTERLOCK_NAME:
            raise ValueError(
                "managed providers cannot replace the degradation interlock"
            )
        names.append(name)
    if len(names) != len(set(names)):
        raise ValueError("managed provider names must be unique")
