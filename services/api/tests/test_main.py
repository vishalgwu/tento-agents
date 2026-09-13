from __future__ import annotations

import httpx
import pytest

from api.main import create_app
from api.middleware.request_id import REQUEST_ID_HEADER


def test_application_registers_the_documented_request_order() -> None:
    app = create_app()

    assert [
        getattr(middleware.cls, "__name__", "") for middleware in app.user_middleware
    ] == [
        "RequestIdMiddleware",
        "ProblemDetailsMiddleware",
        "AuthenticationMiddleware",
        "TenantRlsContextMiddleware",
        "RateLimitMiddleware",
        "IdempotencyMiddleware",
    ]


@pytest.mark.asyncio
async def test_health_reports_unavailable_dependencies_without_error_details() -> None:
    app = create_app()
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/healthz")

    assert response.status_code == 503
    assert response.json() == {
        "status": "degraded",
        "components": {"database": "unavailable", "redis": "unavailable"},
    }
    assert response.headers[REQUEST_ID_HEADER]


@pytest.mark.asyncio
async def test_request_id_is_a_uuid_and_continues_a_valid_client_trace() -> None:
    app = create_app()
    transport = httpx.ASGITransport(app=app)
    supplied_request_id = "f7ac5661-7871-4491-9f06-b94be6cc8c5a"
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(
            "/healthz", headers={REQUEST_ID_HEADER: supplied_request_id}
        )

    assert response.headers[REQUEST_ID_HEADER] == supplied_request_id
