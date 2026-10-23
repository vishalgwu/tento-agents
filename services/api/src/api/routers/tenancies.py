"""The current resident's eligible submission locations."""

from typing import Annotated
from uuid import UUID
from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from api.deps.tenancy import TenantScope, get_request_session, get_request_tenant_scope
from api.routers.tickets import _ACTIVE_TENANCIES

router = APIRouter(prefix="/v1/tenancies", tags=["tenancies"])


class TenancyLocation(BaseModel):
    id: UUID
    property_name: str
    unit_name: str


class TenancyList(BaseModel):
    items: list[TenancyLocation]


@router.get("", response_model=TenancyList)
async def list_tenancies(
    scope: Annotated[TenantScope, Depends(get_request_tenant_scope)],
    session: Annotated[AsyncSession, Depends(get_request_session)],
) -> TenancyList:
    found = await session.execute(
        _ACTIVE_TENANCIES,
        {
            "org_id": str(scope.org_id),
            "person_id": str(scope.person_id),
            "tenancy_id": None,
        },
    )
    return TenancyList(
        items=[
            TenancyLocation(
                id=row["id"],
                property_name=row["property_name"],
                unit_name=row["unit_name"],
            )
            for row in found.mappings().all()
        ]
    )
