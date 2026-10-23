import { NextResponse } from "next/server";
import { SESSION_COOKIE, problem, sameOrigin, serviceUrl } from "@/lib/server-api";

export const runtime = "nodejs";
export const maxDuration = 30;

export async function POST(request: Request) {
  if (!sameOrigin(request)) return problem(403, "Invalid request origin");
  const endpoint = serviceUrl(process.env.SUPABASE_URL);
  const key = process.env.SUPABASE_ANON_KEY;
  if (!endpoint || !key) return problem(503, "Sign-in unavailable");

  try {
    const raw = await request.text();
    if (raw.length > 8192) return problem(413, "Request too large");
    const body: unknown = JSON.parse(raw);
    if (
      !body || typeof body !== "object" || !("email" in body) ||
      typeof body.email !== "string" || !("password" in body) ||
      typeof body.password !== "string" || !body.email.trim() || !body.password
    ) return problem(400, "Email and password required");

    const response = await fetch(new URL("/auth/v1/token?grant_type=password", endpoint), {
      method: "POST",
      headers: { "Content-Type": "application/json", apikey: key },
      body: JSON.stringify({ email: body.email.trim(), password: body.password }),
      signal: AbortSignal.timeout(15000),
      cache: "no-store",
      redirect: "error",
    });
    if (!response.ok) {
      return problem(response.status === 400 || response.status === 401 ? 401 : 503, "Sign-in failed");
    }
    const session = await response.json();
    if (typeof session.access_token !== "string" || typeof session.expires_in !== "number") {
      return problem(503, "Sign-in unavailable");
    }
    const result = NextResponse.json({ authenticated: true }, {
      headers: { "Cache-Control": "no-store" },
    });
    result.cookies.set(SESSION_COOKIE, session.access_token, {
      httpOnly: true,
      secure: process.env.NODE_ENV === "production",
      sameSite: "strict",
      path: "/",
      maxAge: Math.max(1, Math.min(session.expires_in, 3600)),
    });
    return result;
  } catch (error) {
    return problem(error instanceof SyntaxError ? 400 : 503, "Sign-in unavailable");
  }
}

export async function DELETE(request: Request) {
  if (!sameOrigin(request)) return problem(403, "Invalid request origin");
  const result = NextResponse.json({ authenticated: false }, {
    headers: { "Cache-Control": "no-store" },
  });
  result.cookies.set(SESSION_COOKIE, "", {
    httpOnly: true,
    secure: process.env.NODE_ENV === "production",
    sameSite: "strict",
    path: "/",
    maxAge: 0,
  });
  return result;
}
