# infra/migrations

Postgres DDL — the schema of record for Resident OS.

## Ordering

Numbered SQL files, applied in order:

```
0001_orgs_properties_units.sql
0002_people_roles_tenancies.sql
0003_assets_vendors.sql
0004_tickets_state.sql
0005_agent_runs_steps_llm_calls.sql
0006_decisions_audit.sql
0007_knowledge_chunks_embeddings.sql
0008_memory_stores.sql
0009_rls_policies.sql          -- Row Level Security everywhere, cross-tenant tested
```

## Non-negotiables

- **RLS on every table.** Cross-tenant test suite runs in CI; a query from org A returning any row from org B is a hard fail.
- **`jurisdiction` lives on `properties`.** Habitability SLAs, KB filters, and audit records must all agree without special cases.
- **No `health_*` columns anywhere.** Ever. The wellness surface stores `participated_in(event_id)` and nothing inferential — see [docs/01-strategy-and-product.md §8.1](../../docs/01-strategy-and-product.md).
- Every migration is forward-only in production. Down-migrations exist for local dev only.

## Owner

Vishal. See [PHASES.md](../../docs/PHASES.md).

---
> Resident OS — the AI operations layer for apartment communities.
> Root: [README.md](../../README.md)
