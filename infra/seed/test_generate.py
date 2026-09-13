"""Regression coverage for the deterministic synthetic dataset."""

from __future__ import annotations

from datetime import date, datetime

from generate import EXPECTED_COUNTS, build_seed_data, stable_id


def test_seed_data_is_deterministic_and_preserves_demo_fixtures() -> None:
    first = build_seed_data()
    second = build_seed_data()

    assert first == second
    assert {
        "orgs": len(first.orgs),
        "properties": len(first.properties),
        "units": len(first.units),
        "tenancies": len(first.tenancies),
        "assets": len(first.assets),
        "vendors": len(first.vendors),
        "tickets": len(first.tickets),
    } == EXPECTED_COUNTS

    unit_4b = stable_id("unit", "VA-4B")
    drain_dates: list[date] = []
    for ticket in first.tickets:
        if (
            ticket[4] != unit_4b
            or ticket[8] != "plumbing"
            or ticket[9] != "Kitchen drain backs up"
        ):
            continue
        submitted_at = ticket[16]
        assert isinstance(submitted_at, datetime)
        drain_dates.append(submitted_at.date())
    assert drain_dates == [date(2024, 12, 15), date(2025, 7, 15), date(2026, 2, 15)]

    unit_2c = stable_id("unit", "VA-2C")
    water_heaters = [
        asset
        for asset in first.assets
        if asset[4] == unit_2c
        and asset[6] == "water_heater"
        and asset[10] == date(2019, 3, 15)
        and asset[11] == date(2027, 3, 31)
    ]
    assert len(water_heaters) == 1
