# infra/seed

Synthetic data generator for local dev and demos. Not for production.

## What it produces

Per the Week 1–2 gate:

- 1 org, 1 property, 8 buildings
- **400 units**
- **1,200 historical tickets** with realistic priority, trade, and chargeback distributions
- **40 assets** (water heaters, HVAC units, appliances) with warranty status and install dates
- **8 vendors** across trades with accept-rate and first-time-fix priors
- 5 residents per unit with roles and tenancy records
- Reject-reason samples so the approval queue has labeled examples on day one

## Why synthetic, and why now

- The demo needs recurring-failure units (e.g. unit 4B's 3rd kitchen drain ticket in 14 months) for the council-triggering story to work.
- Retrieval eval needs enough KB-relevant tickets to produce meaningful recall@k numbers.
- We do not want fabricated data on any customer instance — the generator refuses to run against a DB whose `orgs.plan` is not `demo` or `local`.

## Owner

Vishal. See [PHASES.md](../../docs/PHASES.md).

---
> Resident OS — the AI operations layer for apartment communities.
> Root: [README.md](../../README.md)
