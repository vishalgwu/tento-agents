# Vercel release and local testing

The existing Supabase database, authentication, runtime roles and records are retained. Do not rerun initial provisioning, seeds, destructive migrations or token-hook setup for this release.

## Verified connections

The read-only release preflight confirmed resident_api and resident_worker connections with neither superuser nor RLS bypass, Upstash Redis PING, Supabase public signing keys, and access to the configured OpenAI model. Run `python scripts/check_live_services.py` to repeat these checks; it loads the ignored root .env and prints no credentials. It does not create tickets, run paid inference or validate policy content.

## Deploy both services on Vercel

The frontend and FastAPI API are separate Vercel projects. Existing PostgreSQL jobs remain durable; no always-running Railway service is required for the Vercel path.

1. Authenticate the intended account with `npx vercel login`. Approve the connected app's workspace access if Vercel returns 403. Application keys do not grant hosting account access.
2. From this repository run:

```powershell
python scripts/deploy_vercel.py --prepare-only
python scripts/deploy_vercel.py --scope YOUR_VERCEL_WORKSPACE_SLUG
```

The live production URLs are https://tento-resident-os.vercel.app and https://tento-resident-api.vercel.app. The script stages allowlisted source trees under ignored tmp/, creates or configures tento-resident-api and tento-resident-os, uploads allowlisted production environment variables via CLI stdin, deploys the API, requires a healthy /healthz, then deploys the frontend with that API URL. It never uploads root .env, administrator connections, database passwords as standalone values, developer environments, or synthetic knowledge files. Runtime database URLs necessarily include the restricted login credentials. Values remain in Vercel's environment store. Local release results contain public URLs only. Both projects use Fluid Compute and a 300-second execution duration. Only production environment variables are provisioned; do not use previews against production data without an explicit separate configuration.

The backend bundle uses Python 3.12, the existing minimal pinned runtime dependencies and source packages. The frontend retains the workspace lockfile and Node 22. Vercel's API deployment must accept server-to-server requests; FastAPI still requires JWT authentication for all /v1 routes. Interactive Vercel deployment protection is disabled on the API project for this reason.

## Worker execution and recovery

After a ticket receipt is saved, Next.js after() awaits an authenticated call to POST /v1/runs/{id}/process without delaying the resident's response. The endpoint verifies the run's tenant and reporter ownership using the request database role before opening the restricted worker connection. Processing claims only that run. Terminal runs and concurrently leased runs are not executed twice. The existing 180-second execution budget, 300-second lease, fencing token, three-attempt cap, transaction-local RLS and deterministic internal work-order identity remain in force.

Queued/running detail reads schedule another attempt, so revisiting a ticket recovers eligible work. A protected daily cron processes one eligible job for WORKER_ORG_ID, using a generated CRON_SECRET retained in the ignored root .env and Vercel. Hobby cron runs daily, not every minute; recovery can therefore be delayed if the resident closes the page and a function is interrupted. This is a bounded MVP worker, not a continuously running queue consumer or a guaranteed immediate unattended retry service. For larger backlogs or strict unattended latency, retain the existing container worker on a suitable paid host or add a supported durable queue transport after choosing its account and budget.

The optional container worker remains `python -m api.worker`, with WORKER_DATABASE_URL and WORKER_ORG_ID. API requests use DATABASE_URL. On Vercel DATABASE_POOL_MODE=null prevents retaining idle connections between requests; Supabase remains the connection pooler.

## Local startup

Use Python 3.12, Node 22 and pnpm 11.19.0. Install requirements.txt and `pnpm install --frozen-lockfile`. Existing root .env contains service settings; Uvicorn does not load it automatically unless explicitly requested:

```powershell
$env:PYTHONPATH="services/api/src;services/brain/src"
python -m uvicorn api.main:app --env-file .env --host 127.0.0.1 --port 8000
```

Set API_BASE_URL=http://127.0.0.1:8000, SUPABASE_URL and SUPABASE_ANON_KEY in ignored apps/web/.env.local, then run `pnpm dev:web`. The frontend now schedules processing itself. Do not also start a container worker unless desired; leases still protect concurrent processing.

## Release acceptance

Run Python Ruff, format, mypy, pytest; regenerate OpenAPI/shared types; run web typecheck, production build and apps/web/scripts/check-proxies.py. The five database tests intentionally skip without a disposable *_test database. Never point that test setting at production.

Live acceptance requires an existing resident to sign in, select an authorized residence, submit a text report, open its saved ticket and observe a terminal result. With no verified policy evidence, abstention is the expected safe result. A successful in-house work order additionally requires real approved policy sources and actual configured in-house trades. Synthetic fixtures must never be imported to make a demo pass.

Verify /healthz, unauthorized API rejection, cross-tenant denial, production cookies, saved result and error logs. Do not claim deployed acceptance until the actual URLs and real login journey have been checked.

## Operations

Run `python scripts/check_deployment.py` for credential-free production boundary checks. The production-health workflow is active on main and checks every six hours; GitHub account notification preferences determine alert delivery.

Use Vercel runtime logs to monitor worker_dispatch_failed/worker_dispatch_unavailable, job_failed and job_lease_lost; logs must not contain resident text, JWTs or provider keys. Monitor database connections, Redis availability, queued job age and OpenAI spend. /healthz checks database and Redis, not policy or model readiness. Configure a health monitor and spend alerts in the relevant accounts.

Confirm the Supabase plan's actual backup coverage and retention in the dashboard; do not assume a free project has managed backups. Keep an encrypted off-host database backup and rehearse restoration to a separate project. Roll back application code through Vercel without rolling back or resetting resident records. Never restore over production without an explicit recovery decision. No migrations are executed at application startup or by the deployment script.

## Part 2 model settings and measurement logs

OPENAI_MODEL remains required. Optional OPENAI_MODEL_SMALL, OPENAI_MODEL_MID and OPENAI_MODEL_LARGE select server-owned tier routes; blank values keep the base model. OPENAI_TEMPERATURE=0 is verified for the current GPT-4.1-mini deployment. Omit it for models without sampling controls. OPENAI_MAX_OUTPUT_TOKENS defaults to 1024. The deployment helper allowlists these settings and transfers them without printing values.

Look for JSON events with event=model_completion in worker/API logs. They contain scoped run identity, task, attempt, model, temperature, first_token_ms, elapsed latency, token counts and versioned estimated token cost, without prompt/response text. Provider completion is not equivalent to a valid final assessment; inspect the saved workflow outcome. Unknown usage or rates remain unpriced in logs. See PART-2-GENAI.md for benchmark methodology and cost limitations.

The source importer uses REDIS_URL for tenant-scoped 24-hour embedding reuse, retaining eligibility checks and exact source versions. Redis errors are cache misses; they do not bypass the model provider or policy checks. This release requires no database migration and does not import synthetic policies.
