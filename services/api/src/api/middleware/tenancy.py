"""Request middleware that binds verified identity to a single RLS transaction."""

from __future__ import annotations

from fastapi import Request
from fastapi.responses import Response
from sqlalchemy.ext.asyncio import async_sessionmaker
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint

from api.deps.auth import AuthenticatedPrincipal
from api.deps.tenancy import TenantScope, tenant_request_session
from api.middleware.errors import (
    ProblemDetailsException,
    TENANT_CONTEXT_UNAVAILABLE,
)


class TenantRlsContextMiddleware(BaseHTTPMiddleware):
    """Open the RLS-bound session used by all authenticated request work."""

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        principal = getattr(request.state, "principal", None)
        if principal is None:
            return await call_next(request)
        if not isinstance(principal, AuthenticatedPrincipal):
            raise ProblemDetailsException(TENANT_CONTEXT_UNAVAILABLE)

        session_factory = getattr(request.app.state, "session_factory", None)
        if not isinstance(session_factory, async_sessionmaker):
            raise ProblemDetailsException(TENANT_CONTEXT_UNAVAILABLE)

        scope = TenantScope(
            org_id=principal.org_id,
            person_id=principal.person_id,
            role=principal.role,
            subject_id=principal.subject_id,
        )
        request.state.tenant_scope = scope

        async with tenant_request_session(session_factory, scope) as session:
            request.state.db_session = session
            response = await call_next(request)
            # FastAPI route exceptions are rendered as responses. Roll back all
            # request-local writes when one becomes a server error, including any
            # idempotency reservation made earlier in this transaction.
            if response.status_code >= 500:
                await session.rollback()
            return response
