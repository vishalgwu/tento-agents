"""Database primitives for the Resident OS public API.

Every API request and background job must establish a transaction-local tenant
context before accessing tenant-scoped tables.  PostgreSQL RLS in
``infra/migrations/0002_rls.sql`` is the final isolation boundary; this module
provides the only supported API-side path for setting that context.

This module intentionally exposes no Supabase service-role client and no
browser-facing credential.  Authentication will provide a verified
``TenantContext`` before a route opens a tenant session.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Final, Literal
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine


AppRole = Literal[
    "resident",
    "property_manager",
    "maintenance_technician",
    "vendor_contact",
    "asset_owner",
    "operations_admin",
]

VALID_APP_ROLES: Final = frozenset(
    {
        "resident",
        "property_manager",
        "maintenance_technician",
        "vendor_contact",
        "asset_owner",
        "operations_admin",
    }
)


@dataclass(frozen=True, slots=True)
class TenantContext:
    """Verified principal data used by Postgres row-level security.

    ``person_id`` is optional for authenticated system work that does not act
    as a person.  When absent, the setter explicitly clears the setting so a
    previous pooled connection value cannot leak into the next transaction.
    """

    org_id: UUID
    role: AppRole
    person_id: UUID | None = None

    def __post_init__(self) -> None:
        if self.role not in VALID_APP_ROLES:
            raise ValueError(f"Unsupported application role: {self.role}")


def create_database_engine(database_url: str) -> AsyncEngine:
    """Build the API's async PostgreSQL engine without SQL or PII logging."""

    if not database_url.startswith("postgresql+asyncpg://"):
        raise ValueError("DATABASE_URL must use the postgresql+asyncpg driver")

    return create_async_engine(
        database_url,
        echo=False,
        pool_pre_ping=True,
        pool_recycle=1_800,
    )


def create_session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    """Return sessions that retain no ORM state after a request completes."""

    return async_sessionmaker(engine, autoflush=False, expire_on_commit=False)


async def set_rls_context(session: AsyncSession, context: TenantContext) -> None:
    """Set the three RLS settings within an already-open transaction.

    PostgreSQL's ``set_config(..., true)`` has the same scope as ``SET LOCAL``:
    the values disappear at commit or rollback.  Calling this outside a
    transaction is forbidden because a pooled connection could otherwise carry
    tenant state across requests.
    """

    if not session.in_transaction():
        raise RuntimeError("RLS context must be set inside an open transaction")

    await session.execute(
        text("SELECT set_config('app.current_org_id', :org_id, true)"),
        {"org_id": str(context.org_id)},
    )
    await session.execute(
        text("SELECT set_config('app.current_person_id', :person_id, true)"),
        {"person_id": str(context.person_id) if context.person_id is not None else ""},
    )
    await session.execute(
        text("SELECT set_config('app.current_role', :role, true)"),
        {"role": context.role},
    )


@asynccontextmanager
async def tenant_session(
    session_factory: async_sessionmaker[AsyncSession],
    context: TenantContext,
) -> AsyncIterator[AsyncSession]:
    """Yield one transaction-bound session with RLS context already set.

    Routes and jobs should use this helper rather than opening a bare session.
    It guarantees context cleanup at the transaction boundary even when the
    request fails or the connection returns to the pool.
    """

    async with session_factory() as session:
        async with session.begin():
            await set_rls_context(session, context)
            yield session
