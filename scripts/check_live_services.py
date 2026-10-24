"""Read-only connection checks; never print credentials or exception details."""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path

import httpx
from dotenv import load_dotenv
from redis.asyncio import Redis
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine


async def main() -> None:
    load_dotenv(Path(__file__).resolve().parents[1] / ".env", override=False)
    results: dict[str, object] = {}
    for name in ("DATABASE_URL", "WORKER_DATABASE_URL"):
        if not os.getenv(name):
            results[name] = "missing"
            continue
        engine = create_async_engine(os.environ[name], connect_args={"timeout": 15})
        try:
            async with engine.connect() as connection:
                row = (
                    await connection.execute(
                        text(
                            "SELECT rolname, rolsuper, rolbypassrls FROM pg_roles WHERE rolname=current_user"
                        )
                    )
                ).one()
                results[name] = {
                    "connected": True,
                    "expected_role": row[0]
                    == (
                        "resident_api" if name == "DATABASE_URL" else "resident_worker"
                    ),
                    "superuser": row[1],
                    "bypass_rls": row[2],
                }
        except Exception:
            results[name] = "connection_failed"
        finally:
            await engine.dispose()
    cache = Redis.from_url(
        os.environ.get("REDIS_URL", "redis://localhost:6379"),
        socket_connect_timeout=15,
        socket_timeout=15,
    )
    try:
        results["redis"] = "ok" if await cache.ping() else "unavailable"
    except Exception:
        results["redis"] = "connection_failed"
    finally:
        await cache.aclose()
    async with httpx.AsyncClient(timeout=20) as client:
        try:
            response = await client.get(
                os.environ["SUPABASE_URL"].rstrip("/")
                + "/auth/v1/.well-known/jwks.json"
            )
            results["supabase_jwks"] = (
                "ok"
                if response.is_success and response.json().get("keys")
                else "unavailable"
            )
        except Exception:
            results["supabase_jwks"] = "connection_failed"
        try:
            response = await client.get(
                "https://api.openai.com/v1/models/"
                + os.environ.get("OPENAI_MODEL", "gpt-4.1-mini"),
                headers={"Authorization": "Bearer " + os.environ["OPENAI_API_KEY"]},
            )
            results["openai_model_access"] = (
                "ok" if response.is_success else f"http_{response.status_code}"
            )
        except Exception:
            results["openai_model_access"] = "connection_failed"
    print(json.dumps(results, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
