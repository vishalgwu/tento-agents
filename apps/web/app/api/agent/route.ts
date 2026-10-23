import { randomUUID } from "node:crypto";
import { cookies } from "next/headers";
import { NextResponse } from "next/server";
import { SESSION_COOKIE, problem, sameOrigin, serviceUrl } from "@/lib/server-api";

export const runtime = "nodejs";
export const maxDuration = 60;

export async function POST(request: Request) {
  if (!sameOrigin(request)) return problem(403, "Invalid request origin");
  const token = (await cookies()).get(SESSION_COOKIE)?.value;
  if (!token) return problem(401, "Sign in to continue");
  const endpoint = serviceUrl(process.env.API_BASE_URL);
  if (!endpoint) return problem(503, "Assistant unavailable");

  try {
    const raw = await request.text();
    if (raw.length > 100000) return problem(413, "Request too large");
    const body: unknown = JSON.parse(raw);
    if (
      !body || typeof body !== "object" || !("description" in body) ||
      typeof body.description !== "string" || !body.description.trim() ||
      body.description.length > 20000
    ) return problem(400, "A description of up to 20000 characters is required");

    const response = await fetch(new URL("/v1/agent/run", endpoint), {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Authorization: `Bearer ${token}`,
        "Idempotency-Key": randomUUID(),
      },
      body: JSON.stringify({ description: body.description.trim() }),
      cache: "no-store",
      signal: AbortSignal.timeout(50000),
      redirect: "error",
    });
    if (!response.ok) {
      const status = [400, 401, 403, 413, 422, 429, 503, 504].includes(response.status)
        ? response.status : 502;
      return problem(status, "Assistant request failed");
    }
    return NextResponse.json(await response.json(), {
      headers: { "Cache-Control": "no-store" },
    });
  } catch (error) {
    const status = error instanceof SyntaxError ? 400
      : error instanceof Error && ["TimeoutError", "AbortError"].includes(error.name) ? 504 : 502;
    return problem(status, "Assistant unavailable");
  }
}
