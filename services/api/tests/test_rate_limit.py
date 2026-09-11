from __future__ import annotations

from uuid import uuid4

import pytest

from api.deps.tenancy import TenantScope
from api.middleware.rate_limit import RateLimitSettings, RedisFixedWindowRateLimiter


class _Redis:
    def __init__(self, count: int, ttl: int) -> None:
        self.count = count
        self.ttl_value = ttl
        self.keys: list[str] = []

    async def eval(self, _script: str, _numkeys: int, key: str, _window: str) -> int:
        self.keys.append(key)
        return self.count

    async def ttl(self, _key: str) -> int:
        return self.ttl_value


def _scope() -> TenantScope:
    return TenantScope(
        org_id=uuid4(),
        person_id=uuid4(),
        subject_id=uuid4(),
        role="property_manager",
    )


@pytest.mark.asyncio
async def test_rate_limit_allows_requests_within_budget() -> None:
    redis = _Redis(count=2, ttl=45)
    limiter = RedisFixedWindowRateLimiter(
        redis, RateLimitSettings(requests_per_window=3, window_seconds=60)
    )  # type: ignore[arg-type]

    decision = await limiter.check(_scope())

    assert decision.allowed is True
    assert decision.remaining == 1
    assert decision.retry_after_seconds == 45
    assert redis.keys[0].startswith("resident-os:rate:")


@pytest.mark.asyncio
async def test_rate_limit_rejects_requests_over_budget() -> None:
    limiter = RedisFixedWindowRateLimiter(
        _Redis(count=4, ttl=1),  # type: ignore[arg-type]
        RateLimitSettings(requests_per_window=3, window_seconds=60),
    )

    decision = await limiter.check(_scope())

    assert decision.allowed is False
    assert decision.remaining == -1
    assert decision.retry_after_seconds == 1
