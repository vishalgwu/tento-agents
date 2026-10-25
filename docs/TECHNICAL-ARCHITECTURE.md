# Runtime architecture

## Workspace access

The public root explains the platform and links to four workspace sign-ins. Next.js exchanges credentials with Supabase and calls JWT-authenticated GET /v1/me before issuing a session cookie. Existing trusted claims determine the workspace; client role selection never changes permissions. Server workspace guards verify identity again. Maintenance and owner views read the existing tenant-scoped ticket API; technical administrator adds public readiness checks and saved run outcomes. These views provide no assignment, finance or user-management mutations.

## Request and execution flow

Browser -> Next.js server proxies on Vercel -> JWT-authenticated FastAPI on Vercel -> Postgres ticket and queued agent_run. Redis supplies API rate limits. Mutation idempotency persists the exact receipt in the same transaction as the ticket/job. Property IDs come from the resident's current tenancy, never arbitrary client-provided location claims.

Authenticated Vercel requests process individual authorized runs. An optional continuous container worker and daily Vercel recovery endpoint serve WORKER_ORG_ID. It claims jobs using FOR UPDATE SKIP LOCKED, a 300-second lease and a fencing UUID. Execution is capped at 180 seconds. Process loss permits lease recovery; failed attempts are limited to three. Trace, result and internal work-order writes commit only if the worker still owns the lease. The graph is side-effect-free outside the database, so a recovered attempt may rerun its model calls and incur another provider charge. It restarts the bounded graph; it does not claim mid-node checkpoint recovery.

## Agent composition

The worker runs brain.production.execute_maintenance: deterministic safety -> redacted intake -> eligible lexical source retrieval -> token-budgeted context -> diagnosis -> in-house dispatch planning -> independent policy audit -> deterministic terminal gate. Source-backed canonical policy configuration is immutable. Missing provider, applicable evidence or in-house capability leads to abstention. A valid automatic in-house decision creates one work order with a deterministic per-run identity in the same transaction.

Production retrieval queries active documents by tenant, ticket time and jurisdiction. It uses real PostgreSQL lexical ranks and exact citation spans. Existing hybrid/reranking components remain available for later tuning; they are not falsely presented as the active query path. Importing verified Markdown uses the existing embedding adapter and a separate OPENAI_API_KEY.

## Trust boundaries

The API verifies asymmetric Supabase JWTs and uses signed org_id/person_id/app_role. Supabase's own role remains authenticated. The optional hook reads administrator-controlled app metadata, never user metadata. Explicit tenant/reporter predicates supplement transaction-local Postgres RLS. The API database login and worker login have separate restricted grants.

Provider keys stay on Python. Next.js uses HttpOnly, Secure-in-production session cookies and same-origin mutation checks. Sessions currently expire within one hour and require signing in again. Deterministic PII rules remain present in the smaller runtime image; optional Presidio and reranker packages are developer extras.

## Operational boundaries

The API awaits one bounded worker execution per processing request; Next.js after() awaits that request after returning the saved receipt. Database leases permit recovery after interruption. Its direct compatibility endpoint /v1/agent/run still performs bounded non-persisted safety/intake analysis. The resident UI uses persisted /v1/tickets and run/status reads. Internal work orders are database records, not vendor dispatch receipts. No external operational transport is enabled.

Use the explicit migration runner and database backups. Runtime roles cannot apply schema changes. Use scripts/deploy_vercel.py to stage and deploy the two Vercel projects. See DEPLOYMENT.md and KEYS-AND-SETUP.md.

## Part 2 measurement and caching

Production OpenAI stages stream internally to measure first non-empty content while retaining full JSON/schema validation before graph handoff. Deployment-owned tier model IDs, temperature and output caps are included in request identity. Versioned token prices estimate known-model usage; content-free worker logs carry first-content timing, pricing version and generation settings. Existing PostgreSQL receipts retain per-attempt usage, elapsed latency and estimates; historical records are preserved.

Verified-source ingestion reuses embeddings through a tenant-scoped Upstash Redis cache with a 24-hour TTL, dimensional/model/digest validation and cache-miss fallback on Redis errors. No resident answer cache, cross-session personal memory or new document authority is introduced. [Part 2 methods and evidence](PART-2-GENAI.md).

## Isolated policy demonstration

The /demo explorer serves packaged real model-run recordings without authentication or paid per-visit calls. Its /api/demo proxy requires same-origin requests and a session, forwarding to the JWT-, tenant-, rate-limit- and idempotency-protected /v1/demo/run route only while DEMO_MODE=true. This path injects fictional inputs into the existing bounded graph, using a private in-memory SQLite FTS5/BM25 index and exact-span claims. It has no production knowledge/ticket/work-order persistence authority. Source checksums and ineligible fixture labels are validated on load. See DEMO.md.
