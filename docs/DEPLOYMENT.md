# Local setup and Vercel + Railway deployment

## 1. Install and configure

Use Python 3.12, Node.js 22 and pnpm 11.19.0. Install requirements.txt and run pnpm install --frozen-lockfile. Copy .env.example to an ignored local file and supply the values in KEYS-AND-SETUP.md. Load API/worker values into each shell explicitly. Place the three web values in apps/web/.env.local. Never put an administrator database URL or provider key in NEXT_PUBLIC_*.

The selected MVP creates internal work orders only. It needs no vendor, email, R2 or Google credentials. Automated tests use scripted providers and do not need paid AI keys.

## 2. Start persistence and apply migrations

```powershell
docker compose -f infra/docker-compose.dev.yml up -d
$env:PYTHONPATH="services/api/src;services/brain/src"
python -m api.migrate
```

The migration command requires MIGRATION_DATABASE_URL with an administrator connection. It uses an advisory lock and a checksum ledger. Run it as an explicit setup/release job, never on API startup. Repeating it skips recorded migrations. A fresh database applies all five migrations in order.

For existing installations: back up and rehearse on a disposable copy. If the first three migrations were applied manually before a migration ledger existed, inspect the schema, then use python -m api.migrate --adopt-through 0003. Adoption records existing state; it does not verify that those earlier scripts ran. Do not adopt migrations that have not been applied. Migration 0004 permanently removes obsolete workflow records and translates historical states. Archive pre-upgrade graph threads rather than resuming incompatible checkpoints. Restore the backup to recover deleted records.

Run infra/auth/runtime-roles.sql as administrator after migration, then set strong login passwords through the database console. The API uses resident_api; the worker and importer use resident_worker. Both must be NOSUPERUSER and NOBYPASSRLS. Runtime credentials never own the database. Grant CONNECT on the actual database if its defaults restrict it. Table and sequence grants are supplied by the role script.

The compose defaults use local Postgres port 55432 and Redis port 56379 to reduce conflicts with other projects; POSTGRES_PORT and REDIS_PORT can override them. The example connection values must match your chosen ports. If those ports are occupied, choose unused ones. Do not stop another project's database.

## 3. Configure accounts, tenancy and real sources

Follow KEYS-AND-SETUP.md for Supabase's signed application claims and user membership. Provision actual organisation/property/building/unit/person/current-tenancy records. Synthetic seed files remain test-only. The report form lists eligible current residences; it never accepts arbitrary property IDs.

Import verified source versions with python -m brain.ingest --org-id YOUR_ORG_UUID --source verified.md --claims policy.json. This command requires OPENAI_API_KEY for its embedding adapter. Sources must be active, production-eligible and properly scoped; source policy spans must match exactly. Configure properties.in_house_trades with actual available trades. Missing evidence or capability causes abstention rather than invented plans.

## 4. Run the application locally

In the API shell, set DATABASE_URL for resident_api, REDIS_URL and Supabase settings:

```powershell
$env:PYTHONPATH="services/api/src;services/brain/src"
python -m uvicorn api.main:app --host 127.0.0.1 --port 8000
```

In a worker shell, set DATABASE_URL for resident_worker, WORKER_ORG_ID and the Anthropic key/model:

```powershell
$env:PYTHONPATH="services/api/src;services/brain/src"
python -m api.worker
```

In the web shell, run pnpm dev:web. Sign in at /resident/sign-in, submit at /app/report, then check /app/tickets. The receipt contains a saved ticket number. The detail page polls while the run is queued/running, then shows the saved outcome and any created internal work order. Emergency guidance appears immediately, before the worker finishes.

GET /healthz checks database and Redis readiness only. It does not prove model credentials or source readiness. The direct compatibility POST /v1/agent/run remains non-persisted safety/intake analysis; the resident product uses POST /v1/tickets.

## 5. Verify before deploying

Run the checks in README.md. For real database integration, migrate a disposable database whose name ends _test and set TEST_DATABASE_URL using an administrator test connection. Tests use temporary restricted roles and rollback their records. They cover real RLS, response replay, lease recovery/fencing, emergency execution, missing-provider abstention and a full scripted four-agent plan that creates one internal work order.

The web proxy test is python apps/web/scripts/check-proxies.py. It uses an explicit local upstream fixture, not live Supabase. Verify actual sign-in, current-tenancy access, same-tenant privacy, expired sessions, normal and emergency reports, duplicate keys, failed model calls, worker restarts, missing policy, and a successful in-house order once keys and real sources exist.

## 6. Create Railway services

1. Create a Railway project with Postgres supporting pgvector and Redis. Apply migrations through a separate administrator setup job. Use restricted runtime logins afterward.
2. Create an API service from this repository. Keep service Root Directory at the repository root. Set the config file path to /infra/railway/api.json. It builds services/api/Dockerfile, uses PORT and checks /healthz.
3. Set API DATABASE_URL, REDIS_URL, SUPABASE_URL and JWT settings. Model keys on the API are only needed for the direct compatibility analysis endpoint.
4. Create a second service from the same root and Dockerfile, using /infra/railway/worker.json. It runs python -m api.worker. Give it the worker DATABASE_URL, WORKER_ORG_ID, ANTHROPIC_API_KEY and ANTHROPIC_MODEL. It needs no public domain and no web health check.
5. Generate an HTTPS domain for the API. Confirm /healthz is 200 and the worker logs show jobs completing. One worker deployment is scoped to one organisation. Give another organisation its own scoped worker.
6. Configure database backups, log retention and provider spend limits. Record how to restore the last healthy application revision and database backup.

The image uses requirements.runtime.txt: no optional cross-encoder model or large NLP assets are needed for the current lexical path. Mandatory deterministic PII rules remain enabled. Tokenizer data is prewarmed during image build. See Railway's official configuration reference: https://docs.railway.com/config-as-code/reference.

## 7. Create Vercel frontend

1. Import the tested repository commit into the intended Vercel project.
2. Set Root Directory to apps/web, enable access to workspace files outside it, choose Next.js and Node.js 22, and keep the pnpm lockfile.
3. Use the included apps/web/vercel.json. Set server-only API_BASE_URL to the Railway API HTTPS origin, plus SUPABASE_URL and SUPABASE_ANON_KEY for each environment.
4. Deploy a preview and test real login -> residence -> saved ticket -> worker result -> internal work order. Verify mobile layout and error states.
5. Deploy the tested commit to production and repeat the tests with production services.

The synchronous proxy has a bounded timeout. Full graph work runs in Railway's durable worker, outside Vercel's request lifetime. Duration limits vary by plan/settings: https://vercel.com/docs/functions/configuring-functions/duration.

## Final live acceptance

Local code and scripted/database tests do not prove a live provider or hosted deployment. Live acceptance needs the final keys, trusted account/tenancy data, verified policies, in-house capability settings and hosting projects. Work orders are internal records awaiting normal assignment; no vendor contact, notification or scheduled visit is implied.
