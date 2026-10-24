import { cookies } from "next/headers";
import { redirect } from "next/navigation";
import { SESSION_COOKIE, serviceUrl } from "@/lib/server-api";
import { canEnter, isIdentity, type Workspace } from "@/lib/workspaces";

export async function requireWorkspace(workspace: Workspace) {
  const token = (await cookies()).get(SESSION_COOKIE)?.value;
  if (!token) redirect(`/sign-in?workspace=${workspace}`);
  const api = serviceUrl(process.env.API_BASE_URL);
  if (!api) throw new Error("Workspace service unavailable");
  const response = await fetch(new URL("/v1/me", api), {
    headers: { Authorization: `Bearer ${token}` },
    cache: "no-store",
    redirect: "error",
    signal: AbortSignal.timeout(15000),
  });
  if (response.status === 401) redirect(`/sign-in?workspace=${workspace}`);
  if (!response.ok) throw new Error("Workspace service unavailable");
  const identity: unknown = await response.json();
  if (!isIdentity(identity)) throw new Error("Unable to verify account");
  if (!canEnter(workspace, identity.role))
    redirect(`/sign-in?workspace=${workspace}`);
  return { identity, api, token };
}
