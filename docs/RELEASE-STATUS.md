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
