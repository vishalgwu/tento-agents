# infra

Local development orchestration and deployment glue.

## Contents

- `docker-compose.yml` — Postgres 15 + pgvector, LiteLLM, MinIO (S3-compatible), the four services, and the web app for a single-command local stack.
- `docker-compose.dev.yml` — hot-reload overlay for the local loop.
- `migrations/` — DDL (see [migrations/README.md](migrations/README.md)).
- `seed/` — synthetic data generator (see [seed/README.md](seed/README.md)).
- `deploy/` — production configuration (Fly for the services, Vercel for `apps/web`, Supabase for the DB).

## Local bring-up

```bash
docker compose up
```

Success gate: hybrid search returns sane results and `recall@5` on the retrieval eval set produces a number.

## Owner

Track **B** owns docker-compose and CI/CD workflows. Track **A** owns migrations and seed.
See [docs/PHASES.md](../docs/PHASES.md).

---
> Resident OS — the AI operations layer for apartment communities.
> Root: [README.md](../README.md)
