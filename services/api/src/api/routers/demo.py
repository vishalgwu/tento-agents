"""Authenticated, rate-limited access to the fictional policy sandbox."""

import asyncio
import os
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field, field_validator

from api.deps.tenancy import TenantScope, get_tenant_scope
from brain.demo import execute_demo

router = APIRouter(prefix="/v1/demo", tags=["demo"])


class DemoRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    description: str = Field(min_length=1, max_length=2000)

    @field_validator("description")
    @classmethod
    def require_nonblank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("description cannot be blank")
        return value.strip()


@router.post("/run")
async def run_demo(
    body: DemoRequest, scope: TenantScope = Depends(get_tenant_scope)
) -> dict[str, Any]:
    if os.environ.get("DEMO_MODE", "").lower() != "true":
        raise HTTPException(404, "Demo unavailable")
    try:
        async with asyncio.timeout(150):
            return await execute_demo(body.description, actor_org_id=scope.org_id)
    except TimeoutError:
        raise HTTPException(504, "Demo assessment timed out") from None
    except Exception:
        raise HTTPException(503, "Demo assessment unavailable") from None
