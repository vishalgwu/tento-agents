"""Create the deterministic Resident OS synthetic development dataset.

The generator owns one clearly marked demo organisation.  It uses fixed UUIDs,
a fixed pseudo-random seed, and a fixed historical reference date so every
fresh database receives the same records.  Re-running it upserts those records
rather than creating another synthetic tenant.

Run the Phase 0 migrations first, then run one of:

    .\\tento\\Scripts\\python.exe infra\\seed\\generate.py --dry-run
    .\\tento\\Scripts\\python.exe infra\\seed\\generate.py

The script reads DATABASE_URL from the environment.  It also accepts the
SQLAlchemy ``postgresql+asyncpg`` URL used by .env.example and converts it to
the native PostgreSQL URL required by asyncpg.

This is synthetic development data only.  It does not read production systems,
call external services, or create media objects.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import random
import sys
import uuid
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Final

import asyncpg  # type: ignore[import-untyped]


SEED_VERSION: Final = 1
RANDOM_SEED: Final = 20_260_910
SEED_NAMESPACE: Final = uuid.UUID("20b95d49-75b6-426d-91be-c1fec78b6e6a")
DEMO_ORG_ID: Final = uuid.uuid5(SEED_NAMESPACE, "resident-os-demo-organisation")
SEED_ADMIN_ID: Final = uuid.uuid5(SEED_NAMESPACE, "seed-operations-administrator")
SEED_REFERENCE_AT: Final = datetime(2026, 3, 1, 12, 0, tzinfo=UTC)
HISTORY_START: Final = datetime(2024, 12, 1, 8, 0, tzinfo=UTC)
HISTORY_END: Final = datetime(2026, 2, 10, 17, 0, tzinfo=UTC)

EXPECTED_COUNTS: Final = {
    "orgs": 1,
    "properties": 2,
    "units": 400,
    "tenancies": 320,
    "assets": 40,
    "vendors": 8,
    "tickets": 1_200,
}

TRADE_SCENARIOS: Final = (
    ("plumbing", "Bathroom faucet has a steady drip", ("p2", "p3"), 28),
    ("plumbing", "Kitchen sink drains slowly", ("p2", "p3"), 24),
    ("hvac", "Heating is not reaching the set temperature", ("p1", "p2"), 16),
    ("hvac", "Air conditioner is blowing warm air", ("p1", "p2"), 16),
    ("appliance", "Dishwasher leaves water at the bottom", ("p2", "p3"), 12),
    ("appliance", "Refrigerator is not cooling consistently", ("p1", "p2"), 12),
    ("electrical", "Kitchen outlet stopped working", ("p1", "p2"), 9),
    ("general_maintenance", "Bedroom door does not close properly", ("p3",), 8),
    ("pest_control", "Resident reports ants near the kitchen cabinet", ("p2", "p3"), 8),
    ("restoration", "Water stain appeared on the ceiling", ("p1", "p2"), 6),
)


@dataclass(frozen=True)
class SeedData:
    """Rows ready for asyncpg's positional ``executemany`` interface."""

    orgs: Sequence[tuple[object, ...]]
    properties: Sequence[tuple[object, ...]]
    buildings: Sequence[tuple[object, ...]]
    units: Sequence[tuple[object, ...]]
    people: Sequence[tuple[object, ...]]
    roles: Sequence[tuple[object, ...]]
    tenancies: Sequence[tuple[object, ...]]
    assets: Sequence[tuple[object, ...]]
    vendors: Sequence[tuple[object, ...]]
    vendor_scores: Sequence[tuple[object, ...]]
    tickets: Sequence[tuple[object, ...]]


def stable_id(kind: str, key: str | int) -> uuid.UUID:
    """Return a reproducible UUID without depending on insertion order."""

    return uuid.uuid5(SEED_NAMESPACE, f"v{SEED_VERSION}:{kind}:{key}")


def seed_timestamp(day: date, hour: int = 9, minute: int = 0) -> datetime:
    return datetime(day.year, day.month, day.day, hour, minute, tzinfo=UTC)


def build_units(
    properties: Sequence[tuple[object, ...]],
    buildings: Sequence[tuple[object, ...]],
) -> tuple[list[tuple[object, ...]], dict[uuid.UUID, list[uuid.UUID]], dict[str, uuid.UUID]]:
    """Build 200 uniquely named units per property.

    Virginia uses 1A through 20J so the documented 4B and 2C fixtures are
    unique and easy to find.  Maryland uses 21A through 40J to keep its unit
    labels distinct in cross-property demonstrations.
    """

    units: list[tuple[object, ...]] = []
    property_units: dict[uuid.UUID, list[uuid.UUID]] = {}
    unit_ids_by_label: dict[str, uuid.UUID] = {}

    for property_index, property_row in enumerate(properties):
        property_id = property_row[0]
        assert isinstance(property_id, uuid.UUID)
        building_id = buildings[property_index][0]
        assert isinstance(building_id, uuid.UUID)
        property_units[property_id] = []

        first_floor = 1 if property_index == 0 else 21
        region_prefix = "VA" if property_index == 0 else "MD"
        for offset, unit_number in enumerate(
            f"{floor}{letter}"
            for floor in range(first_floor, first_floor + 20)
            for letter in "ABCDEFGHIJ"
        ):
            unit_id = stable_id("unit", f"{region_prefix}-{unit_number}")
            units.append(
                (
                    unit_id,
                    DEMO_ORG_ID,
                    property_id,
                    building_id,
                    f"{region_prefix}-UNIT-{offset + 1:03d}",
                    unit_number,
                    str(int(unit_number[:-1])),
                    seed_timestamp(date(2020, 1, 1)),
                )
            )
            property_units[property_id].append(unit_id)
            if property_index == 0:
                unit_ids_by_label[unit_number] = unit_id

    return units, property_units, unit_ids_by_label


def choose_occupied_units(
    randomizer: random.Random,
    property_units: dict[uuid.UUID, list[uuid.UUID]],
    required_unit_ids: Iterable[uuid.UUID],
) -> list[uuid.UUID]:
    """Choose 160 occupied units at each property while preserving fixtures."""

    required = set(required_unit_ids)
    occupied: list[uuid.UUID] = []
    for unit_ids in property_units.values():
        required_for_property = [unit_id for unit_id in unit_ids if unit_id in required]
        candidates = [unit_id for unit_id in unit_ids if unit_id not in required]
        randomizer.shuffle(candidates)
        occupied.extend(required_for_property + candidates[: 160 - len(required_for_property)])
    return occupied


def build_people_and_tenancies(
    randomizer: random.Random,
    property_units: dict[uuid.UUID, list[uuid.UUID]],
    occupied_unit_ids: Sequence[uuid.UUID],
    unit_property_ids: dict[uuid.UUID, uuid.UUID],
) -> tuple[
    list[tuple[object, ...]],
    list[tuple[object, ...]],
    list[tuple[object, ...]],
    dict[uuid.UUID, uuid.UUID],
]:
    """Create 320 current resident tenancies and three synthetic staff users."""

    people: list[tuple[object, ...]] = []
    roles: list[tuple[object, ...]] = []
    tenancies: list[tuple[object, ...]] = []
    reporter_by_unit: dict[uuid.UUID, uuid.UUID] = {}

    ordered_units = list(occupied_unit_ids)
    randomizer.shuffle(ordered_units)
    for index, unit_id in enumerate(ordered_units, start=1):
        person_id = stable_id("resident", index)
        property_id = unit_property_ids[unit_id]
        people.append(
            (
                person_id,
                DEMO_ORG_ID,
                stable_id("auth-subject", index),
                f"RESIDENT-{index:03d}",
                f"Synthetic Resident {index:03d}",
                seed_timestamp(date(2023, 1, 1)),
            )
        )
        roles.append(
            (
                stable_id("resident-role", index),
                DEMO_ORG_ID,
                person_id,
                "resident",
                "organisation",
                None,
                seed_timestamp(date(2023, 1, 1)),
            )
        )
        tenancy_start = date(2023, 1, 1) + timedelta(days=randomizer.randrange(0, 900))
        tenancies.append(
            (
                stable_id("tenancy", index),
                DEMO_ORG_ID,
                property_id,
                unit_id,
                person_id,
                "active",
                tenancy_start,
                True,
            )
        )
        reporter_by_unit[unit_id] = person_id

    staff_specs: tuple[tuple[uuid.UUID, str, str, str, str, uuid.UUID | None], ...] = (
        (SEED_ADMIN_ID, "seed-admin", "Synthetic Operations Administrator", "operations_admin", "organisation", None),
        (
            stable_id("staff", "va-manager"),
            "manager-va",
            "Synthetic Virginia Property Manager",
            "property_manager",
            "property",
            next(iter(property_units)),
        ),
        (
            stable_id("staff", "md-manager"),
            "manager-md",
            "Synthetic Maryland Property Manager",
            "property_manager",
            "property",
            list(property_units)[1],
        ),
    )
    for person_id, external_ref, display_name, role, scope, staff_property_id in staff_specs:
        people.append(
            (
                person_id,
                DEMO_ORG_ID,
                stable_id("auth-subject", external_ref),
                external_ref,
                display_name,
                seed_timestamp(date(2023, 1, 1)),
            )
        )
        roles.append(
            (
                stable_id("staff-role", external_ref),
                DEMO_ORG_ID,
                person_id,
                role,
                scope,
                staff_property_id,
                seed_timestamp(date(2023, 1, 1)),
            )
        )

    return people, roles, tenancies, reporter_by_unit


def build_assets(
    randomizer: random.Random,
    property_units: dict[uuid.UUID, list[uuid.UUID]],
    unit_property_ids: dict[uuid.UUID, uuid.UUID],
    unit_building_ids: dict[uuid.UUID, uuid.UUID],
    special_water_heater_unit_id: uuid.UUID,
) -> list[tuple[object, ...]]:
    """Create 40 assets, including the documented 2C water-heater fixture."""

    assets: list[tuple[object, ...]] = [
        (
            stable_id("asset", "va-2c-water-heater"),
            DEMO_ORG_ID,
            unit_property_ids[special_water_heater_unit_id],
            unit_building_ids[special_water_heater_unit_id],
            special_water_heater_unit_id,
            "VA-2C-WH-001",
            "water_heater",
            "Northstar",
            "NH-50",
            "SYNTH-VA2C-WH-001",
            date(2019, 3, 15),
            date(2027, 3, 31),
            "active",
            seed_timestamp(date(2019, 3, 15)),
        )
    ]

    asset_types = (
        ("water_heater", "Northstar", "WH-40"),
        ("dishwasher", "Harbor", "DW-210"),
        ("refrigerator", "Harbor", "RF-350"),
        ("hvac_air_handler", "Summit", "AH-900"),
        ("garbage_disposal", "Brightline", "GD-75"),
    )
    candidate_units: list[uuid.UUID] = []
    for unit_ids in property_units.values():
        candidates = [unit_id for unit_id in unit_ids if unit_id != special_water_heater_unit_id]
        randomizer.shuffle(candidates)
        candidate_units.extend(candidates[:20])
    randomizer.shuffle(candidate_units)

    for index, unit_id in enumerate(candidate_units[:39], start=2):
        asset_type, manufacturer, model_number = asset_types[(index - 2) % len(asset_types)]
        installed_year = randomizer.randint(2020, 2025)
        installed_on = date(installed_year, randomizer.randint(1, 12), min(randomizer.randint(1, 28), 28))
        warranty_expires_on = date(installed_year + randomizer.choice((3, 5, 7)), installed_on.month, installed_on.day)
        assets.append(
            (
                stable_id("asset", index),
                DEMO_ORG_ID,
                unit_property_ids[unit_id],
                unit_building_ids[unit_id],
                unit_id,
                f"ASSET-{index:03d}",
                asset_type,
                manufacturer,
                model_number,
                f"SYNTH-{index:05d}",
                installed_on,
                warranty_expires_on,
                "active",
                seed_timestamp(installed_on),
            )
        )
    return assets


def build_vendors(randomizer: random.Random) -> tuple[list[tuple[object, ...]], list[tuple[object, ...]]]:
    """Create the eight region-scoped vendors used by later dispatch fixtures."""

    vendor_specs = (
        ("brightflow-va", "Brightflow Plumbing VA", "plumbing", ["US-VA"]),
        ("brightflow-md", "Brightflow Plumbing MD", "plumbing", ["US-MD"]),
        ("summit-air-va", "Summit Air Virginia", "hvac", ["US-VA"]),
        ("summit-air-md", "Summit Air Maryland", "hvac", ["US-MD"]),
        ("circuit-care-va", "Circuit Care Virginia", "electrical", ["US-VA"]),
        ("circuit-care-md", "Circuit Care Maryland", "electrical", ["US-MD"]),
        ("home-appliance-va", "Home Appliance Virginia", "appliance", ["US-VA"]),
        ("home-appliance-md", "Home Appliance Maryland", "appliance", ["US-MD"]),
    )
    vendors: list[tuple[object, ...]] = []
    vendor_scores: list[tuple[object, ...]] = []
    for index, (slug, name, trade, regions) in enumerate(vendor_specs, start=1):
        vendor_id = stable_id("vendor", slug)
        vendors.append(
            (
                vendor_id,
                DEMO_ORG_ID,
                f"VENDOR-{index:02d}",
                name,
                trade,
                f"Synthetic Contact {index}",
                regions,
                date(2028, 12, 31),
                True,
                seed_timestamp(date(2023, 1, 1)),
            )
        )
        vendor_scores.append(
            (
                stable_id("vendor-score", slug),
                DEMO_ORG_ID,
                vendor_id,
                trade,
                SEED_REFERENCE_AT,
                round(randomizer.uniform(0.70, 0.96), 4),
                randomizer.randint(30, 240),
                round(randomizer.uniform(0.75, 0.98), 4),
                round(randomizer.uniform(0.70, 0.95), 4),
                round(randomizer.uniform(0.02, 0.20), 4),
                trade in {"plumbing", "hvac", "appliance"},
            )
        )
    return vendors, vendor_scores


def seasonal_submission_time(randomizer: random.Random, category: str) -> datetime:
    """Draw a timestamp with modest HVAC and pest-control seasonality."""

    while True:
        span_seconds = int((HISTORY_END - HISTORY_START).total_seconds())
        candidate = HISTORY_START + timedelta(seconds=randomizer.randrange(span_seconds))
        if category == "hvac":
            weight = 4 if candidate.month in {12, 1, 2, 6, 7, 8} else 1
        elif category == "pest_control":
            weight = 4 if candidate.month in {5, 6, 7, 8, 9} else 1
        elif category == "restoration":
            weight = 2 if candidate.month in {3, 4, 5, 8, 9, 10} else 1
        else:
            weight = 1
        if randomizer.randrange(4) < weight:
            return candidate.replace(microsecond=0)


def resolution_time(randomizer: random.Random, submitted_at: datetime, priority: str) -> datetime:
    hours_by_priority = {
        "p0": (2, 12),
        "p1": (8, 60),
        "p2": (18, 120),
        "p3": (48, 336),
    }
    lower, upper = hours_by_priority[priority]
    return submitted_at + timedelta(hours=randomizer.randint(lower, upper), minutes=randomizer.randint(0, 59))


def ticket_row(
    *,
    ticket_key: int,
    property_id: uuid.UUID,
    building_id: uuid.UUID,
    unit_id: uuid.UUID,
    reporter_id: uuid.UUID,
    category: str,
    symptom_summary: str,
    reported_text: str,
    priority: str,
    submitted_at: datetime,
    randomizer: random.Random,
) -> tuple[object, ...]:
    acknowledgement_delay_seconds = randomizer.randint(3, 50)
    acknowledged_at = submitted_at + timedelta(seconds=acknowledgement_delay_seconds)
    preferred_start = submitted_at.replace(hour=10, minute=0, second=0, microsecond=0) + timedelta(days=1)
    preferred_end = preferred_start + timedelta(hours=4)
    return (
        stable_id("ticket", ticket_key),
        DEMO_ORG_ID,
        property_id,
        building_id,
        unit_id,
        reporter_id,
        "closed",
        priority,
        category,
        symptom_summary,
        reported_text,
        randomizer.random() < 0.75,
        randomizer.random() < 0.35,
        preferred_start,
        preferred_end,
        acknowledged_at,
        submitted_at,
        resolution_time(randomizer, submitted_at, priority),
    )


def build_tickets(
    randomizer: random.Random,
    unit_property_ids: dict[uuid.UUID, uuid.UUID],
    unit_building_ids: dict[uuid.UUID, uuid.UUID],
    reporter_by_unit: dict[uuid.UUID, uuid.UUID],
    special_drain_unit_id: uuid.UUID,
) -> list[tuple[object, ...]]:
    """Create 1,200 closed historical tickets with deterministic special cases."""

    tickets: list[tuple[object, ...]] = []
    special_dates = (
        seed_timestamp(date(2024, 12, 15), 9, 20),
        seed_timestamp(date(2025, 7, 15), 10, 5),
        seed_timestamp(date(2026, 2, 15), 8, 45),
    )
    for ticket_key, submitted_at in enumerate(special_dates, start=1):
        tickets.append(
            ticket_row(
                ticket_key=ticket_key,
                property_id=unit_property_ids[special_drain_unit_id],
                building_id=unit_building_ids[special_drain_unit_id],
                unit_id=special_drain_unit_id,
                reporter_id=reporter_by_unit[special_drain_unit_id],
                category="plumbing",
                symptom_summary="Kitchen drain backs up",
                reported_text="Synthetic fixture: kitchen drain backs up after normal sink use.",
                priority="p2",
                submitted_at=submitted_at,
                randomizer=randomizer,
            )
        )

    occupied_unit_ids = list(reporter_by_unit)
    scenarios, weights = zip(*((scenario, scenario[3]) for scenario in TRADE_SCENARIOS), strict=True)
    for ticket_key in range(4, EXPECTED_COUNTS["tickets"] + 1):
        category, symptom_summary, priorities, _ = randomizer.choices(scenarios, weights=weights, k=1)[0]
        unit_id = randomizer.choice(occupied_unit_ids)
        priority_weights = [0.2, 0.8] if len(priorities) == 2 else [1.0]
        priority = randomizer.choices(priorities, weights=priority_weights, k=1)[0]
        submitted_at = seasonal_submission_time(randomizer, category)
        tickets.append(
            ticket_row(
                ticket_key=ticket_key,
                property_id=unit_property_ids[unit_id],
                building_id=unit_building_ids[unit_id],
                unit_id=unit_id,
                reporter_id=reporter_by_unit[unit_id],
                category=category,
                symptom_summary=symptom_summary,
                reported_text=f"Synthetic resident report: {symptom_summary.lower()}.",
                priority=priority,
                submitted_at=submitted_at,
                randomizer=randomizer,
            )
        )
    return tickets


def build_seed_data() -> SeedData:
    """Build the complete deterministic seed without touching the database."""

    randomizer = random.Random(RANDOM_SEED)
    properties = [
        (
            stable_id("property", "va"),
            DEMO_ORG_ID,
            "PROPERTY-VA-001",
            "Riverview Apartments",
            "America/New_York",
            "1000 Example Way",
            "Arlington",
            "US-VA",
            "22201",
            "US",
            seed_timestamp(date(2020, 1, 1)),
        ),
        (
            stable_id("property", "md"),
            DEMO_ORG_ID,
            "PROPERTY-MD-001",
            "Maple Court Apartments",
            "America/New_York",
            "2000 Example Avenue",
            "Silver Spring",
            "US-MD",
            "20910",
            "US",
            seed_timestamp(date(2020, 1, 1)),
        ),
    ]
    buildings = [
        (
            stable_id("building", "va-main"),
            DEMO_ORG_ID,
            properties[0][0],
            "BUILDING-VA-001",
            "Riverview Hall",
            "VA-1",
            seed_timestamp(date(2020, 1, 1)),
        ),
        (
            stable_id("building", "md-main"),
            DEMO_ORG_ID,
            properties[1][0],
            "BUILDING-MD-001",
            "Maple Court Hall",
            "MD-1",
            seed_timestamp(date(2020, 1, 1)),
        ),
    ]
    units, property_units, unit_ids_by_label = build_units(properties, buildings)
    unit_property_ids: dict[uuid.UUID, uuid.UUID] = {}
    unit_building_ids: dict[uuid.UUID, uuid.UUID] = {}
    for unit in units:
        unit_id, property_id, building_id = unit[0], unit[2], unit[3]
        assert isinstance(unit_id, uuid.UUID)
        assert isinstance(property_id, uuid.UUID)
        assert isinstance(building_id, uuid.UUID)
        unit_property_ids[unit_id] = property_id
        unit_building_ids[unit_id] = building_id

    special_drain_unit_id = unit_ids_by_label["4B"]
    special_water_heater_unit_id = unit_ids_by_label["2C"]
    occupied_unit_ids = choose_occupied_units(
        randomizer,
        property_units,
        (special_drain_unit_id, special_water_heater_unit_id),
    )
    people, roles, tenancies, reporter_by_unit = build_people_and_tenancies(
        randomizer,
        property_units,
        occupied_unit_ids,
        unit_property_ids,
    )
    assets = build_assets(
        randomizer,
        property_units,
        unit_property_ids,
        unit_building_ids,
        special_water_heater_unit_id,
    )
    vendors, vendor_scores = build_vendors(randomizer)
    tickets = build_tickets(
        randomizer,
        unit_property_ids,
        unit_building_ids,
        reporter_by_unit,
        special_drain_unit_id,
    )
    data = SeedData(
        orgs=[(DEMO_ORG_ID, "resident-os-demo", "Resident OS Synthetic Demo", "America/New_York", True)],
        properties=properties,
        buildings=buildings,
        units=units,
        people=people,
        roles=roles,
        tenancies=tenancies,
        assets=assets,
        vendors=vendors,
        vendor_scores=vendor_scores,
        tickets=tickets,
    )
    validate_seed_data(data, special_drain_unit_id, special_water_heater_unit_id)
    return data


def validate_seed_data(
    data: SeedData,
    special_drain_unit_id: uuid.UUID,
    special_water_heater_unit_id: uuid.UUID,
) -> None:
    """Fail early if a code change breaks a documented fixture invariant."""

    actual_counts = {
        "orgs": len(data.orgs),
        "properties": len(data.properties),
        "units": len(data.units),
        "tenancies": len(data.tenancies),
        "assets": len(data.assets),
        "vendors": len(data.vendors),
        "tickets": len(data.tickets),
    }
    if actual_counts != EXPECTED_COUNTS:
        raise AssertionError(f"Seed counts changed: expected {EXPECTED_COUNTS}, got {actual_counts}")

    drain_tickets = [
        ticket
        for ticket in data.tickets
        if ticket[4] == special_drain_unit_id
        and ticket[8] == "plumbing"
        and ticket[9] == "Kitchen drain backs up"
    ]
    if len(drain_tickets) != 3:
        raise AssertionError("Unit 4B must have exactly three kitchen-drain tickets")
    drain_dates: list[date] = []
    for ticket in drain_tickets:
        submitted_at = ticket[16]
        assert isinstance(submitted_at, datetime)
        drain_dates.append(submitted_at.date())
    if drain_dates != [date(2024, 12, 15), date(2025, 7, 15), date(2026, 2, 15)]:
        raise AssertionError("Unit 4B kitchen-drain dates changed")

    water_heaters = [
        asset
        for asset in data.assets
        if asset[4] == special_water_heater_unit_id
        and asset[6] == "water_heater"
        and asset[10] == date(2019, 3, 15)
        and asset[11] == date(2027, 3, 31)
    ]
    if len(water_heaters) != 1:
        raise AssertionError("Unit 2C water-heater warranty fixture changed")


def normalize_database_url(database_url: str) -> str:
    """Translate the app's SQLAlchemy URL into an asyncpg connection URL."""

    return database_url.replace("postgresql+asyncpg://", "postgresql://", 1)


async def upsert_rows(
    connection: asyncpg.Connection,
    query: str,
    rows: Sequence[Sequence[object]],
) -> None:
    if rows:
        await connection.executemany(query, rows)


async def seed_database(database_url: str, data: SeedData) -> None:
    """Upsert the data in one transaction and prove the database result."""

    connection = await asyncpg.connect(normalize_database_url(database_url))
    try:
        async with connection.transaction():
            await connection.execute("SELECT set_config('app.current_org_id', $1, true)", str(DEMO_ORG_ID))
            await connection.execute("SELECT set_config('app.current_person_id', $1, true)", str(SEED_ADMIN_ID))
            await connection.execute("SELECT set_config('app.current_role', 'operations_admin', true)")

            await upsert_rows(
                connection,
                """
                INSERT INTO orgs (id, slug, name, timezone, is_demo)
                VALUES ($1, $2, $3, $4, $5)
                ON CONFLICT (id) DO UPDATE SET
                    slug = EXCLUDED.slug,
                    name = EXCLUDED.name,
                    timezone = EXCLUDED.timezone,
                    is_demo = EXCLUDED.is_demo,
                    updated_at = now()
                """,
                data.orgs,
            )
            await upsert_rows(
                connection,
                """
                INSERT INTO properties (
                    id, org_id, external_ref, name, timezone, address_line_1,
                    locality, region_code, postal_code, country_code, valid_from
                ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11)
                ON CONFLICT (id) DO UPDATE SET
                    external_ref = EXCLUDED.external_ref, name = EXCLUDED.name,
                    timezone = EXCLUDED.timezone, address_line_1 = EXCLUDED.address_line_1,
                    locality = EXCLUDED.locality, region_code = EXCLUDED.region_code,
                    postal_code = EXCLUDED.postal_code, country_code = EXCLUDED.country_code,
                    valid_from = EXCLUDED.valid_from, updated_at = now()
                """,
                data.properties,
            )
            await upsert_rows(
                connection,
                """
                INSERT INTO buildings (id, org_id, property_id, external_ref, name, code, valid_from)
                VALUES ($1, $2, $3, $4, $5, $6, $7)
                ON CONFLICT (id) DO UPDATE SET
                    external_ref = EXCLUDED.external_ref, name = EXCLUDED.name, code = EXCLUDED.code,
                    valid_from = EXCLUDED.valid_from, updated_at = now()
                """,
                data.buildings,
            )
            await upsert_rows(
                connection,
                """
                INSERT INTO units (
                    id, org_id, property_id, building_id, external_ref, unit_number, floor_label, valid_from
                ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
                ON CONFLICT (id) DO UPDATE SET
                    external_ref = EXCLUDED.external_ref, unit_number = EXCLUDED.unit_number,
                    floor_label = EXCLUDED.floor_label, valid_from = EXCLUDED.valid_from, updated_at = now()
                """,
                data.units,
            )
            await upsert_rows(
                connection,
                """
                INSERT INTO people (id, org_id, auth_subject_id, external_ref, display_name, valid_from)
                VALUES ($1, $2, $3, $4, $5, $6)
                ON CONFLICT (id) DO UPDATE SET
                    auth_subject_id = EXCLUDED.auth_subject_id, external_ref = EXCLUDED.external_ref,
                    display_name = EXCLUDED.display_name, valid_from = EXCLUDED.valid_from, updated_at = now()
                """,
                data.people,
            )
            await upsert_rows(
                connection,
                """
                INSERT INTO roles (id, org_id, person_id, role, scope, property_id, valid_from)
                VALUES ($1, $2, $3, $4, $5, $6, $7)
                ON CONFLICT (id) DO UPDATE SET
                    person_id = EXCLUDED.person_id, role = EXCLUDED.role, scope = EXCLUDED.scope,
                    property_id = EXCLUDED.property_id, valid_from = EXCLUDED.valid_from, updated_at = now()
                """,
                data.roles,
            )
            await upsert_rows(
                connection,
                """
                INSERT INTO tenancies (
                    id, org_id, property_id, unit_id, person_id, status, starts_on, is_primary_contact
                ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
                ON CONFLICT (id) DO UPDATE SET
                    property_id = EXCLUDED.property_id, unit_id = EXCLUDED.unit_id,
                    person_id = EXCLUDED.person_id, status = EXCLUDED.status,
                    starts_on = EXCLUDED.starts_on, is_primary_contact = EXCLUDED.is_primary_contact,
                    updated_at = now()
                """,
                data.tenancies,
            )
            await upsert_rows(
                connection,
                """
                INSERT INTO assets (
                    id, org_id, property_id, building_id, unit_id, external_ref, asset_type,
                    manufacturer, model_number, serial_number, installed_on, warranty_expires_on,
                    status, valid_from
                ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14)
                ON CONFLICT (id) DO UPDATE SET
                    property_id = EXCLUDED.property_id, building_id = EXCLUDED.building_id,
                    unit_id = EXCLUDED.unit_id, external_ref = EXCLUDED.external_ref,
                    asset_type = EXCLUDED.asset_type, manufacturer = EXCLUDED.manufacturer,
                    model_number = EXCLUDED.model_number, serial_number = EXCLUDED.serial_number,
                    installed_on = EXCLUDED.installed_on, warranty_expires_on = EXCLUDED.warranty_expires_on,
                    status = EXCLUDED.status, valid_from = EXCLUDED.valid_from, updated_at = now()
                """,
                data.assets,
            )
            await upsert_rows(
                connection,
                """
                INSERT INTO vendors (
                    id, org_id, external_ref, name, primary_trade, contact_name,
                    service_region_codes, insurance_expires_on, active, valid_from
                ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)
                ON CONFLICT (id) DO UPDATE SET
                    external_ref = EXCLUDED.external_ref, name = EXCLUDED.name,
                    primary_trade = EXCLUDED.primary_trade, contact_name = EXCLUDED.contact_name,
                    service_region_codes = EXCLUDED.service_region_codes,
                    insurance_expires_on = EXCLUDED.insurance_expires_on, active = EXCLUDED.active,
                    valid_from = EXCLUDED.valid_from, updated_at = now()
                """,
                data.vendors,
            )
            await upsert_rows(
                connection,
                """
                INSERT INTO vendor_scores (
                    id, org_id, vendor_id, trade, measured_at, availability_score,
                    response_time_minutes, acceptance_rate, first_time_fix_rate,
                    cost_variance_rate, warranty_eligible
                ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11)
                ON CONFLICT (id) DO UPDATE SET
                    vendor_id = EXCLUDED.vendor_id, trade = EXCLUDED.trade,
                    measured_at = EXCLUDED.measured_at, availability_score = EXCLUDED.availability_score,
                    response_time_minutes = EXCLUDED.response_time_minutes,
                    acceptance_rate = EXCLUDED.acceptance_rate,
                    first_time_fix_rate = EXCLUDED.first_time_fix_rate,
                    cost_variance_rate = EXCLUDED.cost_variance_rate,
                    warranty_eligible = EXCLUDED.warranty_eligible
                """,
                data.vendor_scores,
            )
            await upsert_rows(
                connection,
                """
                INSERT INTO tickets (
                    id, org_id, property_id, building_id, unit_id, reporter_person_id,
                    status, priority, category, symptom_summary, reported_text,
                    access_permission, pets_present, preferred_access_start,
                    preferred_access_end, acknowledged_at, submitted_at, closed_at
                ) VALUES (
                    $1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13,
                    $14, $15, $16, $17, $18
                )
                ON CONFLICT (id) DO UPDATE SET
                    property_id = EXCLUDED.property_id, building_id = EXCLUDED.building_id,
                    unit_id = EXCLUDED.unit_id, reporter_person_id = EXCLUDED.reporter_person_id,
                    status = EXCLUDED.status, priority = EXCLUDED.priority, category = EXCLUDED.category,
                    symptom_summary = EXCLUDED.symptom_summary, reported_text = EXCLUDED.reported_text,
                    access_permission = EXCLUDED.access_permission, pets_present = EXCLUDED.pets_present,
                    preferred_access_start = EXCLUDED.preferred_access_start,
                    preferred_access_end = EXCLUDED.preferred_access_end,
                    acknowledged_at = EXCLUDED.acknowledged_at, submitted_at = EXCLUDED.submitted_at,
                    closed_at = EXCLUDED.closed_at, updated_at = now()
                """,
                data.tickets,
            )

            await verify_database_seed(connection)
    finally:
        await connection.close()


async def verify_database_seed(connection: asyncpg.Connection) -> None:
    """Check database counts and the two fixtures before the transaction commits."""

    for table_name, expected in EXPECTED_COUNTS.items():
        actual = await connection.fetchval(
            f"SELECT count(*) FROM {table_name} WHERE org_id = $1",
            DEMO_ORG_ID,
        )
        if actual != expected:
            raise RuntimeError(f"{table_name} count is {actual}; expected {expected}")

    drain_count = await connection.fetchval(
        """
        SELECT count(*)
        FROM tickets AS ticket
        JOIN units AS unit
          ON unit.org_id = ticket.org_id AND unit.id = ticket.unit_id
        WHERE ticket.org_id = $1
          AND unit.unit_number = '4B'
          AND ticket.category = 'plumbing'
          AND ticket.symptom_summary = 'Kitchen drain backs up'
        """,
        DEMO_ORG_ID,
    )
    if drain_count != 3:
        raise RuntimeError(f"Unit 4B has {drain_count} kitchen-drain tickets; expected 3")

    warranty_count = await connection.fetchval(
        """
        SELECT count(*)
        FROM assets AS asset
        JOIN units AS unit
          ON unit.org_id = asset.org_id AND unit.id = asset.unit_id
        WHERE asset.org_id = $1
          AND unit.unit_number = '2C'
          AND asset.asset_type = 'water_heater'
          AND asset.installed_on = DATE '2019-03-15'
          AND asset.warranty_expires_on = DATE '2027-03-31'
        """,
        DEMO_ORG_ID,
    )
    if warranty_count != 1:
        raise RuntimeError("Unit 2C water-heater warranty fixture is missing")


def summary(data: SeedData) -> str:
    return (
        "Synthetic Resident OS seed is valid: "
        f"{len(data.properties)} properties (US-VA and US-MD), "
        f"{len(data.units)} units, {len(data.tenancies)} active tenancies, "
        f"{len(data.assets)} assets, {len(data.vendors)} vendors, and "
        f"{len(data.tickets)} historical tickets."
    )


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--database-url",
        default=os.environ.get("DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/resident_os"),
        help="PostgreSQL URL. Defaults to DATABASE_URL or the local Compose database.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate and describe the dataset without connecting to PostgreSQL.",
    )
    return parser.parse_args()


async def async_main() -> None:
    arguments = parse_arguments()
    data = build_seed_data()
    print(summary(data))
    if arguments.dry_run:
        return
    await seed_database(arguments.database_url, data)
    print(f"Seeded and verified demo organisation {DEMO_ORG_ID}.")


def main() -> int:
    try:
        asyncio.run(async_main())
    except (AssertionError, asyncpg.PostgresError, OSError, ValueError, RuntimeError) as error:
        print(f"Seed generation failed: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
