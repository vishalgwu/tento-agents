"""
Tento Resident OS — PostgreSQL Row-Level Security Tests

Tests:
3.26 - Database role and tenant context
3.27 - Resident tenancy visibility
3.29 - Cross-person tenancy isolation
3.31 - Unit-level RLS isolation
3.32 - Cross-organization RLS isolation
3.33 - Transaction-local context cleanup
3.34 - Resident and staff role separation

Uses restricted resident_api database credentials.

All database operations are read-only, except setting
transaction-local PostgreSQL configuration variables.
"""

import asyncio
from uuid import UUID

from dotenv import dotenv_values
from sqlalchemy import text

from api.db import (
    TenantContext,
    create_database_engine,
    create_session_factory,
    tenant_session,
)


# --------------------------------------------------
# Configuration
# --------------------------------------------------

env = dotenv_values(".env")

EXPECTED_ORG = "22d72ee6-0bd3-43f6-b3e9-bef9ff26e0f6"

EXPECTED_PERSON = "509f7c65-e3ae-49d4-84b0-c6c2ac4e2044"

OTHER_PERSON = "c71bab75-9098-4ead-9dd2-f02c17b89697"

OTHER_ORG = "11111111-1111-4111-8111-111111111111"

EXPECTED_ROLE = "resident"


# --------------------------------------------------
# Helpers
# --------------------------------------------------

def show_result(name, passed):
    print(f"{name}: {'PASS' if passed else 'FAIL'}")
    return passed


def resident_context(org_id, person_id):
    return TenantContext(
        org_id=UUID(org_id),
        person_id=UUID(person_id),
        role="resident",
    )


# --------------------------------------------------
# Step 3.26 — Database role and RLS context
# --------------------------------------------------

async def test_database_context(session_factory):

    print("\n=== Database Role and Tenant Context ===")

    context = resident_context(EXPECTED_ORG, EXPECTED_PERSON)

    async with tenant_session(session_factory, context) as session:

        result = await session.execute(
            text("""
                SELECT
                    current_user AS db_role,
                    current_setting(
                        'app.current_org_id', true
                    ) AS org_id,
                    current_setting(
                        'app.current_person_id', true
                    ) AS person_id,
                    current_setting(
                        'app.current_role', true
                    ) AS app_role
            """)
        )

        row = result.mappings().one()

    checks = [
        show_result(
            "DATABASE ROLE",
            row["db_role"] == "resident_api"
        ),
        show_result(
            "ORGANIZATION CONTEXT",
            row["org_id"] == EXPECTED_ORG
        ),
        show_result(
            "PERSON CONTEXT",
            row["person_id"] == EXPECTED_PERSON
        ),
        show_result(
            "APPLICATION ROLE",
            row["app_role"] == EXPECTED_ROLE
        ),
    ]

    return show_result(
        "RLS CONTEXT TEST",
        all(checks)
    )


# --------------------------------------------------
# Step 3.27 — Resident tenancy visibility
# --------------------------------------------------

async def test_resident_tenancy(session_factory):

    print("\n=== Resident Tenancy Visibility ===")

    context = resident_context(EXPECTED_ORG, EXPECTED_PERSON)

    async with tenant_session(session_factory, context) as session:

        result = await session.execute(
            text("""
                SELECT
                    t.id AS tenancy_id,
                    u.unit_number,
                    t.person_id,
                    t.status::text AS status
                FROM public.tenancies AS t
                JOIN public.units AS u
                    ON u.id = t.unit_id
                   AND u.org_id = t.org_id
                WHERE t.status = 'active'
                ORDER BY u.unit_number
            """)
        )

        tenancies = result.mappings().all()

    print("Visible active tenancies:", len(tenancies))

    for tenancy in tenancies:
        print("Unit:", tenancy["unit_number"])
        print(
            "Resident matches:",
            str(tenancy["person_id"]) == EXPECTED_PERSON
        )

    passed = (
        len(tenancies) == 1
        and tenancies[0]["unit_number"] == "A-101"
        and str(tenancies[0]["person_id"]) == EXPECTED_PERSON
    )

    return show_result("UNIT A-101 VISIBILITY", passed)


# --------------------------------------------------
# Step 3.29 — Negative tenancy RLS test
# --------------------------------------------------

async def test_cross_person_tenancy(session_factory):

    print("\n=== Negative Tenancy RLS Test ===")

    context = resident_context(EXPECTED_ORG, OTHER_PERSON)

    async with tenant_session(session_factory, context) as session:

        result = await session.execute(
            text("""
                SELECT COUNT(*)
                FROM public.tenancies
                WHERE person_id = CAST(:person_id AS uuid)
            """),
            {"person_id": EXPECTED_PERSON},
        )

        visible_count = result.scalar_one()

    print(
        "Other identity can see Demo Resident tenancy:",
        visible_count
    )

    return show_result(
        "CROSS-PERSON ISOLATION",
        visible_count == 0
    )


# --------------------------------------------------
# Step 3.31 — Unit-level RLS isolation
# --------------------------------------------------

async def test_unit_isolation(session_factory):

    print("\n=== Unit RLS Isolation Test ===")

    # Positive: resident can view their own unit.
    context = resident_context(EXPECTED_ORG, EXPECTED_PERSON)

    async with tenant_session(session_factory, context) as session:

        result = await session.execute(
            text("""
                SELECT COUNT(*)
                FROM public.units
                WHERE unit_number = 'A-101'
                  AND org_id = CAST(:org_id AS uuid)
            """),
            {"org_id": EXPECTED_ORG},
        )

        resident_count = result.scalar_one()

    # Negative: an unmatched identity cannot view the unit.
    other_context = resident_context(EXPECTED_ORG, OTHER_PERSON)

    async with tenant_session(
        session_factory, other_context
    ) as session:

        result = await session.execute(
            text("""
                SELECT COUNT(*)
                FROM public.units
                WHERE unit_number = 'A-101'
                  AND org_id = CAST(:org_id AS uuid)
            """),
            {"org_id": EXPECTED_ORG},
        )

        other_count = result.scalar_one()

    print("Demo Resident visible units:", resident_count)
    print("Other identity visible units:", other_count)

    return show_result(
        "UNIT RLS ISOLATION",
        resident_count == 1 and other_count == 0
    )


# --------------------------------------------------
# Step 3.32 — Cross-organization isolation
# --------------------------------------------------

async def test_cross_organization(session_factory):

    print("\n=== Cross-Organization RLS Isolation Test ===")

    other_context = resident_context(
        OTHER_ORG,
        EXPECTED_PERSON,
    )

    async with tenant_session(session_factory, other_context) as session:

        result = await session.execute(
            text("""
                SELECT
                    (
                        SELECT COUNT(*)
                        FROM public.tenancies
                        WHERE org_id = CAST(:org_id AS uuid)
                    ) AS visible_demo_tenancies,

                    (
                        SELECT COUNT(*)
                        FROM public.units
                        WHERE org_id = CAST(:org_id AS uuid)
                    ) AS visible_demo_units
            """),
            {"org_id": EXPECTED_ORG},
        )

        row = result.mappings().one()

    tenancy_count = row["visible_demo_tenancies"]
    unit_count = row["visible_demo_units"]

    print("Other org can see demo tenancies:", tenancy_count)
    print("Other org can see demo units:", unit_count)

    return show_result(
        "CROSS-ORG ISOLATION",
        tenancy_count == 0 and unit_count == 0
    )


# --------------------------------------------------
# Step 3.33 — Transaction context cleanup
# --------------------------------------------------

async def test_transaction_cleanup(session_factory):

    print("\n=== Transaction Context Cleanup Test ===")

    # Use a single SQLAlchemy session for both transactions.
    async with session_factory() as session:

        # Transaction 1: Set tenant context.
        async with session.begin():

            await session.execute(
                text("""
                    SELECT
                        set_config(
                            'app.current_org_id', :org_id, true
                        ),
                        set_config(
                            'app.current_person_id', :person_id, true
                        ),
                        set_config(
                            'app.current_role', :role, true
                        )
                """),
                {
                    "org_id": EXPECTED_ORG,
                    "person_id": EXPECTED_PERSON,
                    "role": EXPECTED_ROLE,
                },
            )

            before = (
                await session.execute(
                    text("""
                        SELECT
                            current_setting(
                                'app.current_org_id', true
                            ),
                            current_setting(
                                'app.current_person_id', true
                            ),
                            current_setting(
                                'app.current_role', true
                            )
                    """)
                )
            ).one()

        # Transaction 1 has committed.
        # Transaction 2 should have no tenant context.
        async with session.begin():

            after = (
                await session.execute(
                    text("""
                        SELECT
                            current_setting(
                                'app.current_org_id', true
                            ),
                            current_setting(
                                'app.current_person_id', true
                            ),
                            current_setting(
                                'app.current_role', true
                            )
                    """)
                )
            ).one()

    before_passed = tuple(before) == (
        EXPECTED_ORG,
        EXPECTED_PERSON,
        EXPECTED_ROLE,
    )

    after_passed = all(
        value is None or value == ""
        for value in after
    )

    show_result(
        "Context inside transaction",
        before_passed
    )

    show_result(
        "Context cleared after commit",
        after_passed
    )

    return show_result(
        "TRANSACTION CONTEXT CLEANUP",
        before_passed and after_passed
    )


# --------------------------------------------------
# Step 3.34 — Resident and staff role separation
# --------------------------------------------------

async def test_resident_staff_separation(session_factory):
    print("\n=== Resident and Staff Role Separation ===")

    context = resident_context(EXPECTED_ORG, EXPECTED_PERSON)

    async with tenant_session(session_factory, context) as session:
        result = await session.execute(
            text("""
                SELECT
                    public.app_is_resident() AS is_resident,
                    public.app_is_tenant_staff() AS is_tenant_staff
            """)
        )

        row = result.mappings().one()

    print("Is resident:", row["is_resident"])
    print("Is tenant staff:", row["is_tenant_staff"])

    return show_result(
        "RESIDENT STAFF SEPARATION",
        row["is_resident"] is True
        and row["is_tenant_staff"] is False,
    )


# --------------------------------------------------
# Main test runner
# --------------------------------------------------

async def main():

    print("\n=== Tento Resident OS — RLS Security Tests ===")

    database_url = env.get("DATABASE_URL")

    if not database_url:
        print("DATABASE_URL: MISSING")
        return

    engine = create_database_engine(database_url)
    session_factory = create_session_factory(engine)

    try:
        results = []

        results.append(
            await test_database_context(session_factory)
        )

        results.append(
            await test_resident_tenancy(session_factory)
        )

        results.append(
            await test_cross_person_tenancy(session_factory)
        )

        results.append(
            await test_unit_isolation(session_factory)
        )

        results.append(
            await test_cross_organization(session_factory)
        )

        results.append(
            await test_transaction_cleanup(session_factory)
        )

        results.append(
            await test_resident_staff_separation(session_factory)
        )

        print("\n=== Final RLS Test Summary ===")

        print("Tests passed:", sum(results))
        print("Total tests:", len(results))

        show_result(
            "OVERALL RLS TEST",
            all(results)
        )

    except Exception as error:
        print("\nRLS TEST: ERROR")
        print("Error type:", type(error).__name__)
        print("Error message:", str(error).splitlines()[0])

    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())