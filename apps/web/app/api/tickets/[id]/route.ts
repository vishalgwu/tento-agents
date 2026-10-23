import { backendRequest } from "@/lib/backend-proxy";
import { problem } from "@/lib/server-api";
export const runtime = "nodejs";
export const maxDuration = 30;
export async function GET(_request: Request, { params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  if (!/^[0-9a-f-]{36}$/i.test(id)) return problem(404, "Ticket not found");
  return backendRequest(`/v1/tickets/${encodeURIComponent(id)}`);
}
