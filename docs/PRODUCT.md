# Resident OS MVP

## Connected user journey

1. Sign in with a Supabase user carrying trusted tenant membership.
2. Select an active authorised residence and submit a text report.
3. Receive a real ticket number immediately. Deterministic safety screening also returns urgent guidance immediately for safety signals.
4. A separate worker leases the saved job, then runs safety, intake, applicable source retrieval, diagnosis, planning and policy validation.
5. Inspect saved ticket history and current status. The detail page polls only queued/running work.
6. A valid in-house plan creates an internal work order with a real identifier; unsupported cases abstain and retain the report.

Internal work orders await normal operational assignment. The MVP does not contact vendors, schedule visits, send notifications, upload media or process payments.

## Completion boundaries

Automated processing returns completed, abstained or emergency. Queue lifecycle separately uses queued/running/completed/degraded/failed. A completed graph means a validated internal plan, not a completed repair. Missing live evidence or model access cannot produce a work order.

Database migrations, RLS/lease/replay behavior and scripted full-graph execution are testable without paid keys. Real Supabase membership, verified property sources, provider credentials and hosting accounts must be configured before live acceptance.
