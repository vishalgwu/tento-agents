import { cookies } from "next/headers";
import { NextResponse } from "next/server";
import { SESSION_COOKIE, problem, serviceUrl } from "@/lib/server-api";

export async function backendRequest(path: string, options: RequestInit = {}) {
  const token = (await cookies()).get(SESSION_COOKIE)?.value;
  if (!token) return problem(401, "Sign in to continue");
  const endpoint = serviceUrl(process.env.API_BASE_URL);
  if (!endpoint) return problem(503, "Service unavailable");
  try {
    const response = await fetch(new URL(path, endpoint), {
      ...options,
      headers: { ...options.headers, Authorization: `Bearer ${token}` },
      cache: "no-store",
      redirect: "error",
      signal: AbortSignal.timeout(15000),
    });
    if (!response.ok) {
      const status = [400, 401, 403, 404, 409, 413, 422, 429, 503, 504].includes(response.status)
        ? response.status : 502;
      return problem(status, "Request failed");
    }
    return NextResponse.json(await response.json(), {
      status: response.status,
      headers: { "Cache-Control": "no-store" },
    });
  } catch (error) {
    const status = error instanceof Error && ["TimeoutError", "AbortError"].includes(error.name) ? 504 : 502;
    return problem(status, "Service unavailable");
  }
}
