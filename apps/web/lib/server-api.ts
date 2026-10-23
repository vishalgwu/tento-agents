import { NextResponse } from "next/server";

export const SESSION_COOKIE = "resident-session";

export function sameOrigin(request: Request): boolean {
  const origin = request.headers.get("origin");
  const host = request.headers.get("host");
  // Next.js may normalize Request.url to localhost or its internal deployment
  // host. The browser-facing Host remains the correct CSRF boundary.
  return Boolean(host && origin === `${new URL(request.url).protocol}//${host}`);
}

export function problem(status: number, detail: string) {
  return NextResponse.json({ detail }, {
    status,
    headers: { "Cache-Control": "no-store" },
  });
}

export function serviceUrl(value: string | undefined): URL | null {
  try {
    if (!value) return null;
    const url = new URL(value);
    if (url.username || url.password || url.search || url.hash) return null;
    const localHttp = process.env.NODE_ENV !== "production" &&
      url.protocol === "http:" && ["localhost", "127.0.0.1"].includes(url.hostname);
    if (url.protocol !== "https:" && !localHttp) return null;
    return url;
  } catch {
    return null;
  }
}
