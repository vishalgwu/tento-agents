"""Stable, safe HTTP problem responses for the Resident OS API.

The API follows the RFC 7807 problem-details shape, updated by RFC 9457.  All
client-visible details are selected by this module; exception messages, request
bodies, database errors, and provider responses are never reflected to callers.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from dataclasses import dataclass
from enum import Enum
from typing import Final

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, Response
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint


PROBLEM_MEDIA_TYPE: Final = "application/problem+json"
PROBLEM_TYPE_PREFIX: Final = "urn:resident-os:problem:"
_LOGGER = logging.getLogger(__name__)


class ProblemType(str, Enum):
    """Stable namespaced problem types exposed by the API."""

    authentication_required = "authentication-required"
    authentication_unavailable = "authentication-unavailable"
    dependency_unavailable = "dependency-unavailable"
    forbidden = "forbidden"
    idempotency_key_required = "idempotency-key-required"
    idempotency_key_reused = "idempotency-key-reused"
    idempotency_response_too_large = "idempotency-response-too-large"
    invalid_request = "invalid-request"
    method_not_allowed = "method-not-allowed"
    not_found = "not-found"
    rate_limited = "rate-limited"
    request_in_progress = "request-in-progress"
    tenant_context_unavailable = "tenant-context-unavailable"
    unexpected_error = "unexpected-error"

    @property
    def uri(self) -> str:
        return f"{PROBLEM_TYPE_PREFIX}{self.value}"


@dataclass(frozen=True, slots=True)
class ProblemDefinition:
    """Safe public description shared by every instance of one problem type."""

    type: ProblemType
    status_code: int
    title: str
    detail: str


class ProblemDetailsException(Exception):
    """A deliberate public error whose fields have already been sanitised."""

    def __init__(
        self,
        definition: ProblemDefinition,
        *,
        headers: Mapping[str, str] | None = None,
    ) -> None:
        super().__init__(definition.type.value)
        self.definition = definition
        self.headers = dict(headers or {})


def problem(
    type: ProblemType,
    status_code: int,
    title: str,
    detail: str,
) -> ProblemDefinition:
    """Construct one explicit, stable problem definition."""

    return ProblemDefinition(
        type=type,
        status_code=status_code,
        title=title,
        detail=detail,
    )


AUTHENTICATION_REQUIRED = problem(
    ProblemType.authentication_required,
    401,
    "Authentication required",
    "A valid bearer token is required for this resource.",
)
AUTHENTICATION_UNAVAILABLE = problem(
    ProblemType.authentication_unavailable,
    503,
    "Authentication temporarily unavailable",
    "The service cannot validate credentials at this time.",
)
DEPENDENCY_UNAVAILABLE = problem(
    ProblemType.dependency_unavailable,
    503,
    "Dependency temporarily unavailable",
    "The service cannot complete this request at this time.",
)
FORBIDDEN = problem(
    ProblemType.forbidden,
    403,
    "Forbidden",
    "You are not authorised to perform this action.",
)
IDEMPOTENCY_KEY_REQUIRED = problem(
    ProblemType.idempotency_key_required,
    400,
    "Idempotency key required",
    "Mutating requests require exactly one Idempotency-Key header.",
)
IDEMPOTENCY_KEY_REUSED = problem(
    ProblemType.idempotency_key_reused,
    409,
    "Idempotency key reused",
    "This Idempotency-Key was already used for a different request.",
)
IDEMPOTENCY_RESPONSE_TOO_LARGE = problem(
    ProblemType.idempotency_response_too_large,
    500,
    "Idempotency response too large",
    "The service could not safely persist the response for replay.",
)
INVALID_REQUEST = problem(
    ProblemType.invalid_request,
    422,
    "Invalid request",
    "The request could not be validated.",
)
METHOD_NOT_ALLOWED = problem(
    ProblemType.method_not_allowed,
    405,
    "Method not allowed",
    "This HTTP method is not allowed for the resource.",
)
NOT_FOUND = problem(
    ProblemType.not_found,
    404,
    "Resource not found",
    "The requested resource was not found.",
)
RATE_LIMITED = problem(
    ProblemType.rate_limited,
    429,
    "Rate limit exceeded",
    "Too many requests were made. Retry after the indicated delay.",
)
REQUEST_IN_PROGRESS = problem(
    ProblemType.request_in_progress,
    409,
    "Request already in progress",
    "The original request for this Idempotency-Key has not completed yet.",
)
TENANT_CONTEXT_UNAVAILABLE = problem(
    ProblemType.tenant_context_unavailable,
    503,
    "Tenant context temporarily unavailable",
    "The service cannot establish the tenant data boundary at this time.",
)
UNEXPECTED_ERROR = problem(
    ProblemType.unexpected_error,
    500,
    "Unexpected server error",
    "The service could not complete the request.",
)


_HTTP_PROBLEMS: Final = {
    400: problem(
        ProblemType.invalid_request,
        400,
        "Invalid request",
        "The request could not be processed.",
    ),
    401: AUTHENTICATION_REQUIRED,
    403: FORBIDDEN,
    404: NOT_FOUND,
    405: METHOD_NOT_ALLOWED,
    422: INVALID_REQUEST,
    429: RATE_LIMITED,
    503: DEPENDENCY_UNAVAILABLE,
}
_SAFE_EXCEPTION_HEADERS: Final = frozenset({"allow", "retry-after", "www-authenticate"})


def create_problem_response(
    request: Request,
    definition: ProblemDefinition,
    *,
    headers: Mapping[str, str] | None = None,
) -> JSONResponse:
    """Serialize one problem without reflecting query, body, or exception data."""

    payload = {
        "type": definition.type.uri,
        "title": definition.title,
        "status": definition.status_code,
        "detail": definition.detail,
        "instance": request.url.path,
    }
    return JSONResponse(
        status_code=definition.status_code,
        content=payload,
        media_type=PROBLEM_MEDIA_TYPE,
        headers=dict(headers or {}),
    )


async def problem_details_exception_handler(
    request: Request,
    error: ProblemDetailsException,
) -> Response:
    """Render an intentionally public problem raised by a route or middleware."""

    return create_problem_response(request, error.definition, headers=error.headers)


async def http_exception_handler(
    request: Request,
    error: StarletteHTTPException,
) -> Response:
    """Convert framework HTTP errors without exposing their ``detail`` value."""

    definition = _HTTP_PROBLEMS.get(error.status_code)
    if definition is None:
        definition = UNEXPECTED_ERROR if error.status_code >= 500 else INVALID_REQUEST
        definition = ProblemDefinition(
            type=definition.type,
            status_code=error.status_code,
            title=definition.title,
            detail=definition.detail,
        )
    headers = {
        name: value
        for name, value in (error.headers or {}).items()
        if name.lower() in _SAFE_EXCEPTION_HEADERS
    }
    return create_problem_response(request, definition, headers=headers)


async def validation_exception_handler(
    request: Request,
    _error: RequestValidationError,
) -> Response:
    """Return a stable validation problem without echoing submitted values."""

    return create_problem_response(request, INVALID_REQUEST)


async def unhandled_exception_handler(request: Request, _error: Exception) -> Response:
    """Return a generic error and log only safe request metadata."""

    _LOGGER.error(
        "unhandled_api_exception",
        extra={"method": request.method, "path": request.url.path},
    )
    return create_problem_response(request, UNEXPECTED_ERROR)


class ProblemDetailsMiddleware(BaseHTTPMiddleware):
    """Catch errors raised by outer application middleware before routing begins."""

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        try:
            return await call_next(request)
        except ProblemDetailsException as error:
            return await problem_details_exception_handler(request, error)
        except Exception as error:
            return await unhandled_exception_handler(request, error)


def install_problem_handlers(app: FastAPI) -> None:
    """Install route-level problem handlers alongside the outer middleware."""

    app.add_exception_handler(ProblemDetailsException, _registered_problem_handler)
    app.add_exception_handler(StarletteHTTPException, _registered_http_handler)
    app.add_exception_handler(RequestValidationError, _registered_validation_handler)
    app.add_exception_handler(Exception, unhandled_exception_handler)


async def _registered_problem_handler(request: Request, error: Exception) -> Response:
    if isinstance(error, ProblemDetailsException):
        return await problem_details_exception_handler(request, error)
    return await unhandled_exception_handler(request, error)


async def _registered_http_handler(request: Request, error: Exception) -> Response:
    if isinstance(error, StarletteHTTPException):
        return await http_exception_handler(request, error)
    return await unhandled_exception_handler(request, error)


async def _registered_validation_handler(
    request: Request, error: Exception
) -> Response:
    if isinstance(error, RequestValidationError):
        return await validation_exception_handler(request, error)
    return await unhandled_exception_handler(request, error)
