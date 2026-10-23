# Container deployment

The FastAPI API runs on a persistent container host. The Next.js application runs on Vercel. Follow [the complete local and deployment guide](../../docs/DEPLOYMENT.md) for authentication, database roles, migrations, environment variables, Vercel configuration, and smoke tests.

The optional Cloud Run script builds from the repository root and deploys only the public API. Create an Artifact Registry repository, a runtime service account, and Secret Manager secrets for DATABASE_URL, REDIS_URL, and ANTHROPIC_API_KEY. Grant the runtime account access to those named secrets. Set SupabaseUrl to the authentication project and AnthropicModel to the model available to your provider account.

```powershell
.\infra\deploy\deploy-api.ps1 `
  -ProjectId "YOUR_PROJECT" `
  -Region "us-central1" `
  -ArtifactRepository "resident-os" `
  -RuntimeServiceAccount "resident-os-api@YOUR_PROJECT.iam.gserviceaccount.com" `
  -DatabaseUrlSecret "resident-os-database-url" `
  -RedisUrlSecret "resident-os-redis-url" `
  -AnthropicApiKeySecret "resident-os-anthropic-api-key" `
  -SupabaseUrl "https://YOUR_PROJECT.supabase.co" `
  -AnthropicModel "YOUR_MODEL_ID"
```

Secret values remain in Secret Manager; command arguments contain only secret resource names. The script preserves unrelated service settings, sets a 60-second request timeout, and maintains one warm API instance. Set any additional backend settings listed in .env.example through your hosting environment. DEMO_MODE stays enabled because the public MVP produces intake results and emergency guidance without external operational effects.

Before applying migrations to an existing database, take a backup and test migration 0004 on a disposable copy. It permanently removes obsolete workflow tables and rewrites historical operational states. A fresh database uses all migrations in filename order. Do not rerun the initial schema against a populated database.

For application rollback, shift Cloud Run traffic to the previous healthy revision. Database deletion requires restoring the backup; application rollback does not recover removed rows.
