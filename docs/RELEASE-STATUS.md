# Part 2A: measured model gateway and embedding reuse - 25 October 2026

Part 1 remains documented at 156133f. Part 2A adds deployment-controlled model tier overrides, explicit temperature validation/configuration, internal streaming with first-content timing, versioned token-price estimates, content-free model metric logs and tenant-scoped Upstash embedding reuse for verified-source ingestion. No database migration, policy import, account provisioning or resident-record rewrite is included.

The checked-in synthetic benchmark reports and resume-safe bullets are in [PART-2-GENAI.md](PART-2-GENAI.md). They disclose sample size, exact scope and tail latency. A read-only production check found zero active sources and zero canonical policy claims for the configured tenant. The only required human handoff is supplying verified property policies; [one-page checklist](../output/pdf/tento-part2-human-task.pdf). MCP, persistent personal memory, live dense/reranking and RAG faithfulness are not claimed as shipped.

Local verification: Ruff lint/format, 348 passing Python tests (five dedicated PostgreSQL tests skipped locally), production Next.js build and hosted cache isolation/TTL/cleanup. Full mypy passed across 119 files. Web proxy/ticket/auth regression checks, TypeScript and the production Next.js build passed.

Release implementation: **43a090d**. [Python quality and PostgreSQL integration](https://github.com/vishalgwu/tento-agents/actions/runs/40211166242) and [Web quality](https://github.com/vishalgwu/tento-agents/actions/runs/40211166332) passed. The five dedicated PostgreSQL cases ran in CI against a disposable migrated database. Both existing Vercel projects were deployed with the secure allowlisted environment helper; no migration or production data import occurred.

Post-deployment checks passed for API/database/Redis health, four workspace entries, authentication and same-origin boundaries. Direct read-only service checks confirmed resident_api/resident_worker are non-superuser, NOBYPASSRLS roles, plus Supabase JWKS and OpenAI model access. Hosted vector-cache tests confirmed tenant isolation, expiry and cleanup. Public benchmark cards were verified expanded on desktop and at 320px, with no horizontal page overflow; temporary viewport overrides were reset. [Release screenshot](../output/release/tento-part2-measurements.png).

The paired synthetic reports match the release source hashes. These are local development measurements, not deployed load-test results or population accuracy claims. Production evidence still contains no approved policy sources, so policy-backed dispatch/faithfulness acceptance remains blocked on the single source-content handoff.

---

# Engineering showcase and screenshot gallery - 25 October 2026

The README and live home-page #engineering section now present source-audited models/routing, context/RAG, multi-agent orchestration, per-run memory, Supabase/PostgreSQL, Upstash/caching, guardrails, PII, prompt-injection boundaries, security, evaluation, execution limits, temperature behavior, TTFT and cost instrumentation. Status labels separate deployed composition from optional/tested modules and absent capabilities. MCP transport, live reranking, token-streaming TTFT and priced cost totals are not claimed as production features.

README includes real public-page screenshots of the home page and blank sign-in form, plus the live engineering showcase. No account credentials or private resident records appear in these screenshots. docs/ENGINEERING.md links implementation details to the source and explains caveats, including single physical model routing and restart-based worker recovery.

Release code: 68bf6da. Production web build, TypeScript and the existing isolated role/proxy/ticket-flow suite passed. [GitHub Web quality](https://github.com/vishalgwu/tento-agents/actions/runs/40164286108) passed. The frontend was deployed to the existing Vercel project. Desktop and 320px engineering layout checks showed no horizontal page overflow; MCP/cost disclosures expanded correctly and temporary viewport overrides were reset. Source-file links in the engineering deep dive were checked locally.

This release documents and presents existing implementation; it does not enable MCP, reranking, persistent conversational memory, new providers or performance/cost benchmarks. Historical release evidence follows.

---

# Brand and UI release - 25 October 2026

The current Vercel frontend uses the original Tento forest/ivory/lime identity, editorial headings, SVG wordmark and favicon, original conceptual courtyard imagery, responsive role-entry cards, branded sign-in layout and consistent workspace framing. Workspace summary counts derive only from loaded authorized records; no fabricated customer, occupancy or performance statistics were added.

Code release: 9129660. Frontend production build and TypeScript passed. The existing isolated HTTP suite passed for sign-in, all four role workspaces, forged-role denial, tenant-bound ticket proxies and worker-dispatch failure isolation. [GitHub Web quality](https://github.com/vishalgwu/tento-agents/actions/runs/40146048030) passed. Production smoke checks passed for API/database/Redis health, the main portal, all four login entries, authentication and same-origin protection.

Visual QA covered production desktop at 1280px and narrow phone layouts at 320px. The final narrow sign-in and dashboard checks found no horizontal overflow. The original architectural image loaded correctly in the rendered hero, and temporary browser viewport overrides were reset. A production preview is saved at output/release/tento-brand-home.png and shown in README.md. The brand guide is docs/BRAND.md.

This release changes presentation and derives display summaries from existing records; it does not change account roles, tenant authorization, database schema or agent execution. Historical technical/account acceptance notes follow.

---

# Main application update - 24 October 2026

The main page now presents Tento Resident OS, its GenAI maintenance purpose and four workspace sign-in entries. Developer means technical administrator. /sign-in shares one credential flow; /v1/me supplies the API-verified organization, person and role. Neither client fields nor a selected login card grants a role. Server-rendered workspace pages verify access again before loading records.

Maintenance, owner and technical administrator pages now display real authorized request data rather than redirecting to the resident form. These are read-only views. Admin adds service readiness and recorded run errors; no keys are shown. Resident reporting and the existing autonomous pipeline remain intact.

Removed 11 unused code/package files: the vendor page/signing helper, unused badge/separator, and the unused shared decorative UI package. Removed dead credential suggestions and replaced the obsolete deployment plan. Existing data, migrations and the user's local login-test changes were preserved.

Verification: 339 Python tests passed, 5 disposable-database tests skipped locally. Ruff, TypeScript and production web build passed. Isolated HTTP tests passed for all four role workspaces, resident-to-owner/admin denial, forged-role rejection and the existing ticket/worker flow. All three staff workspaces were subsequently verified live using the account-owner-approved operations administrator assignment described below. No role was granted before explicit account-owner approval.

## Final portal validation

- Main portal, all four role sign-in entries, API/database/Redis health, authentication and same-origin protection pass on the deployed URLs.
- Shared login navigation is neutral; it no longer shows resident-only actions on staff/admin sign-in pages.
- The removed vendor route returns 404. Owner/admin pages redirect unauthenticated visitors to the matching workspace sign-in.
- [Python quality and PostgreSQL integration](https://github.com/vishalgwu/tento-agents/actions/runs/40116031675): passed for portal API code 52afcb0.
- [Web quality](https://github.com/vishalgwu/tento-agents/actions/runs/40116163535): passed for final portal commit cf9e7b6.
- [Production health](https://github.com/vishalgwu/tento-agents/actions/runs/40131734869): passed for cf9e7b6.

## Approved account-role change

The account owner explicitly approved promoting the selected existing resident account to operations_admin after being told that resident submission would no longer be available through that login. The role change was applied only to auth.users.raw_app_meta_data.resident_os.app_role for the approved account in the configured organization. Its organization/person identity, tenancy and ticket records were preserved. A minimal change receipt is stored in ignored tmp/approved-admin-role-change.json; no email or credentials are committed here.

Fresh sign-in is required because previously issued JWTs retain their old claims until refreshed or expired. The operations administrator role is allowed into technical administrator, maintenance and owner workspaces. A separate correctly provisioned resident account is now required for new resident submissions in this organization; the user accepted this consequence rather than keeping the selected account as a resident. A fresh sign-in succeeded through the production form. The same live session then opened /admin, /maintenance and /owner. Each displayed the existing three authorized requests; /admin also reported database and Redis readiness. No ticket records were created, deleted or modified during these checks. The existing password was used only for the authorized login and was not persisted in application files or documentation.

The earlier production release evidence below is historical and covers the connected maintenance pipeline. The current deployment uses the same Vercel project URLs.

---

# Release status - 24 October 2026

## Verified this release

- Existing API and worker PostgreSQL logins connect and enforce RLS; neither is a superuser or RLS-bypass role.
- Hosted Upstash Redis responds; Supabase signing keys are available; the configured OpenAI model is accessible.
- OpenAI-first production and compatibility routes use the existing provider configuration with optional Anthropic fallback. Malformed, refused, empty and truncated provider responses fail safely.
- Authenticated single-run processing supports Vercel's bounded request lifetime while retaining durable database jobs, leases and retries.
- Frontend schedules processing after saved receipts and recovers pending runs on detail reads. Failed scheduling does not replace a saved receipt.
- No production migrations, seeds, record deletion or synthetic policy imports were performed.

## Production deployment verified

- Frontend: https://tento-resident-os.vercel.app
- API: https://tento-resident-api.vercel.app
- API /healthz returns 200 with database and Redis healthy.
- Frontend sign-in returns 200. Anonymous API/proxy requests and invalid tokens return 401; cross-origin session mutations return 403.
- The account owner signed into the actual production frontend. The authorized residence loaded from Supabase.
- Two clearly marked release-validation reports were saved without deleting existing records. Request #2 exercised conservative emergency handling (negated hazard words still trigger deterministic screening); guidance appeared and no one was contacted. Request #3 exercised routine processing: the worker completed one attempt, persisted an OpenAI gpt-4.1-mini intake receipt, extracted plumbing facts, and returned an abstention displayed in the browser.
- Read-only receipt verification confirmed routine run status degraded/result abstained, no error code, one completed model call, zero active policy documents and zero unsupported work orders.
- Production smoke checks pass locally and in GitHub Actions. The scheduled health workflow is active on main and checks every six hours. GitHub notification delivery follows the owner's existing account preferences.
- Protected production recovery returned 200 with processed=false after the queue was drained; unauthenticated recovery returns 401.

## Verification

Final offline suite: 338 passed, 5 skipped (no disposable local integration database configured). Ruff and edited-tooling type checks pass. Project-source mypy passes across 110 files. The standard Python 3.12 GitHub quality gate, including full mypy, passed on Linux. The separate real PostgreSQL integration job also passed. Web typecheck, production build and isolated proxy/dispatch tests pass. Both actual Vercel production builds passed. OpenAPI and shared TypeScript types were regenerated.

Release code was pushed to main as abf14c4. Verified GitHub results:

- [Python quality and PostgreSQL integration](https://github.com/vishalgwu/tento-agents/actions/runs/40114361501): both passed.
- [Node 22 quality](https://github.com/vishalgwu/tento-agents/actions/runs/40114361477): passed.
- [Production health](https://github.com/vishalgwu/tento-agents/actions/runs/40114361553): passed.

The user's local edits to test_org_a_login.py were preserved and were not included in the release commit. No credentials were committed; the staged files were scanned against configured secrets before the push.

## Remaining evidence and account actions

No approved property policy documents are configured. Keep abstention until real versioned property policies and actual in-house capabilities are supplied. No fabricated or synthetic policy import was performed. A policy-backed in-house work order cannot yet be validated.

Supabase backup retention/restore arrangements and OpenAI spend-alert preferences need confirmation by the account owner; those settings are not proven by runtime service credentials. No paid upgrade was purchased.

## Release automation and limitations

See DEPLOYMENT.md. scripts/deploy_vercel.py deploys allowlisted source-only bundles and transfers allowlisted production settings via stdin. The generated cron secret is retained only in the ignored root .env and Vercel. Sensitive environment pulls may return redacted placeholders and must not be used as live credentials. The script never migrates, seeds or resets the database.

Processing is bounded to 180 seconds, with a 300-second function/lease and at most three attempts. Frontend after() performs the initial call; pending detail reads recover eligible interrupted work. Daily cron recovers at most one job for the configured organization. Hobby hosting does not provide an always-running worker or immediate unattended retry SLA. The existing container worker remains available if those guarantees become necessary.
