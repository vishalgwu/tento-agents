# Keys and setup: add these at the end

No paid model key is needed to run automated tests. Until a provider and live policy sources are configured, saved jobs end safely with abstention. No external vendor or notification integration is required: this MVP creates internal work orders only.

## Required service configuration

| Variable | Where | What to supply |
| --- | --- | --- |
| DATABASE_URL | Vercel API | Restricted resident_api PostgreSQL connection, using postgresql+asyncpg:// |
| WORKER_DATABASE_URL | Worker/import job | Restricted resident_worker connection; same database, different permissions |
| REDIS_URL | Vercel API | Upstash TLS Redis connection (rediss://) |
| SUPABASE_URL | API + Vercel | Your Supabase project HTTPS URL |
| SUPABASE_ANON_KEY | Vercel server only | Public anonymous/publishable project key accepted by Supabase Auth |
| SUPABASE_JWT_AUDIENCE | API | Usually authenticated; match your issued token audience |
| OPENAI_API_KEY / OPENAI_MODEL | Vercel API and worker | Existing OpenAI credentials and exact model ID; currently gpt-4.1-mini |
| ANTHROPIC_API_KEY (optional fallback) | Worker; API if using direct analysis | Your provider API key |
| ANTHROPIC_MODEL (optional fallback) | Worker; API if using direct analysis | Exact model ID enabled for your account |
| WORKER_ORG_ID | Optional container worker / daily recovery | The organisation UUID this worker serves; this is an ID, not a secret |
| API_BASE_URL | Vercel server | Public HTTPS origin of the Vercel API |
| MIGRATION_DATABASE_URL | Explicit migration job only | Administrator PostgreSQL connection; never the browser or normal API role |

The API can save reports without a model key. The worker needs the model key and verified policy sources to produce validated plans and internal work orders. One worker serves one configured organisation; deploy another tenant-scoped worker for another organisation.

## Needed only for source importing or optional features

- OPENAI_API_KEY and OPENAI_MODEL: the primary model provider, also used by verified-source importing for embeddings. The production query path uses PostgreSQL lexical retrieval.
- TEST_DATABASE_URL: only for integration tests; must point at a disposable database whose name ends _test.
- VENDOR_LINK_SIGNING_SECRET: only if you enable existing signed vendor-link pages. Vendor operations are outside this MVP.
- R2 settings: only for future media uploads. The current report is text-only.
- GOOGLE_API_KEY and SUPABASE_SERVICE_ROLE_KEY are not required by the current runtime.
- Vercel workspace and local CLI account access is needed to create hosting projects. It is separate from application model keys.

## Supabase membership setup

1. Create a Supabase user with email/password and asymmetric JWT signing.
2. Create matching organisation, property, building, unit, person and current tenancy records in the application database.
3. In the Supabase Auth project SQL editor, install infra/auth/supabase-token-hook.sql, then enable that function under Authentication > Hooks > Custom Access Token.
4. Use the Supabase administrator console or Admin API to set the user's app_metadata.resident_os object to org_id, person_id and app_role (for example resident). These identifiers must match the application database. Never put membership authority in user_metadata.
5. Sign in again. The hook preserves Supabase role=authenticated and adds signed org_id, person_id and app_role claims. The API also accepts the previous custom top-level application role for compatibility.

Example administrator-managed metadata shape (replace IDs; do not use it as ordinary user-editable profile data):

```json
{"resident_os":{"org_id":"YOUR_ORG_UUID","person_id":"YOUR_PERSON_UUID","app_role":"resident"}}
```

No user provisioning is fabricated. An account without valid membership or an active tenancy cannot submit a property report.

## Verified production sources

Do not promote files in knowledge/: they are synthetic fixtures. Supply real versioned property documents with status active, production_eligible true, authority, jurisdiction and effective dates. Import using:

```powershell
$env:PYTHONPATH="services/api/src;services/brain/src"
python -m brain.ingest --org-id YOUR_ORG_UUID --source verified-policy.md --claims policy.json
```

The policy JSON is immutable source configuration: each entry has policy_key, outcome, source_start, source_end and source_text. The exact source_text must equal the character slice in the Markdown. Publish a new source version when the policy changes. These values supply deterministic policy precedence; models cannot invent canonical rules. Configure properties.in_house_trades with the actual in-house capabilities, such as an array containing plumbing. Missing sources or capability cause safe abstention.

See docs/DEPLOYMENT.md for the current Vercel deployment steps. Keep all values in ignored local environment files or host secret settings. Never paste secrets into chat or commit them.
