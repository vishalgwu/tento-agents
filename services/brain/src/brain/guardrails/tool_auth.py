"""Fail-closed server-side authorisation for narrow operational tools.

The grant map in this module is deployment policy, not model output.  A tool
adapter must call :meth:`ToolAuthorizer.authorize` immediately before invoking
its provider.  The approval-token store is responsible for atomically recording
the use before it returns; a timeout or store failure therefore blocks the tool.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import Enum
from types import MappingProxyType
from typing import Final, Protocol
from uuid import UUID


class ToolPrincipal(str, Enum):
    """Server-assigned identities that may receive narrow tool capabilities."""

    ORCHESTRATOR = "orchestrator"
    CONTEXT_BROKER = "context_broker"


class ToolName(str, Enum):
    """The complete current MCP-facing tool vocabulary."""

    READ_KNOWLEDGE = "read_knowledge"
    READ_POLICY = "read_policy"
    READ_ASSET_STATE = "read_asset_state"
    CREATE_WORK_ORDER = "create_work_order"
    DISPATCH_VENDOR = "dispatch_vendor"
    SEND_APPROVED_NOTIFICATION = "send_approved_notification"
    PAGE_ON_CALL = "page_on_call"


class ToolEffect(str, Enum):
    """Whether a tool can change a system outside this process."""

    READ = "read"
    WRITE = "write"


class ToolAuthorizationFailure(str, Enum):
    """Stable audit-safe reasons for rejecting a tool invocation."""

    GRANT_NOT_FOUND = "grant_not_found"
    MISSING_ACTION_ID = "missing_action_id"
    MISSING_APPROVAL_TOKEN = "missing_approval_token"
    UNEXPECTED_APPROVAL_TOKEN = "unexpected_approval_token"
    INVALID_APPROVAL_TOKEN = "invalid_approval_token"
    APPROVAL_STORE_UNAVAILABLE = "approval_store_unavailable"


class ToolAuthorizationError(PermissionError):
    """A deliberately non-sensitive tool-authorisation rejection."""

    def __init__(self, failure: ToolAuthorizationFailure) -> None:
        self.failure = failure
        super().__init__(f"tool invocation blocked: {failure.value}")


@dataclass(frozen=True, slots=True)
class ToolDefinition:
    """Server-owned behaviour class for one narrowly named tool."""

    effect: ToolEffect


_TOOL_DEFINITIONS: Final[Mapping[ToolName, ToolDefinition]] = MappingProxyType(
    {
        ToolName.READ_KNOWLEDGE: ToolDefinition(ToolEffect.READ),
        ToolName.READ_POLICY: ToolDefinition(ToolEffect.READ),
        ToolName.READ_ASSET_STATE: ToolDefinition(ToolEffect.READ),
        ToolName.CREATE_WORK_ORDER: ToolDefinition(ToolEffect.WRITE),
        ToolName.DISPATCH_VENDOR: ToolDefinition(ToolEffect.WRITE),
        ToolName.SEND_APPROVED_NOTIFICATION: ToolDefinition(ToolEffect.WRITE),
        ToolName.PAGE_ON_CALL: ToolDefinition(ToolEffect.WRITE),
    }
)

_READ_TOOLS: Final = frozenset(
    {
        ToolName.READ_KNOWLEDGE,
        ToolName.READ_POLICY,
        ToolName.READ_ASSET_STATE,
    }
)

# Do not derive this map from a prompt, request claims, or agent configuration.
# Its presence is intentionally explicit so adding a tool is a reviewed change.
SERVER_GRANT_MAP: Final[Mapping[ToolPrincipal, frozenset[ToolName]]] = MappingProxyType(
    {
        ToolPrincipal.ORCHESTRATOR: frozenset(ToolName),
        ToolPrincipal.CONTEXT_BROKER: _READ_TOOLS,
    }
)


@dataclass(frozen=True, slots=True)
class ToolInvocation:
    """Server-derived identity and target for one intended tool call.

    ``action_id`` is created when the approved action is persisted.  Models and
    incoming prompts never provide it; binding it into the scope prevents a
    token approved for one ticket action from authorising a different one.
    """

    org_id: UUID
    run_id: UUID
    ticket_id: UUID
    principal: ToolPrincipal
    tool: ToolName
    action_id: UUID | None = None


@dataclass(frozen=True, slots=True)
class ApprovalTokenConsumption:
    """Opaque durable receipt returned only after one successful token use."""

    grant_id: UUID
    approval_id: UUID


class ApprovalTokenStore(Protocol):
    """Durable, atomic storage for action-scoped approval-token consumption.

    Implementations must commit a unique consumption record before returning a
    receipt.  They must require the same organisation, action scope, unexpired
    token hash, and approved approval record in one transaction.  A duplicate
    token use returns ``None`` rather than overwriting audit history.
    """

    async def consume(
        self,
        *,
        org_id: UUID,
        run_id: UUID,
        token_hash: str,
        action_scope: str,
        invocation_digest: str,
        now: datetime,
    ) -> ApprovalTokenConsumption | None:
        """Atomically consume one valid approval token, or return ``None``."""


@dataclass(frozen=True, slots=True)
class AuthorizedToolCall:
    """Audit-safe proof that the server authorised one narrow invocation."""

    invocation: ToolInvocation
    effect: ToolEffect
    action_scope: str | None
    approval: ApprovalTokenConsumption | None

    def require_exact_invocation(self, invocation: ToolInvocation) -> None:
        """Reject accidental reuse of a permit for another tool or resource."""

        if invocation != self.invocation:
            raise ToolAuthorizationError(ToolAuthorizationFailure.GRANT_NOT_FOUND)


class ToolAuthorizer:
    """Checks the fixed grant map and atomically consumes write approvals."""

    def __init__(
        self,
        approval_tokens: ApprovalTokenStore,
        *,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._approval_tokens = approval_tokens
        self._clock = clock

    async def authorize(
        self,
        invocation: ToolInvocation,
        *,
        approval_token: str | None = None,
    ) -> AuthorizedToolCall:
        """Return a permit only when the fixed server policy authorises it."""

        definition = _TOOL_DEFINITIONS[invocation.tool]
        if invocation.tool not in SERVER_GRANT_MAP.get(
            invocation.principal, frozenset()
        ):
            raise ToolAuthorizationError(ToolAuthorizationFailure.GRANT_NOT_FOUND)

        if definition.effect is ToolEffect.READ:
            if approval_token is not None:
                raise ToolAuthorizationError(
                    ToolAuthorizationFailure.UNEXPECTED_APPROVAL_TOKEN
                )
            return AuthorizedToolCall(
                invocation=invocation,
                effect=definition.effect,
                action_scope=None,
                approval=None,
            )

        if invocation.action_id is None:
            raise ToolAuthorizationError(ToolAuthorizationFailure.MISSING_ACTION_ID)
        token_hash = _approval_token_hash(approval_token)
        now = self._clock()
        if now.tzinfo is None or now.utcoffset() is None:
            raise RuntimeError("tool authorizer clock must return an aware datetime")
        action_scope = action_scope_for(invocation)
        try:
            approval = await self._approval_tokens.consume(
                org_id=invocation.org_id,
                run_id=invocation.run_id,
                token_hash=token_hash,
                action_scope=action_scope,
                invocation_digest=invocation_digest(invocation),
                now=now,
            )
        except asyncio.CancelledError:
            raise
        except Exception as error:
            raise ToolAuthorizationError(
                ToolAuthorizationFailure.APPROVAL_STORE_UNAVAILABLE
            ) from error
        if approval is None:
            raise ToolAuthorizationError(
                ToolAuthorizationFailure.INVALID_APPROVAL_TOKEN
            )
        return AuthorizedToolCall(
            invocation=invocation,
            effect=definition.effect,
            action_scope=action_scope,
            approval=approval,
        )


def action_scope_for(invocation: ToolInvocation) -> str:
    """Build the exact server-owned approval scope for a write invocation."""

    definition = _TOOL_DEFINITIONS[invocation.tool]
    if definition.effect is not ToolEffect.WRITE or invocation.action_id is None:
        raise ToolAuthorizationError(ToolAuthorizationFailure.MISSING_ACTION_ID)
    return (
        f"{invocation.tool.value}:ticket:{invocation.ticket_id}:"
        f"action:{invocation.action_id}"
    )


def invocation_digest(invocation: ToolInvocation) -> str:
    """Create the content-free invocation digest stored with a token use."""

    payload = {
        "action_id": str(invocation.action_id) if invocation.action_id else None,
        "org_id": str(invocation.org_id),
        "principal": invocation.principal.value,
        "run_id": str(invocation.run_id),
        "ticket_id": str(invocation.ticket_id),
        "tool": invocation.tool.value,
    }
    encoded = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _approval_token_hash(approval_token: str | None) -> str:
    if approval_token is None:
        raise ToolAuthorizationError(ToolAuthorizationFailure.MISSING_APPROVAL_TOKEN)
    if (
        not isinstance(approval_token, str)
        or not approval_token
        or approval_token != approval_token.strip()
        or len(approval_token) > 1024
    ):
        raise ToolAuthorizationError(ToolAuthorizationFailure.INVALID_APPROVAL_TOKEN)
    return hashlib.sha256(approval_token.encode("utf-8")).hexdigest()
