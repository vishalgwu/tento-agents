import Link from "next/link";
import { PageFrame } from "@/components/page-frame";
import { requireWorkspace } from "@/lib/workspace-session";
import { workspaces, type Workspace } from "@/lib/workspaces";
import { isTicket, statusLabel } from "@/lib/tickets";

export async function WorkspaceBoard({
  workspace,
}: {
  workspace: Exclude<Workspace, "resident">;
}) {
  const { identity, api, token } = await requireWorkspace(workspace);
  const response = await fetch(new URL("/v1/tickets?limit=50", api), {
    headers: { Authorization: `Bearer ${token}` },
    cache: "no-store",
    redirect: "error",
    signal: AbortSignal.timeout(15000),
  });
  const payload: unknown = response.ok ? await response.json() : null;
  const page =
    payload && typeof payload === "object"
      ? (payload as Record<string, unknown>)
      : null;
  const items = page && Array.isArray(page.items) ? page.items : null;
  const valid = items !== null && items.every(isTicket);
  const tickets = valid ? items.filter(isTicket) : [];
  let readiness: string | null = null;
  if (workspace === "admin") {
    try {
      const health = await fetch(new URL("/healthz", api), {
        cache: "no-store",
        signal: AbortSignal.timeout(10000),
      });
      readiness = health.ok
        ? "Database and Redis responding"
        : "Service needs attention";
    } catch {
      readiness = "Service check unavailable";
    }
  }
  return (
    <PageFrame
      eyebrow={`${workspaces[workspace].name} workspace`}
      title={
        workspace === "maintenance"
          ? "Maintenance operations"
          : workspace === "owner"
            ? "Property maintenance overview"
            : "Application operations"
      }
      description={workspaces[workspace].description}
    >
      <div className="workspace-identity">
        <div>
          <p className="eyebrow">Verified account role</p>
          <p className="role-name">{statusLabel(identity.role)}</p>
        </div>
        <Link href="/#workspaces" className="text-link">
          All workspaces ↗
        </Link>
      </div>
      {valid && (
        <dl className="workspace-stats">
          <div className="workspace-stat">
            <dt>Visible requests</dt>
            <dd>{tickets.length}</dd>
            <small>IN THIS AUTHORIZED VIEW</small>
          </div>
          <div className="workspace-stat">
            <dt>Active assessments</dt>
            <dd>
              {
                tickets.filter((ticket) =>
                  ["queued", "running"].includes(
                    ticket.latest_run?.status ?? "",
                  ),
                ).length
              }
            </dd>
            <small>QUEUED OR RUNNING</small>
          </div>
          <div className="workspace-stat">
            <dt>Needs attention</dt>
            <dd>
              {
                tickets.filter((ticket) =>
                  ["blocked", "escalated", "failed"].includes(ticket.status),
                ).length
              }
            </dd>
            <small>BASED ON SAVED STATUS</small>
          </div>
        </dl>
      )}
      {readiness && (
        <p className="mb-6 rounded-xl border bg-card p-5">
          {readiness}. Agent outcomes are recorded below; credentials are never
          displayed.
        </p>
      )}
      {!valid ? (
        <p role="alert" className="rounded-xl border p-6">
          Requests could not be loaded. Refresh this page to retry. No sample
          data is shown.
        </p>
      ) : (
        <>
          <div className="mb-6 flex items-end justify-between gap-4">
            <div>
              <h2 className="text-xl font-medium">
                {workspace === "owner"
                  ? "Current maintenance requests"
                  : "Request queue"}
              </h2>
              <p className="mt-2 text-sm text-muted-foreground">
                Latest {tickets.length} authorized requests
                {page?.next_cursor
                  ? "; more are available in request history"
                  : ""}
                . Read-only view of saved records.
              </p>
            </div>
            <Link href="/app/tickets" className="shrink-0 text-sm underline">
              Request history
            </Link>
          </div>
          {tickets.length === 0 ? (
            <p className="rounded-xl border bg-card p-8">
              No requests are visible to this account yet.
            </p>
          ) : (
            <div className="grid gap-3">
              {tickets.map((ticket) => (
                <Link
                  key={ticket.id}
                  href={`/app/tickets/${ticket.id}`}
                  className="ticket-card grid gap-3 rounded-xl border bg-card p-5 transition-colors hover:border-primary focus-visible:outline-2 focus-visible:outline-primary sm:grid-cols-[1fr_auto]"
                >
                  <div>
                    <h3 className="font-medium">
                      Request #{ticket.ticket_number}
                      {ticket.category ? ` / ${ticket.category}` : ""}
                    </h3>
                    <p className="mt-2 text-sm text-muted-foreground">
                      {ticket.symptom_summary ||
                        "Assessment has not supplied a summary yet."}
                    </p>
                  </div>
                  <div className="text-sm sm:text-right">
                    <p
                      className={`ticket-status ${["blocked", "escalated", "failed"].includes(ticket.status) ? "ticket-status--attention" : ""}`}
                    >
                      {statusLabel(ticket.status)}
                    </p>
                    <p className="mt-2 text-muted-foreground">
                      Agent:{" "}
                      {ticket.latest_run
                        ? statusLabel(ticket.latest_run.status)
                        : "No recorded run"}
                    </p>
                    {workspace === "admin" && ticket.latest_run?.error_code && (
                      <p className="mt-2 text-destructive">
                        {ticket.latest_run.error_code}
                      </p>
                    )}
                  </div>
                </Link>
              ))}
            </div>
          )}
        </>
      )}
      <p className="mt-8 text-sm leading-6 text-muted-foreground">
        {workspace === "maintenance"
          ? "This workspace displays saved assessments. Assignment, repair updates and vendor scheduling are not implemented."
          : workspace === "owner"
            ? "This overview shows authorized maintenance records. Financial reporting and portfolio administration are not implemented."
            : "This workspace is restricted to operations administrators in their organization. User provisioning, policy import and secret management remain controlled server-side operations."}
      </p>
    </PageFrame>
  );
}
