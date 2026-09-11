"""FastAPI application assembly for the Resident OS public API.

Runtime request order is problem conversion -> authentication -> tenant RLS ->
rate limit -> idempotency -> routing.  The problem layer is registered last so
it wraps the other middleware and renders failures after they propagate.
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Final

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, Response
from redis.asyncio import Redis
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from api.db import create_database_engine, create_session_factory
from api.middleware.authentication import AuthenticationMiddleware
from api.middleware.errors import ProblemDetailsMiddleware, install_problem_handlers
from api.middleware.idempotency import IdempotencyMiddleware, PostgresIdempotencyStore
from api.middleware.rate_limit import (
    RateLimitMiddleware,
    RateLimitSettings,
    RedisFixedWindowRateLimiter,
)
from api.middleware.tenancy import TenantRlsContextMiddleware


_LOCAL_DATABASE_URL: Final = (
    "postgresql+asyncpg://postgres:postgres@localhost:5432/resident_os"
)
_LOCAL_REDIS_URL: Final = "redis://localhost:6379/0"


@dataclass(frozen=True, slots=True)
class ApiSettings:
    """Runtime infrastructure settings; secrets never enter request state or logs."""

    database_url: str
    redis_url: str

    @classmethod
    def from_environment(cls) -> ApiSettings:
        return cls(
            database_url=os.environ.get("DATABASE_URL", _LOCAL_DATABASE_URL),
            redis_url=os.environ.get("REDIS_URL", _LOCAL_REDIS_URL),
        )


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Create and close the shared, non-service-role API infrastructure clients."""

    settings = ApiSettings.from_environment()
    engine = create_database_engine(settings.database_url)
    cache = Redis.from_url(settings.redis_url, decode_responses=False)
    app.state.database_engine = engine
    app.state.session_factory = create_session_factory(engine)
    app.state.redis_client = cache
    app.state.rate_limiter = RedisFixedWindowRateLimiter(
        cache,
        RateLimitSettings.from_environment(),
    )
    app.state.idempotency_store = PostgresIdempotencyStore()
    try:
        yield
    finally:
        await cache.aclose()
        await engine.dispose()


def create_app() -> FastAPI:
    """Build the API with the documented ingress order and no speculative routes."""

    app = FastAPI(
        title="Resident OS API",
        version="0.1.0",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
        lifespan=lifespan,
    )
    install_problem_handlers(app)

    # Starlette executes the last added middleware first. This registration
    # therefore produces the documented request pipeline listed in this file.
    app.add_middleware(IdempotencyMiddleware)
    app.add_middleware(RateLimitMiddleware)
    app.add_middleware(TenantRlsContextMiddleware)
    app.add_middleware(AuthenticationMiddleware)
    app.add_middleware(ProblemDetailsMiddleware)

    app.add_api_route("/healthz", health, methods=["GET"], include_in_schema=False)
    return app


async def health(request: Request) -> Response:
    """Report only database and Redis readiness, never their exception details."""

    database_ok = await _database_is_ready(
        getattr(request.app.state, "database_engine", None)
    )
    cache_ok = await _cache_is_ready(getattr(request.app.state, "redis_client", None))
    healthy = database_ok and cache_ok
    return JSONResponse(
        status_code=200 if healthy else 503,
        content={
            "status": "ok" if healthy else "degraded",
            "components": {
                "database": "ok" if database_ok else "unavailable",
                "redis": "ok" if cache_ok else "unavailable",
            },
        },
    )


async def _database_is_ready(engine: AsyncEngine | None) -> bool:
    if engine is None:
        return False
    try:
        async with engine.connect() as connection:
            await connection.execute(text("SELECT 1"))
    except Exception:
        return False
    return True


async def _cache_is_ready(cache: Redis | None) -> bool:
    if cache is None:
        return False
    try:
        await cache.ping()
    except Exception:
        return False
    return True


app = create_app()
