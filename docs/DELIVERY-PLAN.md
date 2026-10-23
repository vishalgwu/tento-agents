# Delivery status

## Implemented

- Connected sign-in, authorised residence selection, saved reports, history and status polling.
- Atomic ticket/job/idempotency receipts and tenant/reporter access boundaries.
- Durable leased worker with bounded retries and fencing.
- Full autonomous graph with real eligible source queries and saved traces.
- Verified-source import and immutable policy configuration.
- Internal work-order creation for validated in-house plans.
- Railway API/worker configuration, Supabase token hook, migration runner and restricted role script.

## Local verification

Ruff, Python/TypeScript checks, unit tests, real PostgreSQL integration and HTTP proxy contracts must pass before release. Database tests use isolated data; model tests use scripted responses. Record the exact latest commands/results in the release handoff.

## Final configuration and live acceptance

Add the keys and trusted membership described in KEYS-AND-SETUP.md. Supply actual property data, in-house capabilities and verified source versions. Create Railway and Vercel projects, deploy a tested commit, then verify real sign-in, model calls and saved internal work orders over HTTPS. These steps cannot be claimed complete before service configuration exists.

Media, vendor integrations, external notifications, payments and extra dashboards are outside the chosen MVP.
