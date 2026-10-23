"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { PageFrame } from "@/components/page-frame";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { isTicket, requestError, statusLabel, type Ticket } from "@/lib/tickets";

export function TicketHistory() {
  const [tickets, setTickets] = useState<Ticket[]>([]);
  const [cursor, setCursor] = useState<string | null>(null);
  const [busy, setBusy] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [revision, setRevision] = useState(0);

  useEffect(() => {
    const controller = new AbortController();
    async function load() {
      setBusy(true);
      setError(null);
      try {
        const response = await fetch("/api/tickets", { signal: controller.signal, cache: "no-store" });
        if (!response.ok) throw new Error(requestError(response.status));
        const body = await response.json();
        if (!Array.isArray(body.items) || !body.items.every(isTicket)) throw new Error("The service returned an unexpected response.");
        if (controller.signal.aborted) return;
        setTickets(body.items);
        setCursor(typeof body.next_cursor === "string" ? body.next_cursor : null);
      } catch (failure) {
        if (!controller.signal.aborted) setError(failure instanceof Error ? failure.message : "Unable to load your requests.");
      } finally {
        if (!controller.signal.aborted) setBusy(false);
      }
    }
    void load();
    return () => controller.abort();
  }, [revision]);

  async function loadMore() {
    if (!cursor || busy) return;
    setBusy(true);
    setError(null);
    try {
      const response = await fetch(`/api/tickets?cursor=${encodeURIComponent(cursor)}`, { cache: "no-store" });
      if (!response.ok) throw new Error(requestError(response.status));
      const body = await response.json();
      if (!Array.isArray(body.items) || !body.items.every(isTicket)) throw new Error("The service returned an unexpected response.");
      setTickets((current) => {
        const existing = new Set(current.map((ticket) => ticket.id));
        return [...current, ...body.items.filter((ticket: Ticket) => !existing.has(ticket.id))];
      });
      setCursor(typeof body.next_cursor === "string" ? body.next_cursor : null);
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : "Unable to load more requests.");
    } finally { setBusy(false); }
  }

  return (
    <PageFrame eyebrow="Maintenance" title="Your requests" description="Follow the current status and assessment of your maintenance reports.">
      <div className="mb-6 flex flex-wrap gap-3">
        <Button render={<Link href="/app/report" />}>New request</Button>
        <Button disabled={busy} variant="outline" onClick={() => setRevision((value) => value + 1)}>Refresh</Button>
      </div>
      {error ? <p role="alert" className="mb-5 text-destructive">{error} <Link className="underline" href="/resident/sign-in">Sign in</Link></p> : null}
      <div aria-busy={busy} aria-live="polite" className="grid gap-4">
        {!busy && !error && tickets.length === 0 ? <p className="text-muted-foreground">You have no maintenance requests yet.</p> : null}
        {tickets.map((ticket) => (
          <Card key={ticket.id}>
            <CardContent className="py-5">
              <div className="flex flex-wrap items-center justify-between gap-3">
                <Link className="font-medium text-primary underline underline-offset-4" href={`/app/tickets/${ticket.id}`}>Request #{ticket.ticket_number}</Link>
                <span className="rounded-full border px-3 py-1 text-sm">{statusLabel(ticket.status)}</span>
              </div>
              <p className="mt-3 break-words">{ticket.symptom_summary || "Your report is being assessed."}</p>
              <p className="mt-3 text-sm text-muted-foreground">{new Date(ticket.submitted_at).toLocaleString()}{ticket.category ? ` · ${ticket.category}` : ""}</p>
            </CardContent>
          </Card>
        ))}
        {busy ? <p role="status" className="text-muted-foreground">Loading requests...</p> : null}
      </div>
      {cursor ? <Button disabled={busy} onClick={loadMore} variant="outline" className="mt-6">Load more</Button> : null}
    </PageFrame>
  );
}
