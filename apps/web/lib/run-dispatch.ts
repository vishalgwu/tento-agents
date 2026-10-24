import { randomUUID } from "node:crypto";
import { cookies } from "next/headers";
import { after } from "next/server";
import { SESSION_COOKIE, serviceUrl } from "@/lib/server-api";

const uuid = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

/** Extend the request lifecycle without delaying a persisted ticket response. */
export async function dispatchPendingRun(response: Response, shape: "submission" | "detail") {
  if (!response.ok) return;
  try {
    const body: unknown = await response.clone().json();
    if (!body || typeof body !== "object") return;
    const value = body as Record<string, unknown>;
    const candidate = shape === "submission" ? value : value.latest_run;
    if (!candidate || typeof candidate !== "object") return;
    const run = candidate as Record<string, unknown>;
    if (typeof run.run_id !== "string" || !uuid.test(run.run_id) ||
      !["queued", "running"].includes(String(run.status))) return;

    // Request cookies must be read before after() leaves the request context.
    const token = (await cookies()).get(SESSION_COOKIE)?.value;
    const endpoint = serviceUrl(process.env.API_BASE_URL);
    if (!token || !endpoint) return;
    const runId = run.run_id;
    after(async () => {
      try {
        const result = await fetch(new URL(`/v1/runs/${runId}/process`, endpoint), {
          method: "POST",
          headers: {
            Authorization: `Bearer ${token}`,
            "Content-Type": "application/json",
            "Idempotency-Key": randomUUID(),
          },
          body: "{}",
          cache: "no-store",
          redirect: "error",
          signal: AbortSignal.timeout(240000),
        });
        if (!result.ok) {
          console.warn("worker_dispatch_failed", { run_id: runId, status: result.status });
        }
        // No resident content or upstream error body is read or logged.
        await result.body?.cancel();
      } catch {
        console.warn("worker_dispatch_unavailable", { run_id: runId });
      }
    });
  } catch {
    // A scheduling failure must not hide or replace an already saved ticket.
    console.warn("worker_dispatch_not_scheduled");
  }
}
