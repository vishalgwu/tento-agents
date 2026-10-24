"""Verified identity for workspace routing; never a client-selected role."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from api.db import AppRole
from api.deps.tenancy import TenantScope, get_request_tenant_scope

router = APIRouter(prefix="/v1", tags=["identity"])


class Identity(BaseModel):
    org_id: UUID
    person_id: UUID
    role: AppRole


@router.get("/me", response_model=Identity)
async def get_identity(
    scope: Annotated[TenantScope, Depends(get_request_tenant_scope)],
) -> Identity:
    return Identity(org_id=scope.org_id, person_id=scope.person_id, role=scope.role)
