# services/api

FastAPI HTTP + SSE surface for Resident OS. Thin: routers, dependencies, request/response schemas. All real work delegates to `services/brain` or the database.

## What lives here

- `routers/` — one file per resource (`tickets`, `runs`, `decisions`, `approvals`, `vendors`, `webhooks`)
- `deps/` — auth (Supabase JWT), org-scope enforcement, rate limits, request-id propagation
- `schemas/` — Pydantic request/response models; these drive `docs/openapi.yaml`
- `sse/` — streaming step events for the trace viewer

## Contracts

- OpenAPI spec: [docs/openapi.yaml](../../docs/openapi.yaml) — hand-authored, single source of truth for API shapes.
- All shapes here must round-trip cleanly to the generated types in [packages/shared-types](../../packages/shared-types).

## Owner

Vishal. See [PHASES.md](../../docs/PHASES.md).

---
> Resident OS — the AI operations layer for apartment communities.
> Root: [README.md](../../README.md)
