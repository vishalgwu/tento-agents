from __future__ import annotations

from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import column, select, table

from api.deps.tenancy import TenantScope, set_request_rls_context


def _scope() -> TenantScope:
    return TenantScope(
        org_id=uuid4(),
        person_id=uuid4(),
        subject_id=uuid4(),
        role="property_manager",
    )


def test_org_filter_binds_only_the_verified_organisation_id() -> None:
    scope = _scope()
    tickets = table("tickets", column("org_id"))

    statement = select(tickets).where(scope.org_filter(tickets.c.org_id))
    assert list(statement.compile().params.values()) == [scope.org_id]


def test_scope_does_not_reveal_an_out_of_scope_organisation() -> None:
    scope = _scope()

    with pytest.raises(HTTPException) as error:
        scope.require_matching_org(uuid4())

    assert error.value.status_code == 404


class _RecordingSession:
    def __init__(self) -> None:
        self.calls: list[dict[str, str]] = []

    def in_transaction(self) -> bool:
        return True

    async def execute(self, _statement: object, parameters: dict[str, str]) -> None:
        self.calls.append(parameters)


@pytest.mark.asyncio
async def test_request_context_sets_all_rls_values_before_tenant_query() -> None:
    scope = _scope()
    session = _RecordingSession()

    await set_request_rls_context(session, scope)  # type: ignore[arg-type]

    assert session.calls == [
        {"org_id": str(scope.org_id)},
        {"person_id": str(scope.person_id)},
        {"role": "property_manager"},
    ]
