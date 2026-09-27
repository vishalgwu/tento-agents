"""Regression coverage for server-enforced narrow-tool grants."""

from __future__ import annotations

import asyncio
import hashlib
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest

from brain.guardrails.tool_auth import (
    ApprovalTokenConsumption,
    ToolAuthorizationError,
    ToolAuthorizationFailure,
    ToolAuthorizer,
    ToolInvocation,
    ToolName,
    ToolPrincipal,
    action_scope_for,
    invocation_digest,
)


_NOW = datetime(2026, 9, 26, 12, 0, tzinfo=UTC)


@dataclass
class _StoredApproval:
    org_id: UUID
    run_id: UUID
    token_hash: str
    action_scope: str
    expires_at: datetime
    consumed: bool = False


class _ApprovalStore:
    """A lock-backed stand-in for the production atomic database insert."""

    def __init__(self, approval: _StoredApproval | None) -> None:
        self._approval = approval
        self._lock = asyncio.Lock()
        self.calls = 0

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
        del invocation_digest
        self.calls += 1
        async with self._lock:
            approval = self._approval
            if (
                approval is None
                or approval.consumed
                or approval.org_id != org_id
                or approval.run_id != run_id
                or approval.token_hash != token_hash
                or approval.action_scope != action_scope
                or approval.expires_at <= now
            ):
                return None
            approval.consumed = True
            return ApprovalTokenConsumption(grant_id=uuid4(), approval_id=uuid4())


class _UnavailableApprovalStore:
    async def consume(self, **_: object) -> ApprovalTokenConsumption | None:
        raise ConnectionError("approval database unavailable")


def _invocation(
    *,
    principal: ToolPrincipal = ToolPrincipal.ORCHESTRATOR,
    tool: ToolName = ToolName.CREATE_WORK_ORDER,
    action_id: UUID | None = None,
) -> ToolInvocation:
    return ToolInvocation(
        org_id=UUID("00000000-0000-0000-0000-000000000001"),
        run_id=UUID("00000000-0000-0000-0000-000000000002"),
        ticket_id=UUID("00000000-0000-0000-0000-000000000003"),
        principal=principal,
        tool=tool,
        action_id=action_id,
    )


def _authorizer(
    invocation: ToolInvocation, token: str = "approval-token"
) -> tuple[ToolAuthorizer, _ApprovalStore]:
    store = _ApprovalStore(
        _StoredApproval(
            org_id=invocation.org_id,
            run_id=invocation.run_id,
            token_hash=hashlib.sha256(token.encode("utf-8")).hexdigest(),
            action_scope=action_scope_for(invocation),
            expires_at=_NOW + timedelta(minutes=5),
        )
    )
    return ToolAuthorizer(store, clock=lambda: _NOW), store


@pytest.mark.asyncio
async def test_read_grant_needs_no_token_and_write_grant_cannot_be_conferred_to_context() -> (
    None
):
    read = _invocation(
        principal=ToolPrincipal.CONTEXT_BROKER,
        tool=ToolName.READ_POLICY,
    )
    store = _ApprovalStore(None)
    authorizer = ToolAuthorizer(store, clock=lambda: _NOW)

    permit = await authorizer.authorize(read)

    assert permit.approval is None
    assert permit.action_scope is None
    assert store.calls == 0
    write = _invocation(
        principal=ToolPrincipal.CONTEXT_BROKER,
        tool=ToolName.CREATE_WORK_ORDER,
        action_id=uuid4(),
    )
    with pytest.raises(ToolAuthorizationError) as error:
        await authorizer.authorize(write, approval_token="any-token")
    assert error.value.failure is ToolAuthorizationFailure.GRANT_NOT_FOUND
    assert store.calls == 0


@pytest.mark.asyncio
async def test_write_tool_requires_one_exact_action_scoped_approval_token() -> None:
    invocation = _invocation(action_id=uuid4())
    authorizer, store = _authorizer(invocation)

    with pytest.raises(ToolAuthorizationError) as missing:
        await authorizer.authorize(invocation)
    assert missing.value.failure is ToolAuthorizationFailure.MISSING_APPROVAL_TOKEN
    assert store.calls == 0

    permit = await authorizer.authorize(invocation, approval_token="approval-token")

    assert permit.approval is not None
    assert permit.action_scope == action_scope_for(invocation)
    assert store.calls == 1
    assert invocation_digest(invocation) == invocation_digest(invocation)

    with pytest.raises(ToolAuthorizationError) as reused:
        await authorizer.authorize(invocation, approval_token="approval-token")
    assert reused.value.failure is ToolAuthorizationFailure.INVALID_APPROVAL_TOKEN


@pytest.mark.asyncio
async def test_token_for_one_action_cannot_authorise_another_action_or_permit() -> None:
    approved = _invocation(action_id=uuid4())
    authorizer, store = _authorizer(approved)
    another_action = _invocation(action_id=uuid4())

    with pytest.raises(ToolAuthorizationError) as rejected:
        await authorizer.authorize(another_action, approval_token="approval-token")
    assert rejected.value.failure is ToolAuthorizationFailure.INVALID_APPROVAL_TOKEN
    assert store.calls == 1

    permit = await authorizer.authorize(approved, approval_token="approval-token")
    permit.require_exact_invocation(approved)
    with pytest.raises(ToolAuthorizationError) as mismatch:
        permit.require_exact_invocation(another_action)
    assert mismatch.value.failure is ToolAuthorizationFailure.GRANT_NOT_FOUND


@pytest.mark.asyncio
async def test_competing_write_calls_can_consume_a_token_only_once() -> None:
    invocation = _invocation(action_id=uuid4())
    authorizer, _ = _authorizer(invocation)

    results = await asyncio.gather(
        authorizer.authorize(invocation, approval_token="approval-token"),
        authorizer.authorize(invocation, approval_token="approval-token"),
        return_exceptions=True,
    )

    assert sum(not isinstance(result, BaseException) for result in results) == 1
    failure = next(result for result in results if isinstance(result, BaseException))
    assert isinstance(failure, ToolAuthorizationError)
    assert failure.failure is ToolAuthorizationFailure.INVALID_APPROVAL_TOKEN


@pytest.mark.asyncio
async def test_unavailable_token_store_fails_closed_without_exposing_the_token() -> (
    None
):
    invocation = _invocation(action_id=uuid4())
    authorizer = ToolAuthorizer(_UnavailableApprovalStore(), clock=lambda: _NOW)

    with pytest.raises(ToolAuthorizationError) as error:
        await authorizer.authorize(invocation, approval_token="secret-token-value")

    assert error.value.failure is ToolAuthorizationFailure.APPROVAL_STORE_UNAVAILABLE
    assert "secret-token-value" not in str(error.value)
