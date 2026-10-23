"""Fail-closed server-side authorisation for narrow operational tools.

The grant map in this module is deployment policy, not model output.  A tool
adapter must call :meth:`ToolAuthorizer.authorize` immediately before invoking
its provider. Write adapters require server-generated action identities and must
enforce idempotency when executing external effects.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from enum import Enum
from types import MappingProxyType
from typing import Final
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
    SEND_NOTIFICATION = "send_notification"
    PAGE_ON_CALL = "page_on_call"


class ToolEffect(str, Enum):
    """Whether a tool can change a system outside this process."""

    READ = "read"
    WRITE = "write"


class ToolAuthorizationFailure(str, Enum):
    """Stable audit-safe reasons for rejecting a tool invocation."""

    GRANT_NOT_FOUND = "grant_not_found"
    MISSING_ACTION_ID = "missing_action_id"


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
        ToolName.SEND_NOTIFICATION: ToolDefinition(ToolEffect.WRITE),
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

    ``action_id`` is created when the validated action is persisted.  Models and
    incoming prompts never provide it; binding it into the scope prevents a
    a permit for one ticket action from authorising a different one.
    """

    org_id: UUID
    run_id: UUID
    ticket_id: UUID
    principal: ToolPrincipal
    tool: ToolName
    action_id: UUID | None = None


@dataclass(frozen=True, slots=True)
class AuthorizedToolCall:
    """Audit-safe proof that the server authorised one narrow invocation."""

    invocation: ToolInvocation
    effect: ToolEffect
    action_scope: str | None

    def require_exact_invocation(self, invocation: ToolInvocation) -> None:
        """Reject accidental reuse of a permit for another tool or resource."""

        if invocation != self.invocation:
            raise ToolAuthorizationError(ToolAuthorizationFailure.GRANT_NOT_FOUND)


class ToolAuthorizer:
    """Checks the fixed grant map using deployment-owned grants."""

    async def authorize(self, invocation: ToolInvocation) -> AuthorizedToolCall:
        """Apply server grants; write adapters must use a persisted action identity."""
        definition = _TOOL_DEFINITIONS[invocation.tool]
        if invocation.tool not in SERVER_GRANT_MAP.get(
            invocation.principal, frozenset()
        ):
            raise ToolAuthorizationError(ToolAuthorizationFailure.GRANT_NOT_FOUND)
        scope = (
            action_scope_for(invocation)
            if definition.effect is ToolEffect.WRITE
            else None
        )
        return AuthorizedToolCall(
            invocation=invocation, effect=definition.effect, action_scope=scope
        )


def action_scope_for(invocation: ToolInvocation) -> str:
    """Build the exact server-owned action scope for a write invocation."""

    definition = _TOOL_DEFINITIONS[invocation.tool]
    if definition.effect is not ToolEffect.WRITE or invocation.action_id is None:
        raise ToolAuthorizationError(ToolAuthorizationFailure.MISSING_ACTION_ID)
    return (
        f"{invocation.tool.value}:ticket:{invocation.ticket_id}:"
        f"action:{invocation.action_id}"
    )


def invocation_digest(invocation: ToolInvocation) -> str:
    """Create the content-free invocation digest stored for a tool call."""

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
