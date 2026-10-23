"""Exercise web proxies against an isolated, explicit upstream test double.

Run from any directory with Python 3.12 after installing web dependencies.
This checks HTTP contracts and cookie protections, not a live Supabase/database.
"""
from __future__ import annotations

import http.cookiejar
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.error import HTTPError, URLError
from urllib.request import HTTPCookieProcessor, Request, build_opener

WEB = Path(__file__).resolve().parents[1]
TICKET = "11111111-1111-4111-8111-111111111111"
TENANCY = "22222222-2222-4222-8222-222222222222"
RUN = "33333333-3333-4333-8333-333333333333"
KEY = "44444444-4444-4444-8444-444444444444"
TOKEN = "isolated-test-user-token"


def free_port() -> int:
    with socket.socket() as connection:
        connection.bind(("127.0.0.1", 0))
        return int(connection.getsockname()[1])


class Upstream(BaseHTTPRequestHandler):
    keys: list[str] = []

    def log_message(self, *_args: object) -> None:
        pass

    def send_json(self, value: object, status: int = 200) -> None:
        data = json.dumps(value).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_POST(self) -> None:
        body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", "0"))))
        if self.path.startswith("/auth/v1/token"):
            assert body == {"email": "resident@example.test", "password": "test-password"}
            return self.send_json({"access_token": TOKEN, "expires_in": 3600})
        assert self.headers.get("Authorization") == f"Bearer {TOKEN}"
        assert self.path == "/v1/tickets"
        assert body == {"description": "Kitchen tap is dripping", "tenancy_id": TENANCY, "access_permission": False, "pets_present": True}
        key = self.headers.get("Idempotency-Key")
        assert key == KEY
        self.keys.append(key)
        return self.send_json({"ticket_id": TICKET, "ticket_number": 42, "run_id": RUN, "status": "queued", "emergency": False, "message": None}, 201)

    def do_GET(self) -> None:
        assert self.headers.get("Authorization") == f"Bearer {TOKEN}"
        if self.path == "/v1/tenancies":
            return self.send_json({"items": [{"id": TENANCY, "property_name": "Test property", "unit_name": "101"}]})
        ticket = {"id": TICKET, "ticket_number": 42, "status": "diagnosed", "priority": "p2", "category": "plumbing", "symptom_summary": "Dripping tap", "submitted_at": "2026-10-23T00:00:00Z", "latest_run": {"run_id": RUN, "status": "completed", "result": {"summary": "Plumbing assessment complete", "facts": {"category": "plumbing"}}, "error_code": None}}
        if self.path.startswith("/v1/tickets?"):
            return self.send_json({"items": [ticket], "next_cursor": None})
        assert self.path == f"/v1/tickets/{TICKET}"
        return self.send_json(ticket)


def main() -> None:
    port = free_port()
    upstream = ThreadingHTTPServer(("127.0.0.1", 0), Upstream)
    threading.Thread(target=upstream.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{port}"
    backend = f"http://127.0.0.1:{upstream.server_port}"
    env = {**os.environ, "API_BASE_URL": backend, "SUPABASE_URL": backend, "SUPABASE_ANON_KEY": "isolated-public-test-key", "NEXT_TELEMETRY_DISABLED": "1"}
    node = shutil.which("node")
    if not node:
        raise RuntimeError("Node.js is required")
    next_script = (WEB / "node_modules/next/dist/bin/next").resolve()
    process = subprocess.Popen([node, str(next_script), "dev", "--hostname", "127.0.0.1", "--port", str(port)], cwd=WEB, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    client = build_opener(HTTPCookieProcessor(http.cookiejar.CookieJar()))

    def call(path: str, expected: int, payload: object = None, method: str | None = None, origin: str | None = base, key: str | None = None) -> object:
        headers = {"Content-Type": "application/json"}
        if origin is not None:
            headers["Origin"] = origin
        if key:
            headers["Idempotency-Key"] = key
        request = Request(base + path, data=json.dumps(payload).encode() if payload is not None else None, headers=headers, method=method)
        try:
            response = client.open(request, timeout=60)
        except HTTPError as error:
            response = error
        with response:
            assert response.status == expected, (path, response.status, expected)
            result = json.loads(response.read())
            if path.startswith("/api/"):
                assert response.headers.get("Cache-Control") == "no-store"
            return result

    try:
        deadline = time.monotonic() + 60
        while True:
            try:
                call("/api/tickets", 401)
                break
            except URLError:
                if time.monotonic() >= deadline or process.poll() is not None:
                    raise RuntimeError("Next.js test server did not start") from None
                time.sleep(0.2)
        call("/api/tickets", 403, {}, "POST", origin="https://foreign.example", key=KEY)
        call("/api/session", 200, {"email": "resident@example.test", "password": "test-password"}, "POST")
        tenancies = call("/api/tenancies", 200)
        assert isinstance(tenancies, dict) and tenancies["items"][0]["id"] == TENANCY
        payload = {"description": "Kitchen tap is dripping", "tenancy_id": TENANCY, "access_permission": False, "pets_present": True}
        first = call("/api/tickets", 201, payload, "POST", key=KEY)
        second = call("/api/tickets", 201, payload, "POST", key=KEY)
        assert first == second and Upstream.keys == [KEY, KEY]
        history = call("/api/tickets", 200)
        assert isinstance(history, dict) and history["items"][0]["ticket_number"] == 42
        detail = call(f"/api/tickets/{TICKET}", 200)
        assert isinstance(detail, dict) and detail["latest_run"]["result"]["summary"] == "Plumbing assessment complete"
        call("/api/tickets", 400, {**payload, "access_permission": "yes"}, "POST", key=KEY)
        call("/api/session", 200, method="DELETE")
        call("/api/tickets", 401)
        print("PASS: sign-in cookie, permitted residences, persistent submission proxy, stable retry key, history/detail result, validation, cross-origin denial, sign-out")
    finally:
        process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()
        upstream.shutdown()
        upstream.server_close()


if __name__ == "__main__":
    main()
