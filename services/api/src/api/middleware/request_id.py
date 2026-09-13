"""Safe request-correlation identifiers for API ingress and error responses."""

from __future__ import annotations

from typing import Final
from uuid import UUID, uuid4

from fastapi import Request
from fastapi.responses import Response
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint


REQUEST_ID_HEADER: Final = "X-Request-ID"


class RequestIdMiddleware(BaseHTTPMiddleware):
    """Attach one UUID request identifier before authentication and error handling.

    A caller may continue an existing trace only with a syntactically valid UUID.
    Invalid, oversized, and multi-value headers are replaced rather than echoed,
    so an untrusted header cannot become an uncontrolled log value.
    """

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        request_id = _request_id(request)
        request.state.request_id = request_id
        response = await call_next(request)
        response.headers[REQUEST_ID_HEADER] = request_id
        return response


def _request_id(request: Request) -> str:
    values = request.headers.getlist(REQUEST_ID_HEADER)
    if len(values) != 1:
        return str(uuid4())
    try:
        return str(UUID(values[0]))
    except (TypeError, ValueError, AttributeError):
        return str(uuid4())
