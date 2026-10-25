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
from uuid import UUID
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
    role = "resident"
    keys: list[str] = []
    dispatch_keys: list[str] = []
    run_status = "completed"
    dispatch_status = 503

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
        if self.path == f"/v1/runs/{RUN}/process":
            assert body == {}
            key = self.headers.get("Idempotency-Key")
            assert key is not None and UUID(key).version == 4
            self.dispatch_keys.append(key)
            return self.send_json({"run_id": RUN, "processed": False}, self.dispatch_status)
        if self.path == "/v1/demo/run":
            assert body == {"description": "cabinet hinge"}
            assert UUID(self.headers["Idempotency-Key"]).version == 4
            return self.send_json({"synthetic": True, "status": "completed", "summary": "Demo only", "citations": [], "trace": []})
        assert self.path == "/v1/tickets"
        assert body == {"description": "Kitchen tap is dripping", "tenancy_id": TENANCY, "access_permission": False, "pets_present": True}
        key = self.headers.get("Idempotency-Key")
        assert key == KEY
        self.keys.append(key)
        return self.send_json({"ticket_id": TICKET, "ticket_number": 42, "run_id": RUN, "status": "queued", "emergency": False, "message": None}, 201)

    def do_GET(self) -> None:
        if self.path == "/healthz":
            return self.send_json({"status": "ok", "components": {"database": "ok", "redis": "ok"}})
        assert self.headers.get("Authorization") == f"Bearer {TOKEN}"
        if self.path == "/v1/me":
            return self.send_json({"org_id": TENANCY, "person_id": TICKET, "role": self.role})
        if self.path == "/v1/tenancies":
            return self.send_json({"items": [{"id": TENANCY, "property_name": "Test property", "unit_name": "101"}]})
        ticket = {"id": TICKET, "ticket_number": 42, "status": "diagnosed", "priority": "p2", "category": "plumbing", "symptom_summary": "Dripping tap", "submitted_at": "2026-10-23T00:00:00Z", "latest_run": {"run_id": RUN, "status": self.run_status, "result": {"summary": "Plumbing assessment complete", "facts": {"category": "plumbing"}}, "error_code": None}}
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
        call("/api/demo", 401, {"description": "cabinet hinge"}, "POST")
        call("/api/demo", 403, {"description": "cabinet hinge"}, "POST", origin="https://foreign.example")
        call("/api/tickets", 403, {}, "POST", origin="https://foreign.example", key=KEY)
        login = call("/api/session", 200, {"email": "resident@example.test", "password": "test-password", "workspace": "resident"}, "POST")
        assert isinstance(login, dict) and login["destination"] == "/app/report"
        call("/api/session", 403, {"email": "resident@example.test", "password": "test-password", "workspace": "admin"}, "POST")
        call("/api/session", 403, {"email": "resident@example.test", "password": "test-password", "workspace": "owner"}, "POST")
        forged = call("/api/session", 200, {"email": "resident@example.test", "password": "test-password", "role": "operations_admin"}, "POST")
        assert isinstance(forged, dict) and forged["destination"] == "/app/report", "Client role fields must not grant access"
        with client.open(base + "/admin", timeout=60) as denied:
            assert "/sign-in?workspace=admin" in denied.geturl(), "A resident must not obtain the admin workspace"
        demo = call("/api/demo", 200, {"description": "cabinet hinge"}, "POST")
        assert isinstance(demo, dict) and demo["synthetic"] is True
        call("/api/demo", 400, {"description": " "}, "POST")
        tenancies = call("/api/tenancies", 200)
        assert isinstance(tenancies, dict) and tenancies["items"][0]["id"] == TENANCY
        payload = {"description": "Kitchen tap is dripping", "tenancy_id": TENANCY, "access_permission": False, "pets_present": True}
        first = call("/api/tickets", 201, payload, "POST", key=KEY)
        second = call("/api/tickets", 201, payload, "POST", key=KEY)
        assert first == second and Upstream.keys == [KEY, KEY]
        deadline = time.monotonic() + 10
        while len(Upstream.dispatch_keys) < 2 and time.monotonic() < deadline:
            time.sleep(0.05)
        assert len(Upstream.dispatch_keys) == 2, "Submission must schedule a worker call even when runner fails"
        assert len(set(Upstream.dispatch_keys)) == 2, "Every kick needs a fresh idempotency key"
        Upstream.dispatch_status = 200
        Upstream.run_status = "running"
        call(f"/api/tickets/{TICKET}", 200)
        deadline = time.monotonic() + 10
        while len(Upstream.dispatch_keys) < 3 and time.monotonic() < deadline:
            time.sleep(0.05)
        assert len(Upstream.dispatch_keys) == 3, "Pending detail must trigger lease recovery"
        Upstream.run_status = "completed"
        history = call("/api/tickets", 200)
        assert isinstance(history, dict) and history["items"][0]["ticket_number"] == 42
        detail = call(f"/api/tickets/{TICKET}", 200)
        assert isinstance(detail, dict) and detail["latest_run"]["result"]["summary"] == "Plumbing assessment complete"
        assert len(Upstream.dispatch_keys) == 3, "Terminal detail must not dispatch work"
        call("/api/tickets", 400, {**payload, "access_permission": "yes"}, "POST", key=KEY)
        for role, workspace, destination, heading in (
            ("maintenance_technician", "maintenance", "/maintenance", "Maintenance operations"),
            ("asset_owner", "owner", "/owner", "Property maintenance overview"),
            ("operations_admin", "admin", "/admin", "Application operations"),
        ):
            Upstream.role = role
            login = call("/api/session", 200, {"email": "resident@example.test", "password": "test-password", "workspace": workspace}, "POST")
            assert isinstance(login, dict) and login["destination"] == destination
            with client.open(base + destination, timeout=60) as view:
                assert heading in view.read().decode(), f"Missing verified {workspace} workspace"
        call("/api/session", 200, method="DELETE")
        call("/api/tickets", 401)
        print("PASS: sign-in cookie, permitted residences, persistent submission proxy, stable retry key, history/detail result, validation, cross-origin denial, worker dispatch/recovery/failure isolation, sign-out")
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
