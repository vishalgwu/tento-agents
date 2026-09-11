"""Authentication middleware for versioned public API routes."""

from __future__ import annotations

from fastapi import Request
from fastapi.responses import Response
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint

from api.deps.auth import (
    InvalidAccessToken,
    JwtConfigurationError,
    JwtKeySetUnavailable,
    authenticate_bearer_authorization,
    get_supabase_jwt_verifier,
)
from api.middleware.errors import (
    AUTHENTICATION_REQUIRED,
    AUTHENTICATION_UNAVAILABLE,
    ProblemDetailsException,
)


class AuthenticationMiddleware(BaseHTTPMiddleware):
    """Attach a verified principal before any versioned API handler executes."""

    _API_PREFIX = "/v1/"

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        if not request.url.path.startswith(self._API_PREFIX):
            return await call_next(request)

        try:
            verifier = get_supabase_jwt_verifier()
            request.state.principal = await authenticate_bearer_authorization(
                request.headers.get("Authorization"), verifier
            )
        except InvalidAccessToken as error:
            raise ProblemDetailsException(
                AUTHENTICATION_REQUIRED,
                headers={"WWW-Authenticate": "Bearer"},
            ) from error
        except (JwtConfigurationError, JwtKeySetUnavailable) as error:
            raise ProblemDetailsException(
                AUTHENTICATION_UNAVAILABLE,
                headers={"WWW-Authenticate": "Bearer"},
            ) from error

        return await call_next(request)
