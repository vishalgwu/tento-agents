# Resident OS

Tento Resident OS has one main page with Resident, Maintenance, Owner and Technical administrator workspaces. Maintenance/owner/admin provide verified, read-only operational views; role selection never grants access. The connected maintenance flow lets a resident sign in, select an authorised residence, save a report, and follow its actual status. A separate durable Python worker runs safety, intake, source retrieval, diagnosis, dispatch planning and policy validation. A validated in-house plan creates a real internal work order. No vendor is contacted and no visit is claimed to be scheduled.

## Start here

- [Keys and account setup](docs/KEYS-AND-SETUP.md): add credentials at the end; automated tests need no paid model keys.
- [Local startup and Vercel deployment](docs/DEPLOYMENT.md).
- [Product scope](docs/PRODUCT.md) and [architecture](docs/TECHNICAL-ARCHITECTURE.md).

## Local workflow

Use Python 3.12, Node.js 22 and pnpm 11.19.0. Install requirements.txt and run pnpm install --frozen-lockfile. Configure ignored API environment values and apps/web/.env.local using .env.example. Explicitly load the API environment into your shell; Uvicorn does not load the root file automatically.

Start Postgres with pgvector and Redis, apply migrations with an administrator connection, and configure restricted runtime roles. Then run:

```powershell
$env:PYTHONPATH="services/api/src;services/brain/src"
python -m uvicorn api.main:app --reload --port 8000
```

In a second shell with WORKER_DATABASE_URL for the worker role and WORKER_ORG_ID set:

```powershell
$env:PYTHONPATH="services/api/src;services/brain/src"
python -m api.worker
```

In a third shell, run pnpm dev:web. Open /resident/sign-in, then /app/report and /app/tickets. Real membership and current tenancy records are required. Without a model key or live policy sources, reports remain saved and the worker returns explicit abstention.

## Verify

```powershell
python -m ruff check services/api services/brain infra/seed scripts/export_openapi.py
python -m ruff format --check services/api services/brain infra/seed
python -m mypy
python -m pytest -q
python scripts/export_openapi.py
pnpm generate:api
pnpm typecheck:web
pnpm build:web
python apps/web/scripts/check-proxies.py
```

Set TEST_DATABASE_URL to a migrated disposable *_test database to include the real PostgreSQL integration tests; otherwise those tests skip. CI includes a pgvector integration job. Proxy tests use explicit upstream fixtures. Scripted model tests do not claim live provider success.

## Hosting

The live app is [tento-resident-os.vercel.app](https://tento-resident-os.vercel.app). Vercel hosts the Next.js frontend and a separate FastAPI project. The frontend schedules authenticated, bounded processing after saving tickets; PostgreSQL retains the queue, leases and results. A protected daily cron provides limited recovery for the configured organization. See [release status](docs/RELEASE-STATUS.md) for verified results and remaining policy requirements, and [deployment](docs/DEPLOYMENT.md) for automated release commands. The existing container worker remains available for continuous processing.

The runtime image omits optional cross-encoder/NLP model packages; deterministic PII regex protection remains enabled. Source fixtures stay outside production indexes. Media uploads, vendor scheduling, external notifications, payments and extra dashboards are outside this internal-work-order MVP.

See [LICENSE](LICENSE).
