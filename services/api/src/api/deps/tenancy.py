"""Tenant-bound request dependencies and explicit organisation query scoping.

Postgres RLS is the final tenant-isolation boundary. This module supplies the
second boundary: routes pass the authenticated request scope into every query
and establish the matching transaction-local context before query execution.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from fastapi import Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.sql.elements import ColumnElement

from api.db import AppRole, TenantContext, set_rls_context, tenant_session
from api.deps.auth import AuthenticatedPrincipal, get_current_principal


@dataclass(frozen=True, slots=True)
class TenantScope:
    """The authenticated organisation boundary for one API request.

    Routes must use ``scope.org_filter(table.c.org_id)`` (or its ORM
    equivalent) in every tenant-table query. It is intentionally not possible
    to substitute an organisation id supplied by a client.
    """

    org_id: UUID
    person_id: UUID
    role: AppRole
    subject_id: UUID

    @property
    def rls_context(self) -> TenantContext:
        """Return the exact transaction-local RLS context for the request."""

        return TenantContext(
            org_id=self.org_id, person_id=self.person_id, role=self.role
        )

    def org_filter(self, org_id_column: ColumnElement[Any]) -> ColumnElement[bool]:
        """Return the mandatory explicit predicate for a tenant-table query.

        Example: ``select(tickets).where(scope.org_filter(tickets.c.org_id))``.
        This remains required even though RLS independently enforces the same
        organisation boundary.
        """

        return org_id_column == self.org_id

    def require_matching_org(self, candidate_org_id: UUID) -> UUID:
        """Reject a client-provided organisation id outside this request scope.

        A 404 avoids confirming that an organisation outside the caller's scope
        exists. Query construction must still apply ``org_filter``.
        """

        if candidate_org_id != self.org_id:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Resource not found",
            )
        return self.org_id


async def get_tenant_scope(
    principal: AuthenticatedPrincipal = Depends(get_current_principal),
) -> TenantScope:
    """Derive a request scope only from cryptographically verified claims."""

    return TenantScope(
        org_id=principal.org_id,
        person_id=principal.person_id,
        role=principal.role,
        subject_id=principal.subject_id,
    )


async def set_request_rls_context(session: AsyncSession, scope: TenantScope) -> None:
    """Set transaction-local PostgreSQL RLS state before any tenant query.

    The active ``AsyncSession`` must already be inside ``session.begin()``. The
    lower-level setter rejects accidental connection-scoped use, preventing state
    from leaking through the async connection pool.
    """

    await set_rls_context(session, scope.rls_context)


@asynccontextmanager
async def tenant_request_session(
    session_factory: async_sessionmaker[AsyncSession],
    scope: TenantScope,
) -> AsyncIterator[AsyncSession]:
    """Open one request transaction with its RLS context already established.

    Routes should use this bridge instead of a bare session and still add
    ``scope.org_filter(...)`` to every organisation-scoped statement.
    """

    async with tenant_session(session_factory, scope.rls_context) as session:
        yield session
