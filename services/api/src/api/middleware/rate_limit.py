"""Redis-backed fixed-window rate limiting for authenticated API requests."""

from __future__ import annotations

import os
import time
from dataclasses import dataclass
from typing import Any, Awaitable, Final, cast

from fastapi import Request
from fastapi.responses import Response
from redis.asyncio import Redis
from redis.exceptions import RedisError
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint

from api.deps.tenancy import TenantScope
from api.middleware.errors import (
    DEPENDENCY_UNAVAILABLE,
    ProblemDetailsException,
    RATE_LIMITED,
)


_FIXED_WINDOW_INCREMENT: Final = """
local count = redis.call('INCR', KEYS[1])
if count == 1 then
  redis.call('EXPIRE', KEYS[1], ARGV[1])
end
return count
"""


class RateLimitUnavailable(Exception):
    """Redis could not make a bounded ingress decision."""


@dataclass(frozen=True, slots=True)
class RateLimitSettings:
    """Fixed-window configuration, deliberately bounded to prevent bad config."""

    requests_per_window: int = 120
    window_seconds: int = 60

    def __post_init__(self) -> None:
        if not 1 <= self.requests_per_window <= 10_000:
            raise ValueError("API_RATE_LIMIT_REQUESTS must be between 1 and 10000")
        if not 1 <= self.window_seconds <= 3_600:
            raise ValueError("API_RATE_LIMIT_WINDOW_SECONDS must be between 1 and 3600")

    @classmethod
    def from_environment(cls) -> RateLimitSettings:
        try:
            return cls(
                requests_per_window=int(
                    os.environ.get("API_RATE_LIMIT_REQUESTS", "120")
                ),
                window_seconds=int(
                    os.environ.get("API_RATE_LIMIT_WINDOW_SECONDS", "60")
                ),
            )
        except ValueError as error:
            raise ValueError(
                "API rate-limit configuration must contain integers"
            ) from error


@dataclass(frozen=True, slots=True)
class RateLimitDecision:
    """Result of one atomic increment, safe to expose through response headers."""

    limit: int
    remaining: int
    retry_after_seconds: int

    @property
    def allowed(self) -> bool:
        return self.remaining >= 0


class RedisFixedWindowRateLimiter:
    """Use one Redis script so increment and expiry cannot be interleaved."""

    _KEY_PREFIX: Final = "resident-os:rate"

    def __init__(self, client: Redis, settings: RateLimitSettings) -> None:
        self._client = client
        self._settings = settings

    async def check(self, scope: TenantScope) -> RateLimitDecision:
        window = int(time.time() // self._settings.window_seconds)
        key = ":".join(
            (
                self._KEY_PREFIX,
                str(scope.org_id),
                str(scope.person_id),
                str(window),
            )
        )
        try:
            raw_count = await cast(
                Awaitable[Any],
                self._client.eval(
                    _FIXED_WINDOW_INCREMENT,
                    1,
                    key,
                    str(self._settings.window_seconds),
                ),
            )
            count = int(raw_count)
            ttl = int(await self._client.ttl(key))
        except RedisError as error:
            raise RateLimitUnavailable from error

        retry_after = ttl if ttl > 0 else self._settings.window_seconds
        return RateLimitDecision(
            limit=self._settings.requests_per_window,
            remaining=self._settings.requests_per_window - count,
            retry_after_seconds=retry_after,
        )


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Enforce a tenant-person rate budget after RLS scope is established."""

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        scope = getattr(request.state, "tenant_scope", None)
        if scope is None:
            return await call_next(request)
        if not isinstance(scope, TenantScope):
            raise ProblemDetailsException(DEPENDENCY_UNAVAILABLE)

        limiter = getattr(request.app.state, "rate_limiter", None)
        if not isinstance(limiter, RedisFixedWindowRateLimiter):
            raise ProblemDetailsException(DEPENDENCY_UNAVAILABLE)

        try:
            decision = await limiter.check(scope)
        except RateLimitUnavailable as error:
            raise ProblemDetailsException(DEPENDENCY_UNAVAILABLE) from error

        headers = {
            "X-RateLimit-Limit": str(decision.limit),
            "X-RateLimit-Remaining": str(max(decision.remaining, 0)),
        }
        if not decision.allowed:
            headers["Retry-After"] = str(decision.retry_after_seconds)
            raise ProblemDetailsException(RATE_LIMITED, headers=headers)

        response = await call_next(request)
        response.headers.update(headers)
        return response
