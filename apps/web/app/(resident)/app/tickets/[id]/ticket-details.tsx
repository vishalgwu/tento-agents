"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { PageFrame } from "@/components/page-frame";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { isTicket, requestError, statusLabel, type Ticket } from "@/lib/tickets";

const factLabels = {
  intent: "Request type", category: "Category", symptom_summary: "Issue summary",
  affected_asset: "Affected item", access_permission: "Entry permitted", pets_present: "Pets present",
};
function Assessment({ result }: { result: Record<string, unknown> }) {
  const facts = result.facts && typeof result.facts === "object" ? result.facts as Record<string, unknown> : {};
  const decision = result.decision && typeof result.decision === "object" ? result.decision as Record<string, unknown> : {};
  const workOrder = result.work_order && typeof result.work_order === "object" ? result.work_order as Record<string, unknown> : {};
  return <>
    {typeof result.summary === "string" ? <p className="whitespace-pre-wrap break-words leading-7">{result.summary}</p> : null}
    {typeof workOrder.id === "string" ? <section className="mt-5 rounded-xl border p-4"><h3 className="font-medium">Internal work order created</h3><p className="mt-2">{typeof workOrder.scope_summary === "string" ? workOrder.scope_summary : "Your property team has a saved maintenance work order."}</p><p className="mt-2 text-sm text-muted-foreground">Awaiting internal assignment. No visit has been scheduled and no vendor has been contacted.</p><p className="mt-2 break-all text-xs text-muted-foreground">Work order: {workOrder.id}</p></section> : null}
    <dl className="mt-4 grid gap-4 sm:grid-cols-2">
      {Object.entries(factLabels).map(([key, label]) => {
        const value = facts[key];
        return typeof value === "string" || typeof value === "boolean" ? <div key={key}><dt className="text-sm text-muted-foreground">{label}</dt><dd className="mt-1 break-words">{typeof value === "boolean" ? value ? "Yes" : "No" : value}</dd></div> : null;
      })}
    </dl>
    {typeof decision.rationale === "string" && decision.rationale !== result.summary ? <p className="mt-5 whitespace-pre-wrap break-words leading-7">{decision.rationale}</p> : null}
  </>;
}

export function TicketDetails({ id }: { id: string }) {
  const [ticket, setTicket] = useState<Ticket | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(true);
  const [revision, setRevision] = useState(0);
  useEffect(() => {
    const controller = new AbortController();
    let timer: ReturnType<typeof setTimeout> | undefined;
    async function load() {
      try {
        const response = await fetch(`/api/tickets/${encodeURIComponent(id)}`, { signal: controller.signal, cache: "no-store" });
        if (!response.ok) throw new Error(requestError(response.status));
        const body: unknown = await response.json();
        if (!isTicket(body)) throw new Error("The service returned an unexpected response.");
        if (controller.signal.aborted) return;
        setTicket(body);
        setError(null);
        if (body.latest_run && ["queued", "running"].includes(body.latest_run.status)) timer = setTimeout(load, 3000);
      } catch (failure) {
        if (!controller.signal.aborted) setError(failure instanceof Error ? failure.message : "Unable to load your request.");
      } finally {
        if (!controller.signal.aborted) setBusy(false);
      }
    }
    setBusy(true);
    void load();
    return () => { controller.abort(); if (timer) clearTimeout(timer); };
  }, [id, revision]);

  const pending = ticket?.latest_run && ["queued", "running"].includes(ticket.latest_run.status);
  return (
    <PageFrame eyebrow="Maintenance request" title={ticket ? `Request #${ticket.ticket_number}` : "Your maintenance request"} description="The current status comes directly from your property's maintenance system.">
      <div className="mb-6 flex flex-wrap gap-3">
        <Button render={<Link href="/app/tickets" />} variant="outline">All requests</Button>
        <Button disabled={busy} variant="outline" onClick={() => setRevision((value) => value + 1)}>Refresh status</Button>
      </div>
      {error ? <p role="alert" className="mb-5 text-destructive">{error} <Link href="/resident/sign-in" className="underline">Sign in</Link></p> : null}
      {ticket?.priority === "p0" ? (
        <section role="alert" className="mb-5 rounded-xl border border-destructive bg-destructive/5 p-4">
          <h2 className="font-semibold">Urgent safety guidance</h2>
          <p className="mt-2 leading-7">This report may describe an emergency. Move to safety and contact emergency services or your property emergency maintenance number. This service has not contacted anyone.</p>
        </section>
      ) : null}
      {busy ? <p role="status">Loading request...</p> : null}
      {ticket ? <div className="grid gap-5">
        <Card><CardContent className="py-5"><dl className="grid gap-4 sm:grid-cols-3"><div><dt className="text-sm text-muted-foreground">Status</dt><dd className="mt-1 font-medium">{statusLabel(ticket.status)}</dd></div><div><dt className="text-sm text-muted-foreground">Priority</dt><dd className="mt-1">{ticket.priority ? ticket.priority.toUpperCase() : "Being assessed"}</dd></div><div><dt className="text-sm text-muted-foreground">Submitted</dt><dd className="mt-1">{new Date(ticket.submitted_at).toLocaleString()}</dd></div></dl></CardContent></Card>
        <Card><CardHeader><CardTitle>Assessment</CardTitle></CardHeader><CardContent aria-live="polite">
          {pending ? <p role="status">Your report is {ticket.latest_run?.status === "queued" ? "waiting to be assessed" : "being assessed"}. This page updates automatically.</p> : null}
          {ticket.latest_run?.result ? <Assessment result={ticket.latest_run.result} /> : null}
          {!pending && !ticket.latest_run?.result ? <p className="text-muted-foreground">An assessment is not available yet. Your report remains saved. Contact your property team if you need help.</p> : null}
          {ticket.latest_run && ["failed", "degraded", "cancelled"].includes(ticket.latest_run.status) ? <p className="mt-4 text-muted-foreground">The assistant could not complete every step. Your report is saved; contact your property team for the next steps.</p> : null}
        </CardContent></Card>
      </div> : null}
    </PageFrame>
  );
}
