"""Opt-in real PostgreSQL checks; use a migrated dedicated *_test database.

TEST_DATABASE_URL must use postgresql+asyncpg and a migration-owner account able
to create a temporary NOLOGIN role. All fixtures, grants and roles roll back.
"""

from __future__ import annotations

import json
import os
from collections.abc import AsyncIterator
from typing import Any
from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncSession

from api.db import TenantContext, create_database_engine, set_rls_context
from api.deps.tenancy import TenantScope
from api.middleware.idempotency import (
    CachedResponse,
    ConflictingIdempotencyRecord,
    IdempotencyRequest,
    NewIdempotencyRecord,
    PostgresIdempotencyStore,
    ReplayedIdempotencyRecord,
)
from api.routers.tickets import (
    SubmitTicketRequest,
    get_ticket,
    list_tickets,
    submit_ticket,
)
from api.worker import LeaseLost, claim_job, execute_job

_URL = os.environ.get("TEST_DATABASE_URL", "")
pytestmark = pytest.mark.skipif(not _URL, reason="TEST_DATABASE_URL is not configured")


@pytest_asyncio.fixture
async def database() -> AsyncIterator[tuple[AsyncSession, TenantScope]]:
    parsed = make_url(_URL)
    if parsed.drivername != "postgresql+asyncpg" or not (
        parsed.database or ""
    ).endswith("_test"):
        pytest.fail(
            "TEST_DATABASE_URL must identify a dedicated *_test PostgreSQL database"
        )
    engine = create_database_engine(_URL)
    org, prop, building, unit, person, tenancy = (uuid4() for _ in range(6))
    scope = TenantScope(
        org_id=org, person_id=person, subject_id=person, role="resident"
    )
    params = {
        "org": org,
        "prop": prop,
        "building": building,
        "unit": unit,
        "person": person,
        "tenancy": tenancy,
        "slug": f"test-{org}",
    }
    try:
        async with engine.connect() as connection:
            transaction = await connection.begin()
            session = AsyncSession(bind=connection, expire_on_commit=False)
            try:
                seed = [
                    "INSERT INTO public.orgs(id,slug,name) VALUES(:org,:slug,'Integration test')",
                    "INSERT INTO public.properties(id,org_id,name,timezone,address_line_1,locality,region_code,postal_code) VALUES(:prop,:org,'Test property','UTC','Test address','Test locality','VA','00000')",
                    "INSERT INTO public.buildings(id,org_id,property_id,name) VALUES(:building,:org,:prop,'Test building')",
                    "INSERT INTO public.units(id,org_id,property_id,building_id,unit_number) VALUES(:unit,:org,:prop,:building,'Test unit')",
                    "INSERT INTO public.people(id,org_id,display_name) VALUES(:person,:org,'Test resident')",
                    "INSERT INTO public.tenancies(id,org_id,property_id,unit_id,person_id,starts_on) VALUES(:tenancy,:org,:prop,:unit,:person,CURRENT_DATE - 1)",
                ]
                for statement in seed:
                    await session.execute(text(statement), params)
                # Generated hexadecimal identity is the only interpolated SQL identifier.
                role = f"mvp_test_{uuid4().hex}"
                await session.execute(
                    text(f"CREATE ROLE {role} NOLOGIN NOSUPERUSER NOBYPASSRLS")
                )
                await session.execute(text(f"GRANT USAGE ON SCHEMA public TO {role}"))
                await session.execute(
                    text(
                        f"GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO {role}"
                    )
                )
                await session.execute(
                    text(
                        f"GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO {role}"
                    )
                )
                await session.execute(text(f"SET LOCAL ROLE {role}"))
                await set_rls_context(session, scope.rls_context)
                yield session, scope
            finally:
                await session.close()
                if transaction.is_active:
                    await transaction.rollback()
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_real_resident_submission_result_reads_and_idempotency(
    database: tuple[AsyncSession, TenantScope],
) -> None:
    session, scope = database
    store = PostgresIdempotencyStore()
    request = IdempotencyRequest(
        org_id=scope.org_id,
        person_id=scope.person_id,
        method="POST",
        path="/v1/tickets",
        key_hash="a" * 64,
        request_digest="b" * 64,
    )
    reserved = await store.begin(session, request)
    assert isinstance(reserved, NewIdempotencyRecord)
    receipt = await submit_ticket(
        SubmitTicketRequest(description="Kitchen tap drips"), scope, session
    )
    response = CachedResponse(
        status_code=201,
        body=receipt.model_dump_json().encode(),
        headers={},
        media_type="application/json",
    )
    await store.complete(session, request, reserved.record_id, response)
    replay = await store.begin(session, request)
    assert isinstance(replay, ReplayedIdempotencyRecord)
    assert json.loads(replay.response.body)["ticket_id"] == str(receipt.ticket_id)
    changed = IdempotencyRequest(
        org_id=scope.org_id,
        person_id=scope.person_id,
        method="POST",
        path="/v1/tickets",
        key_hash="a" * 64,
        request_digest="c" * 64,
    )
    assert isinstance(await store.begin(session, changed), ConflictingIdempotencyRecord)
    page = await list_tickets(scope, session)
    assert [ticket.id for ticket in page.items] == [receipt.ticket_id]
    detail = await get_ticket(receipt.ticket_id, scope, session)
    assert detail.latest_run is not None and detail.latest_run.run_id == receipt.run_id
    assert detail.latest_run.status == "queued"
    # Even a second current resident of the same unit cannot read the report's
    # normalized result through the explicit reporter boundary.
    other = uuid4()
    await set_rls_context(
        session, TenantContext(org_id=scope.org_id, role="operations_admin")
    )
    await session.execute(
        text(
            "INSERT INTO public.people(id,org_id,display_name) VALUES(:other,:org,'Other test resident')"
        ),
        {"other": other, "org": scope.org_id},
    )
    await session.execute(
        text(
            "INSERT INTO public.tenancies(org_id,property_id,unit_id,person_id,starts_on) VALUES(:org,:property,:unit,:other,CURRENT_DATE-1)"
        ),
        {
            "org": scope.org_id,
            "property": detail.property_id,
            "unit": detail.unit_id,
            "other": other,
        },
    )
    other_scope = TenantScope(
        org_id=scope.org_id, person_id=other, subject_id=other, role="resident"
    )
    await set_rls_context(session, other_scope.rls_context)
    assert (await list_tickets(other_scope, session)).items == []
    from fastapi import HTTPException

    with pytest.raises(HTTPException) as hidden:
        await get_ticket(receipt.ticket_id, other_scope, session)
    assert hidden.value.status_code == 404


@pytest.mark.asyncio
async def test_real_expired_lease_recovery_fencing_and_final_result(
    database: tuple[AsyncSession, TenantScope],
) -> None:
    session, scope = database
    receipt = await submit_ticket(
        SubmitTicketRequest(description="Kitchen tap drips"), scope, session
    )
    await set_rls_context(
        session, TenantContext(org_id=scope.org_id, role="operations_admin")
    )
    first = await claim_job(session, scope.org_id)
    assert first is not None and first.run_id == receipt.run_id
    await session.execute(
        text(
            "UPDATE public.agent_runs SET lease_expires_at=now()-interval '1 second' WHERE org_id=:org AND id=:run"
        ),
        {"org": scope.org_id, "run": first.run_id},
    )
    second = await claim_job(session, scope.org_id)
    assert (
        second is not None
        and second.run_id == first.run_id
        and second.lease_id != first.lease_id
    )

    async def workflow(**kwargs: object) -> dict[str, Any]:
        return {
            "status": "abstained",
            "summary": "No configured policy evidence",
            "facts": {"category": "plumbing", "symptom_summary": "Kitchen tap drips"},
        }

    with pytest.raises(LeaseLost):
        await execute_job(session, scope.org_id, first, workflow)
    await execute_job(session, scope.org_id, second, workflow)
    assert await claim_job(session, scope.org_id) is None
    await set_rls_context(session, scope.rls_context)
    detail = await get_ticket(receipt.ticket_id, scope, session)
    assert detail.status == "blocked"
    assert detail.category == "plumbing"
    assert detail.latest_run is not None and detail.latest_run.status == "degraded"
    assert detail.latest_run.result is not None
    assert detail.latest_run.result["summary"] == "No configured policy evidence"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "description,expected",
    [
        ("I smell gas in my apartment.", "emergency"),
        ("Kitchen sink drips.", "abstained"),
    ],
)
async def test_real_worker_runs_graph_and_persists_safe_terminal_result(
    database: tuple[AsyncSession, TenantScope],
    monkeypatch: pytest.MonkeyPatch,
    description: str,
    expected: str,
) -> None:
    from brain.production import execute_maintenance

    session, scope = database
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    receipt = await submit_ticket(
        SubmitTicketRequest(description=description), scope, session
    )
    await set_rls_context(
        session, TenantContext(org_id=scope.org_id, role="operations_admin")
    )
    job = await claim_job(session, scope.org_id)
    assert job is not None
    await execute_job(session, scope.org_id, job, execute_maintenance)
    await set_rls_context(session, scope.rls_context)
    detail = await get_ticket(receipt.ticket_id, scope, session)
    assert detail.latest_run is not None and detail.latest_run.result is not None
    assert detail.latest_run.result["status"] == expected
    from api.routers.stream import stream_run

    stream = await stream_run(job.run_id, scope, session)
    events = b"".join(
        [
            item.encode() if isinstance(item, str) else item
            async for item in stream.body_iterator
        ]
    )
    assert b'"stage":"unknown"' not in events
    assert b"timeline.ready" in events


@pytest.mark.asyncio
async def test_real_complete_graph_creates_internal_order_and_audited_receipts(
    database: tuple[AsyncSession, TenantScope], monkeypatch: pytest.MonkeyPatch
) -> None:
    from brain import production
    from brain.gateway.client import (
        GatewayClient,
        ModelRoute,
        RenderedPrompt,
        ProviderCompletion,
    )
    import hashlib

    session, scope = database
    receipt = await submit_ticket(
        SubmitTicketRequest(description="Kitchen sink drains slowly."), scope, session
    )
    await set_rls_context(
        session, TenantContext(org_id=scope.org_id, role="operations_admin")
    )
    await session.execute(
        text(
            "UPDATE public.properties SET in_house_trades=ARRAY['plumbing']::trade[] WHERE org_id=:org"
        ),
        {"org": scope.org_id},
    )
    document_id, chunk_id = uuid4(), uuid4()
    passage = "Owner repairs plumbing defects reported by the resident, including sink drains."
    params = {
        "org": scope.org_id,
        "document": document_id,
        "chunk": chunk_id,
        "passage": passage,
        "end": len(passage),
        "digest": hashlib.sha256(passage.encode()).hexdigest(),
    }
    await session.execute(
        text("""INSERT INTO public.kb_documents(id,org_id,document_key,version,title,authority,jurisdiction_code,source_uri,content_sha256,status,effective_from)
        VALUES(:document,:org,'TEST-SOP','1','Isolated test source','internal_sop','US-VA','test://isolated-source',:digest,'active',now()-interval '1 day')"""),
        params,
    )
    await session.execute(
        text("""INSERT INTO public.kb_chunks(id,org_id,kb_document_id,chunk_index,heading_path,source_start,source_end,content,content_sha256,token_count)
        VALUES(:chunk,:org,:document,0,'Repairs',0,:end,:passage,:digest,15)"""),
        params,
    )
    await session.execute(
        text("""INSERT INTO public.kb_policy_claims(org_id,kb_document_id,policy_key,outcome,source_start,source_end)
        VALUES(:org,:document,'repair','owner_responsible',0,:end)"""),
        params,
    )

    class ScriptedProvider:
        name = "anthropic"

        async def invoke(
            self, *, route: ModelRoute, prompt: RenderedPrompt
        ) -> ProviderCompletion:
            payloads = {
                "intake-normalize": {
                    "intent": "maintenance",
                    "category": "plumbing",
                    "symptom_summary": "The kitchen sink drains slowly.",
                },
                "diagnostician": {
                    "likely_cause": "The drain may be obstructed.",
                    "cause_provenance_ids": ["[C1]"],
                    "recommended_actions": [
                        {
                            "action": "Inspect the drain.",
                            "rationale": "The cited source supports maintenance.",
                            "provenance_ids": ["[C1]"],
                        }
                    ],
                },
                "dispatch-planning": {
                    "trade": "plumbing",
                    "fulfillment": "in_house",
                    "scope_summary": "Inspect the sink drain.",
                    "responsible_party": "owner",
                    "provenance_ids": ["[C1]"],
                },
                "policy-audit": {
                    "findings": [
                        {
                            "policy_key": "repair",
                            "verdict": "compliant",
                            "rationale": "The policy permits the proposed scope.",
                            "provenance_ids": ["[C1]"],
                        }
                    ]
                },
            }
            return ProviderCompletion(
                output_text=json.dumps(payloads[prompt.template.name]),
                input_tokens=10,
                output_tokens=10,
            )

    def gateway(**kwargs: Any) -> GatewayClient:
        kwargs["providers"] = {"anthropic": ScriptedProvider()}
        return GatewayClient(**kwargs)

    monkeypatch.setattr(production, "GatewayClient", gateway)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "isolated-test-provider")
    monkeypatch.setenv("ANTHROPIC_MODEL", "isolated-test-model")
    job = await claim_job(session, scope.org_id)
    assert job is not None
    await execute_job(session, scope.org_id, job, production.execute_maintenance)
    assert (
        await session.execute(
            text("SELECT count(*) FROM public.llm_calls WHERE org_id=:org"),
            {"org": scope.org_id},
        )
    ).scalar_one() == 4
    assert (
        await session.execute(
            text("SELECT count(*) FROM public.work_orders WHERE org_id=:org"),
            {"org": scope.org_id},
        )
    ).scalar_one() == 1
    await set_rls_context(session, scope.rls_context)
    detail = await get_ticket(receipt.ticket_id, scope, session)
    assert detail.status == "ready"
    assert detail.latest_run and detail.latest_run.result
    assert detail.latest_run.result["status"] == "completed"
    assert detail.latest_run.result["work_order"]["status"] == "proposed"
