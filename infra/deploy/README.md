# Deployment baseline

The public API is deployed to Cloud Run. The Next.js application is deployed
separately from `apps/web` to Vercel. This is intentionally not a complete
production release procedure: browser authentication, secret ownership,
database migration rollout, and outbound-transport verification still require
their own reviewed release steps.

## API deployment

The deployment script builds a Git-revision-tagged image through Cloud Build,
then deploys only `resident-os-api`. It sets one minimum API instance and leaves
CPU allocated between requests, avoiding a cold start for the review path. It
does not deploy workers, MCP adapters, or observability services. Any later
service for those roles must use its own reviewed deployment with zero minimum
instances.

Create an Artifact Registry Docker repository in the target region, create a
runtime service account with only the runtime permissions it needs, and add two
Secret Manager secrets containing the full connection values:

- `DATABASE_URL`
- `REDIS_URL`

From the repository root, run the following with real project and secret names:

```powershell
.\infra\deploy\deploy-api.ps1 `
  -ProjectId "YOUR_PROJECT" `
  -Region "us-central1" `
  -ArtifactRepository "resident-os" `
  -RuntimeServiceAccount "resident-os-api@YOUR_PROJECT.iam.gserviceaccount.com" `
  -DatabaseUrlSecret "resident-os-database-url" `
  -RedisUrlSecret "resident-os-redis-url"
```

The script never passes connection values as command-line flags: it binds the
named secrets to `DATABASE_URL` and `REDIS_URL` at the service level. It uses
`--update-env-vars` and `--update-secrets` so unrelated service configuration
is retained.

`DEMO_MODE=true` is set both in the image and in every deployment. Do not change
the script to disable demo mode until a documented verification has shown every
outbound notification, vendor, and property-management transport is blocked.

## Rollback

After identifying a previously healthy Cloud Run revision, shift traffic back to
it with `gcloud run services update-traffic`. Keep demo mode enabled during a
rollback as well.
