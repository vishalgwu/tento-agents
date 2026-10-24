"""Public production smoke checks; no credentials or resident data required."""

from __future__ import annotations

import argparse
import json
from urllib.error import HTTPError
from urllib.request import Request, urlopen


def check(url: str, expected: int, *, origin: str | None = None) -> bytes:
    headers = {"Origin": origin, "Content-Type": "application/json"} if origin else {}
    request = Request(url, data=b"{}" if origin else None, headers=headers)
    try:
        with urlopen(request, timeout=45) as response:
            status, body = response.status, response.read()
    except HTTPError as error:
        status, body = error.code, error.read()
    if status != expected:
        raise RuntimeError(
            f"Production check failed: expected HTTP {expected}, received {status}"
        )
    return body


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--api", default="https://tento-resident-api.vercel.app")
    parser.add_argument("--web", default="https://tento-resident-os.vercel.app")
    args = parser.parse_args()
    health = json.loads(check(args.api + "/healthz", 200))
    if health.get("status") != "ok" or health.get("components") != {
        "database": "ok",
        "redis": "ok",
    }:
        raise RuntimeError("Production database or cache is unhealthy")
    check(args.web + "/resident/sign-in", 200)
    check(args.api + "/v1/tickets", 401)
    check(args.web + "/api/tickets", 401)
    check(args.web + "/api/session", 403, origin="https://example.org")
    print(
        "PASS: API/database/Redis health, frontend availability, authentication, same-origin protection"
    )


if __name__ == "__main__":
    main()
