import type { components } from "@resident-os/shared-types";

export type Run = components["schemas"]["RunSnapshot"];
export type Ticket = Pick<components["schemas"]["TicketSummary"],
  "id" | "ticket_number" | "status" | "priority" | "category" | "symptom_summary" | "submitted_at" | "latest_run"
>;
function isRun(value: unknown): value is Run {
  if (!value || typeof value !== "object") return false;
  const run = value as Record<string, unknown>;
  return typeof run.run_id === "string" && typeof run.status === "string" &&
    (run.result === null || (typeof run.result === "object" && !Array.isArray(run.result))) &&
    (run.error_code === null || typeof run.error_code === "string");
}
export function isTicket(value: unknown): value is Ticket {
  if (!value || typeof value !== "object") return false;
  const item = value as Record<string, unknown>;
  return typeof item.id === "string" && typeof item.ticket_number === "number" &&
    typeof item.status === "string" && typeof item.submitted_at === "string" &&
    (item.priority === null || typeof item.priority === "string") &&
    (item.category === null || typeof item.category === "string") &&
    (item.symptom_summary === null || typeof item.symptom_summary === "string") &&
    (item.latest_run === undefined || item.latest_run === null || isRun(item.latest_run));
}
export function statusLabel(status: string): string {
  return status.replaceAll("_", " ").replace(/^./, (letter) => letter.toUpperCase());
}
export function requestError(status: number): string {
  return status === 401 ? "Your session has expired. Sign in to continue."
    : status === 403 ? "Your account cannot access this request. Contact your property team."
    : status === 404 ? "This maintenance request could not be found."
    : status === 429 ? "Too many requests. Please try again shortly."
    : "The service is unavailable. Please try again.";
}
