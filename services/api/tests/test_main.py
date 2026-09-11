from __future__ import annotations

import httpx
import pytest

from api.main import create_app


def test_application_registers_the_documented_request_order() -> None:
    app = create_app()

    assert [middleware.cls.__name__ for middleware in app.user_middleware] == [
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
