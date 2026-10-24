# Resident OS web

The Next.js application provides resident maintenance submission at `/app/report`, request history at `/app/tickets`, and current request status at `/app/tickets/[id]`. Account access is at `/resident/sign-in`. Owner and technician URLs redirect to the resident workspace.

## Local development

From the repository root:

```powershell
pnpm install --frozen-lockfile
pnpm typecheck:web
pnpm build:web
pnpm dev:web
```

Create `apps/web/.env.local` with `API_BASE_URL=http://localhost:8000`, `SUPABASE_URL`, and `SUPABASE_ANON_KEY`. Use the public Supabase anonymous key, never the service-role key. Accounts must exist, carry the organization/person/role claims expected by the backend, and have an active tenancy. See the root deployment guide for API, database migration, and worker setup.

## Resident workflow

1. The sign-in form exchanges credentials with Supabase Auth through `/api/session`. The server stores a short-lived access token in an HttpOnly, SameSite Strict cookie. Cookies are Secure in production. Sessions expire after at most one hour; sign in again when needed.
2. The report form loads authorized residences from `/api/tenancies`. A resident chooses a residence, describes the issue, and optionally specifies access permission and pets.
3. `/api/tickets` forwards the report to `POST /v1/tickets` with the user's bearer token and an idempotency key. Retrying the same unchanged submission retains its key, preventing duplicate tickets after a network interruption.
4. The backend persists the ticket and queued run before responding. The browser opens the saved request detail. If the submission detects an emergency, urgent guidance is shown immediately with a link to the saved request.
5. The detail polls every three seconds while the durable run is queued or running, then displays the actual assessment, known facts, rationale, and ticket status. A failed assessment leaves the saved report visible and gives clear next steps.
6. History shows the resident's existing requests, supports cursor pagination, and can be refreshed explicitly.

Mutation routes require a matching Origin header. Upstream requests disable redirects and caching. Raw backend exceptions and credentials are never returned to the browser. `DELETE /api/session` clears the local session cookie. Read proxies forward the same user identity; the backend enforces organization and resident ownership boundaries.

`/api/agent` remains a bounded direct-assessment endpoint for API clients; the resident interface uses the persisted ticket workflow.

## Vercel

Set the project Root Directory to `apps/web`, enable access to workspace files outside that directory, and use the included `vercel.json`. Set `API_BASE_URL` to the HTTPS origin of the separately hosted Python API, plus `SUPABASE_URL` and `SUPABASE_ANON_KEY`. No backend secrets belong in `NEXT_PUBLIC_*` variables.

Ticket submission persists and enqueues work with a 15-second API deadline. After the receipt is returned, Next.js `after()` calls the authenticated Python `POST /v1/runs/{run_id}/process` endpoint. This call has a 240-second deadline; ticket submission and detail functions have a 300-second maximum duration. The Python endpoint bounds execution to 180 seconds and uses the existing database lease to prevent duplicate execution.

Authenticated detail reads schedule the same worker call while a run is queued or running, allowing recovery when the original dispatch was interrupted. Terminal runs do not dispatch work. Dispatch failures never replace a successfully saved response; later detail reads can retry. Polling remains uncached and stops after a terminal run state or request failure.

Deploy the Python API as a separate Vercel project with its runner duration configured, or keep a dedicated worker on the Python host. Request-driven dispatch resumes while users view pending requests; a continuous external worker or scheduler remains useful for unattended recovery.

## Verification

Typecheck and production build validate all routes. To check the web HTTP boundary against an explicitly isolated authentication/API fixture:

```powershell
python apps/web/scripts/check-proxies.py
```

This starts and stops a temporary Next.js dev server and verifies cookies, authorized residence and ticket contracts, unchanged retry keys, validation, cross-origin denial, post-response worker dispatch, pending-run recovery, terminal-run suppression, and failure isolation. It does not connect to live Supabase or Postgres.

 Verify the resident workflow with a provisioned account and active tenancy: sign in, submit a report, confirm it appears in history, observe queued/running transition, and refresh the detail after completion. A second resident must not be able to read the first resident's request ID. Provider and database integrations require configured deployment credentials; a local UI build alone does not verify those external services.
