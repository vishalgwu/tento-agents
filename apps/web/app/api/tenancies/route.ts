import { backendRequest } from "@/lib/backend-proxy";
export const runtime = "nodejs";
export const maxDuration = 30;
export async function GET() { return backendRequest("/v1/tenancies"); }
