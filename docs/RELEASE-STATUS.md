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
- Production smoke checks pass. The source includes a scheduled GitHub Actions health check every six hours; it becomes active after that workflow is pushed to main. GitHub notification delivery follows the owner's existing account preferences.

## Verification

Final offline suite: 338 passed, 5 skipped (no disposable integration database configured). Ruff passes. Project-source mypy check passes across 110 files with third-party import traversal skipped; focused type checks of edited provider and deployment files also pass. The unmodified full dependency-traversing mypy command stalls in this Windows environment and was interrupted, so a full standard CI type-check result is not claimed. Web typecheck, production build and isolated proxy/dispatch tests pass. Both actual Vercel production builds passed. OpenAPI and shared TypeScript types were regenerated.

## Remaining evidence and account actions

No approved property policy documents are configured. Keep abstention until real versioned property policies and actual in-house capabilities are supplied. No fabricated or synthetic policy import was performed. A policy-backed in-house work order cannot yet be validated.

Supabase backup retention/restore arrangements and OpenAI spend-alert preferences need confirmation by the account owner; those settings are not proven by runtime service credentials. No paid upgrade was purchased.

## Release automation and limitations

See DEPLOYMENT.md. scripts/deploy_vercel.py deploys allowlisted source-only bundles and transfers allowlisted production settings via stdin. The generated cron secret is retained only in the ignored root .env and Vercel. Sensitive environment pulls may return redacted placeholders and must not be used as live credentials. The script never migrates, seeds or resets the database.

Processing is bounded to 180 seconds, with a 300-second function/lease and at most three attempts. Frontend after() performs the initial call; pending detail reads recover eligible interrupted work. Daily cron recovers at most one job for the configured organization. Hobby hosting does not provide an always-running worker or immediate unattended retry SLA. The existing container worker remains available if those guarantees become necessary.
