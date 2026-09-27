[CmdletBinding()]
param(
    [Parameter(Mandatory)]
    [ValidateNotNullOrEmpty()]
    [string]$ProjectId,

    [Parameter(Mandatory)]
    [ValidateNotNullOrEmpty()]
    [string]$Region,

    [Parameter(Mandatory)]
    [ValidateNotNullOrEmpty()]
    [string]$ArtifactRepository,

    [Parameter(Mandatory)]
    [ValidateNotNullOrEmpty()]
    [string]$RuntimeServiceAccount,

    [Parameter(Mandatory)]
    [ValidateNotNullOrEmpty()]
    [string]$DatabaseUrlSecret,

    [Parameter(Mandatory)]
    [ValidateNotNullOrEmpty()]
    [string]$RedisUrlSecret,

    [ValidatePattern("^[a-z]([-a-z0-9]*[a-z0-9])?$")]
    [string]$ServiceName = "resident-os-api",

    [ValidatePattern("^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")]
    [string]$ImageTag = ""
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Invoke-Gcloud {
    param([Parameter(Mandatory)][string[]]$Arguments)

    & gcloud @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "gcloud $($Arguments -join ' ') failed with exit code $LASTEXITCODE."
    }
}

if (-not (Get-Command gcloud -ErrorAction SilentlyContinue)) {
    throw "Google Cloud CLI is required. Install it and authenticate before deploying."
}

if ([string]::IsNullOrWhiteSpace($ImageTag)) {
    $ImageTag = (& git rev-parse --short=12 HEAD).Trim()
    if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace($ImageTag)) {
        throw "ImageTag was not supplied and the current Git revision could not be resolved."
    }
}

$image = "$Region-docker.pkg.dev/$ProjectId/$ArtifactRepository/$ServiceName`:$ImageTag"
$secretBindings = @(
    "DATABASE_URL=$DatabaseUrlSecret`:latest",
    "REDIS_URL=$RedisUrlSecret`:latest"
) -join ","

Invoke-Gcloud @(
    "artifacts", "repositories", "describe", $ArtifactRepository,
    "--project", $ProjectId,
    "--location", $Region
)

Invoke-Gcloud @(
    "builds", "submit", ".",
    "--project", $ProjectId,
    "--region", $Region,
    "--config", "infra/deploy/cloudbuild.api.yaml",
    "--substitutions", "_IMAGE=$image"
)

# This script deploys only the public API. Future worker, MCP, and observability
# services require their own reviewed deployment with --min-instances 0.
Invoke-Gcloud @(
    "run", "deploy", $ServiceName,
    "--image", $image,
    "--project", $ProjectId,
    "--region", $Region,
    "--platform", "managed",
    "--service-account", $RuntimeServiceAccount,
    "--allow-unauthenticated",
    "--port", "8080",
    "--min-instances", "1",
    "--max-instances", "5",
    "--cpu", "1",
    "--memory", "1Gi",
    "--concurrency", "80",
    "--timeout", "60s",
    "--no-cpu-throttling",
    "--update-env-vars", "DEMO_MODE=true,API_RATE_LIMIT_REQUESTS=120,API_RATE_LIMIT_WINDOW_SECONDS=60",
    "--update-secrets", $secretBindings
)
