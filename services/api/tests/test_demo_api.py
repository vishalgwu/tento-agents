"""Demo flag, trusted identity and sanitized failure behavior."""

from uuid import uuid4

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from api.deps.tenancy import TenantScope
from api.routers import demo


@pytest.mark.asyncio
async def test_demo_uses_only_the_verified_actor_scope(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DEMO_MODE", "true")
    actor = uuid4()
    scope = TenantScope(
        org_id=actor, person_id=uuid4(), subject_id=uuid4(), role="operations_admin"
    )

    async def execute(description: str, *, actor_org_id: object) -> dict[str, object]:
        assert actor_org_id == actor
        assert description == "cabinet hinge"
        return {"synthetic": True}

    monkeypatch.setattr(demo, "execute_demo", execute)
    assert await demo.run_demo(
        demo.DemoRequest(description="cabinet hinge"), scope
    ) == {"synthetic": True}
    with pytest.raises(ValidationError):
        demo.DemoRequest.model_validate(
            {"description": "hinge", "org_id": str(uuid4())}
        )
    monkeypatch.setenv("DEMO_MODE", "false")
    with pytest.raises(HTTPException) as error:
        await demo.run_demo(demo.DemoRequest(description="cabinet hinge"), scope)
    assert error.value.status_code == 404


@pytest.mark.asyncio
async def test_demo_provider_error_does_not_echo_secrets(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DEMO_MODE", "true")
    scope = TenantScope(
        org_id=uuid4(), person_id=uuid4(), subject_id=uuid4(), role="resident"
    )

    async def broken(*args: object, **kwargs: object) -> dict[str, object]:
        raise ValueError("sensitive-upstream-detail")

    monkeypatch.setattr(demo, "execute_demo", broken)
    with pytest.raises(HTTPException) as error:
        await demo.run_demo(demo.DemoRequest(description="cabinet hinge"), scope)
    assert error.value.status_code == 503
    assert "sensitive" not in error.value.detail
