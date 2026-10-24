
"""
Step 3.52 — Two-organization PostgreSQL RLS isolation test.

Tests two populated organizations using the restricted
resident_api database role.

Read-only: does not modify application records.
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


ORG_A = "22d72ee6-0bd3-43f6-b3e9-bef9ff26e0f6"
PERSON_A = "509f7c65-e3ae-49d4-84b0-c6c2ac4e2044"
UNIT_A = "A-101"

ORG_B = "ab027600-2e27-4983-b113-00f57d40d112"
PERSON_B = "df893c36-4d57-4068-bc46-778db114c67d"
UNIT_B = "B-201"


async def check_resident(
    session_factory,
    org_id,
    person_id,
    own_unit,
    other_org,
    label,
):
    context = TenantContext(
        org_id=UUID(org_id),
        person_id=UUID(person_id),
        role="resident",
    )

    async with tenant_session(session_factory, context) as session:
        result = await session.execute(
            text("""
                SELECT
                    (SELECT COUNT(*)
                     FROM public.tenancies
                     WHERE org_id = CAST(:own_org AS uuid)
                       AND person_id = CAST(:person AS uuid)
                       AND status = 'active')
                        AS own_tenancies,

                    (SELECT COUNT(*)
                     FROM public.units
                     WHERE org_id = CAST(:own_org AS uuid)
                       AND unit_number = :own_unit)
                        AS own_units,

                    (SELECT COUNT(*)
                     FROM public.tenancies
                     WHERE org_id = CAST(:other_org AS uuid))
                        AS other_tenancies,

                    (SELECT COUNT(*)
                     FROM public.units
                     WHERE org_id = CAST(:other_org AS uuid))
                        AS other_units
            """),
            {
                "own_org": org_id,
                "person": person_id,
                "own_unit": own_unit,
                "other_org": other_org,
            },
        )

        row = result.mappings().one()

    print(f"\n=== {label} ===")
    print("Own active tenancies:", row["own_tenancies"])
    print("Own visible units:", row["own_units"])
    print("Other organization tenancies:", row["other_tenancies"])
    print("Other organization units:", row["other_units"])

    passed = (
        row["own_tenancies"] == 1
        and row["own_units"] == 1
        and row["other_tenancies"] == 0
        and row["other_units"] == 0
    )

    print("ISOLATION:", "PASS" if passed else "FAIL")

    return passed


async def main():
    env = dotenv_values(".env")
    database_url = env.get("DATABASE_URL")

    if not database_url:
        print("DATABASE_URL: MISSING")
        return

    engine = create_database_engine(database_url)
    session_factory = create_session_factory(engine)

    try:
        result_a = await check_resident(
            session_factory,
            ORG_A,
            PERSON_A,
            UNIT_A,
            ORG_B,
            "Organization A Resident",
        )

        result_b = await check_resident(
            session_factory,
            ORG_B,
            PERSON_B,
            UNIT_B,
            ORG_A,
            "Organization B Resident",
        )

        print("\n=== Final Result ===")
        print(
            "TWO-ORGANIZATION ISOLATION:",
            "PASS" if result_a and result_b else "FAIL",
        )

    except Exception as error:
        print("ISOLATION TEST: ERROR")
        print("Error type:", type(error).__name__)
        print("Error message:", str(error).splitlines()[0])

    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
