"""Prepare/deploy two Vercel projects; transfer allowlisted secrets via stdin only.

Run after `npx vercel login`. No migration, fixture import or database reset occurs.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import secrets
from pathlib import Path
import shutil
import subprocess
import sys

from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parents[1]
IGNORE = shutil.ignore_patterns(
    ".env",
    ".env.*",
    "node_modules",
    ".next",
    "__pycache__",
    "*.pyc",
    ".vercel",
    "*.tsbuildinfo",
    ".pytest_cache",
)


def prepare() -> tuple[Path, Path]:
    # Fixed, workspace-contained staging roots. Preserve previous artifacts;
    # never recursively delete a computed directory.
    from datetime import datetime

    base = (
        ROOT / "tmp" / ("vercel-release-" + datetime.now().strftime("%Y%m%d-%H%M%S-%f"))
    )
    api = base / "api"
    web = base / "web"
    api.mkdir(parents=True)
    web.mkdir(parents=True)
    for name in ("api", "brain"):
        shutil.copytree(ROOT / f"services/{name}/src/{name}", api / name, ignore=IGNORE)
    # The Vercel parser requires a standalone dependency input here.
    (api / "requirements.txt").write_text(
        (ROOT / "requirements.runtime.lock.txt").read_text(encoding="utf-8"),
        encoding="utf-8",
        newline="\n",
    )
    (api / "app.py").write_text(
        "from api.main import create_app\n\napp = create_app()\n", encoding="utf-8"
    )
    (api / ".python-version").write_text("3.12\n", encoding="utf-8")
    (api / "vercel.json").write_text(
        json.dumps(
            {
                "$schema": "https://openapi.vercel.sh/vercel.json",
                "functions": {"app.py": {"maxDuration": 300}},
                "crons": [
                    {"path": "/internal/worker/recover", "schedule": "0 3 * * *"}
                ],
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    (api / ".vercelignore").write_text(
        ".env*\n**/__pycache__\n**/tests\n", encoding="utf-8"
    )
    for name in ("package.json", "pnpm-lock.yaml", "pnpm-workspace.yaml"):
        shutil.copy2(ROOT / name, web / name)
    for name in ("apps", "packages"):
        shutil.copytree(ROOT / name, web / name, ignore=IGNORE)
    (web / ".vercelignore").write_text(
        "**/.env*\n**/node_modules\n**/.next\n**/__pycache__\n", encoding="utf-8"
    )
    return api, web


def cli(args: list[str], cwd: Path, value: str | None = None) -> str:
    executable = shutil.which("npx.cmd" if os.name == "nt" else "npx")
    if not executable:
        raise RuntimeError("Node.js/npx is required")
    result = subprocess.run(
        [executable, "--yes", "vercel@65.2.0", *args],
        cwd=cwd,
        input=value,
        text=True,
        capture_output=True,
        check=False,
        env={**os.environ, "VERCEL_TELEMETRY_DISABLED": "1"},
    )
    if result.returncode:
        # CLI output may contain remote configuration. Do not print it.
        raise RuntimeError(
            f"Vercel command {args[0]} failed; check CLI login, workspace access and project permissions"
        )
    return result.stdout.strip()


def project(name: str, path: Path, scope: str, frontend: bool) -> None:
    settings: dict[str, object] = {
        "name": name,
        "framework": "nextjs" if frontend else "fastapi",
        "resourceConfig": {"fluid": True, "functionDefaultTimeout": 300},
    }
    if frontend:
        settings.update(
            rootDirectory="apps/web",
            nodeVersion="22.x",
            sourceFilesOutsideRootDirectory=True,
        )
    else:
        # Public ingress is still JWT-authenticated by FastAPI. Interactive
        # deployment protection would prevent server-to-server worker calls.
        settings["ssoProtection"] = None
    config = path / "project-settings.json"
    config.write_text(json.dumps(settings), encoding="utf-8")
    try:
        cli(["api", f"/v9/projects/{name}", "--method", "GET", "--scope", scope], path)
    except RuntimeError:
        # These settings belong to PATCH; the create-project schema omits them.
        create_settings = {
            key: value
            for key, value in settings.items()
            if key not in {"nodeVersion", "sourceFilesOutsideRootDirectory"}
        }
        config.write_text(json.dumps(create_settings), encoding="utf-8")
        cli(
            [
                "api",
                "/v11/projects",
                "--method",
                "POST",
                "--input",
                str(config),
                "--scope",
                scope,
            ],
            path,
        )
    # Project names are immutable for this release; including the existing name
    # in PATCH can be interpreted as a conflicting rename by the API.
    settings.pop("name")
    config.write_text(json.dumps(settings), encoding="utf-8")
    cli(
        [
            "api",
            f"/v9/projects/{name}",
            "--method",
            "PATCH",
            "--input",
            str(config),
            "--scope",
            scope,
        ],
        path,
    )
    cli(["link", "--yes", "--project", name, "--scope", scope], path)


def upload(path: Path, scope: str, values: dict[str, str]) -> None:
    for key, value in values.items():
        cli(["env", "add", key, "production", "--force", "--scope", scope], path, value)


def deploy(path: Path, scope: str) -> str:
    output = cli(["deploy", "--prod", "--yes", "--scope", scope], path)
    urls = re.findall(r"https://[a-zA-Z0-9.-]+\.vercel\.app\b", output)
    if not urls:
        raise RuntimeError(
            "Deployment succeeded without a recognized Vercel URL; inspect project deployments"
        )
    return urls[-1]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prepare-only", action="store_true")
    parser.add_argument(
        "--scope", help="Your explicitly selected Vercel workspace slug"
    )
    parser.add_argument("--api-project", default="tento-resident-api")
    parser.add_argument("--web-project", default="tento-resident-os")
    parser.add_argument(
        "--api-url", help="Reuse an already deployed, healthy HTTPS API origin"
    )
    args = parser.parse_args()
    api, web = prepare()
    if args.prepare_only:
        print(f"Prepared API: {api}\nPrepared web workspace: {web}")
        return
    if not args.scope:
        parser.error("--scope is required for deployment")
    cli(["whoami"], ROOT)
    raw = dotenv_values(ROOT / ".env")
    required = (
        "DATABASE_URL",
        "WORKER_DATABASE_URL",
        "REDIS_URL",
        "SUPABASE_URL",
        "SUPABASE_ANON_KEY",
        "OPENAI_API_KEY",
        "OPENAI_MODEL",
    )
    missing = [key for key in required if not raw.get(key)]
    if missing:
        raise RuntimeError("Missing configuration names: " + ", ".join(missing))
    api_names = (
        "DATABASE_URL",
        "WORKER_DATABASE_URL",
        "REDIS_URL",
        "SUPABASE_URL",
        "SUPABASE_JWT_AUDIENCE",
        "OPENAI_API_KEY",
        "OPENAI_MODEL",
        "OPENAI_MODEL_SMALL",
        "OPENAI_MODEL_MID",
        "OPENAI_MODEL_LARGE",
        "OPENAI_TEMPERATURE",
        "OPENAI_MAX_OUTPUT_TOKENS",
        "API_RATE_LIMIT_REQUESTS",
        "API_RATE_LIMIT_WINDOW_SECONDS",
        "ANTHROPIC_API_KEY",
        "ANTHROPIC_MODEL",
        "WORKER_ORG_ID",
    )
    api_values = {key: str(raw[key]) for key in api_names if raw.get(key)}
    api_values.update(DEMO_MODE="true", DATABASE_POOL_MODE="null")
    cron_secret = raw.get("CRON_SECRET")
    if not cron_secret:
        cron_secret = secrets.token_urlsafe(48)
        # Preserve the generated credential locally without displaying it.
        # Vercel intentionally redacts sensitive values on subsequent pulls.
        with (ROOT / ".env").open("a", encoding="utf-8") as stream:
            stream.write("\nCRON_SECRET=" + cron_secret + "\n")
    api_values["CRON_SECRET"] = cron_secret
    if args.api_url:
        api_url = args.api_url.rstrip("/")
    else:
        project(args.api_project, api, args.scope, False)
        upload(api, args.scope, api_values)
        api_url = deploy(api, args.scope)
    if not api_url.startswith("https://"):
        raise RuntimeError("API deployment did not return an HTTPS URL")
    import httpx

    response = httpx.get(api_url + "/healthz", timeout=45)
    if response.status_code != 200 or response.json().get("status") != "ok":
        raise RuntimeError("API deployment is not healthy; frontend was not deployed")
    project(args.web_project, web, args.scope, True)
    upload(
        web,
        args.scope,
        {
            "API_BASE_URL": api_url,
            "SUPABASE_URL": str(raw["SUPABASE_URL"]),
            "SUPABASE_ANON_KEY": str(raw["SUPABASE_ANON_KEY"]),
        },
    )
    web_url = deploy(web, args.scope)
    print(f"API health verified: {api_url}/healthz\nFrontend: {web_url}")
    (ROOT / "tmp/vercel-release-result.json").write_text(
        json.dumps({"api": api_url, "web": web_url}, indent=2), encoding="utf-8"
    )


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        # Only our sanitized messages are exposed, never third-party exceptions.
        if isinstance(error, RuntimeError):
            print(str(error), file=sys.stderr)
        else:
            print(
                "Release stopped safely; inspect configuration and account access locally.",
                file=sys.stderr,
            )
        sys.exit(1)
