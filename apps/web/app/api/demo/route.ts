import { randomUUID } from "node:crypto";
import { cookies } from "next/headers";
import { NextResponse } from "next/server";
import {
  SESSION_COOKIE,
  problem,
  sameOrigin,
  serviceUrl,
} from "@/lib/server-api";

export const runtime = "nodejs";
export const maxDuration = 180;

export async function POST(request: Request) {
  if (!sameOrigin(request)) return problem(403, "Invalid request origin");
  const token = (await cookies()).get(SESSION_COOKIE)?.value;
  if (!token) return problem(401, "Sign in to run a live demo");
  const endpoint = serviceUrl(process.env.API_BASE_URL);
  if (!endpoint) return problem(503, "Demo unavailable");
  try {
    const raw = await request.text();
    if (raw.length > 12000) return problem(413, "Request too large");
    const body: unknown = JSON.parse(raw);
    if (
      !body ||
      typeof body !== "object" ||
      !("description" in body) ||
      typeof body.description !== "string" ||
      !body.description.trim() ||
      body.description.length > 2000
    )
      return problem(400, "A demo report is required");
    const response = await fetch(new URL("/v1/demo/run", endpoint), {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Authorization: `Bearer ${token}`,
        "Idempotency-Key": randomUUID(),
      },
      body: JSON.stringify({ description: body.description.trim() }),
      cache: "no-store",
      redirect: "error",
      signal: AbortSignal.timeout(160000),
    });
    if (!response.ok)
      return problem(
        [401, 403, 404, 429, 503, 504].includes(response.status)
          ? response.status
          : 502,
        "Demo request unavailable",
      );
    return NextResponse.json(await response.json(), {
      headers: { "Cache-Control": "no-store" },
    });
  } catch (error) {
    return problem(
      error instanceof SyntaxError ? 400 : 503,
      "Demo request unavailable",
    );
  }
}
