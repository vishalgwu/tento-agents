"""Authenticated request-bound processing of one durable maintenance run."""

from __future__ import annotations

import os
import hmac
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.exc import SQLAlchemyError

from api.db import create_database_engine, create_session_factory
from api.deps.tenancy import TenantScope, get_request_session, get_request_tenant_scope
from api.routers.stream import _GET_RUN
from api.worker import process_one
from brain.production import execute_maintenance

router = APIRouter(prefix="/v1/runs", tags=["runs"])
recovery_router = APIRouter(prefix="/internal/worker", include_in_schema=False)


class ProcessingResult(BaseModel):
    run_id: UUID
    processed: bool


@router.post("/{run_id}/process", response_model=ProcessingResult)
async def process_run(
    run_id: UUID,
    scope: Annotated[TenantScope, Depends(get_request_tenant_scope)],
    session: Annotated[AsyncSession, Depends(get_request_session)],
) -> ProcessingResult:
    # Check through the request role and RLS first. Never expose worker access
    # until the caller is authorized to read this exact run and ticket.
    found = await session.execute(
        _GET_RUN,
        {
            "org_id": str(scope.org_id),
            "run_id": str(run_id),
            "person_id": str(scope.person_id),
            "is_staff": scope.role != "resident",
        },
    )
    if found.mappings().one_or_none() is None:
        raise HTTPException(404)
    database_url = os.environ.get("WORKER_DATABASE_URL", "").strip()
    if not database_url:
        raise HTTPException(503, "Run processing is not configured")
    try:
        engine = create_database_engine(database_url)
    except (ValueError, SQLAlchemyError) as error:
        raise HTTPException(503, "Run processing is not configured") from error
    try:
        factory = create_session_factory(engine)
        processed = await process_one(
            factory, scope.org_id, execute_maintenance, run_id=run_id
        )
        return ProcessingResult(run_id=run_id, processed=processed)
    except Exception as error:
        raise HTTPException(503, "Run processing is temporarily unavailable") from error
    finally:
        await engine.dispose()


class RecoveryResult(BaseModel):
    processed: bool


@recovery_router.get("/recover", response_model=RecoveryResult)
async def recover_run(request: Request) -> RecoveryResult:
    """Recover at most one job in the explicitly configured organization."""
    secret = os.environ.get("CRON_SECRET", "")
    authorization = request.headers.getlist("Authorization")
    if (
        not secret
        or len(authorization) != 1
        or not hmac.compare_digest(
            authorization[0].encode("utf-8"), f"Bearer {secret}".encode("utf-8")
        )
    ):
        raise HTTPException(401, "Invalid recovery authorization")
    database_url = os.environ.get("WORKER_DATABASE_URL", "").strip()
    configured_org = os.environ.get("WORKER_ORG_ID", "").strip()
    if not database_url or not configured_org:
        raise HTTPException(503, "Run recovery is not configured")
    try:
        org_id = UUID(configured_org)
        engine = create_database_engine(database_url)
    except (ValueError, SQLAlchemyError) as error:
        raise HTTPException(503, "Run recovery is not configured") from error
    try:
        processed = await process_one(
            create_session_factory(engine), org_id, execute_maintenance
        )
        return RecoveryResult(processed=processed)
    except Exception as error:
        raise HTTPException(503, "Run recovery is temporarily unavailable") from error
    finally:
        await engine.dispose()
