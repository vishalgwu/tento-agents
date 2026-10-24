import { dispatchPendingRun } from "@/lib/run-dispatch";
import { backendRequest } from "@/lib/backend-proxy";
import { problem, sameOrigin } from "@/lib/server-api";
export const runtime = "nodejs";
export const maxDuration = 300;
const uuid = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
export async function GET(request: Request) {
  const query = new URL(request.url).searchParams;
  const cursor = query.get("cursor");
  if (cursor && cursor.length > 512) return problem(400, "Invalid page cursor");
  const params = new URLSearchParams({ limit: "20" });
  if (cursor) params.set("cursor", cursor);
  return backendRequest(`/v1/tickets?${params}`);
}
export async function POST(request: Request) {
  if (!sameOrigin(request)) return problem(403, "Invalid request origin");
  const key = request.headers.get("Idempotency-Key");
  if (!key || !uuid.test(key)) return problem(400, "A request identifier is required");
  try {
    const raw = await request.text();
    if (raw.length > 100000) return problem(413, "Request too large");
    const body: unknown = JSON.parse(raw);
    if (!body || typeof body !== "object" || !("description" in body) || typeof body.description !== "string" || !body.description.trim() || body.description.length > 20000) return problem(400, "A description is required");
    const payload: Record<string, unknown> = { description: body.description.trim() };
    if ("tenancy_id" in body) {
      if (typeof body.tenancy_id !== "string" || !uuid.test(body.tenancy_id)) return problem(400, "Invalid residence");
      payload.tenancy_id = body.tenancy_id;
    }
    const fields = body as Record<string, unknown>;
    for (const field of ["access_permission", "pets_present"] as const) {
      if (field in fields) {
        if (typeof fields[field] !== "boolean") return problem(400, "Invalid access preferences");
        payload[field] = fields[field];
      }
    }
    const response = await backendRequest("/v1/tickets", {
      method: "POST",
      headers: { "Content-Type": "application/json", "Idempotency-Key": key },
      body: JSON.stringify(payload),
    });
    await dispatchPendingRun(response, "submission");
    return response;
  } catch { return problem(400, "Invalid request"); }
}
