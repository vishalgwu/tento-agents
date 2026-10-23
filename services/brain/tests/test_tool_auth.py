"""Server grants remain enforced without interactive gates."""

from uuid import uuid4
import pytest
from brain.guardrails.tool_auth import (
    ToolAuthorizer,
    ToolInvocation,
    ToolName,
    ToolPrincipal,
    ToolAuthorizationError,
    action_scope_for,
)


def invocation(
    principal: ToolPrincipal, tool: ToolName, *, action: bool = False
) -> ToolInvocation:
    return ToolInvocation(
        org_id=uuid4(),
        run_id=uuid4(),
        ticket_id=uuid4(),
        principal=principal,
        tool=tool,
        action_id=uuid4() if action else None,
    )


@pytest.mark.asyncio
async def test_context_broker_cannot_write() -> None:
    with pytest.raises(ToolAuthorizationError):
        await ToolAuthorizer().authorize(
            invocation(
                ToolPrincipal.CONTEXT_BROKER, ToolName.CREATE_WORK_ORDER, action=True
            )
        )


@pytest.mark.asyncio
async def test_write_requires_server_action_identity_and_exact_permit() -> None:
    authorizer = ToolAuthorizer()
    with pytest.raises(ToolAuthorizationError):
        await authorizer.authorize(
            invocation(ToolPrincipal.ORCHESTRATOR, ToolName.CREATE_WORK_ORDER)
        )
    call = invocation(
        ToolPrincipal.ORCHESTRATOR, ToolName.CREATE_WORK_ORDER, action=True
    )
    permit = await authorizer.authorize(call)
    assert permit.action_scope == action_scope_for(call)
    permit.require_exact_invocation(call)
    with pytest.raises(ToolAuthorizationError):
        permit.require_exact_invocation(
            invocation(
                ToolPrincipal.ORCHESTRATOR, ToolName.CREATE_WORK_ORDER, action=True
            )
        )
