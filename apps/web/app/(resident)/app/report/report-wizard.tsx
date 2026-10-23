"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useRef, useState, type FormEvent } from "react";
import { PageFrame } from "@/components/page-frame";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Label } from "@/components/ui/label";
import { requestError } from "@/lib/tickets";

type Tenancy = { id: string; property_name: string; unit_name: string };
type Preference = "unknown" | "yes" | "no";

export function ReportWizard() {
  const router = useRouter();
  const [description, setDescription] = useState("");
  const [tenancies, setTenancies] = useState<Tenancy[]>([]);
  const [tenancy, setTenancy] = useState("");
  const [loading, setLoading] = useState(true);
  const [access, setAccess] = useState<Preference>("unknown");
  const [pets, setPets] = useState<Preference>("unknown");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [emergency, setEmergency] = useState<{ ticketId: string; message: string } | null>(null);
  const request = useRef<{ body: string; key: string } | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    async function load() {
      try {
        const response = await fetch("/api/tenancies", { signal: controller.signal, cache: "no-store" });
        if (!response.ok) throw new Error(requestError(response.status));
        const body = await response.json();
        if (!Array.isArray(body.items) || !body.items.every((item: unknown) => {
          if (!item || typeof item !== "object") return false;
          const value = item as Record<string, unknown>;
          return typeof value.id === "string" && typeof value.property_name === "string" && typeof value.unit_name === "string";
        })) throw new Error("Your residence information could not be loaded.");
        if (controller.signal.aborted) return;
        setTenancies(body.items);
        if (body.items.length === 1) setTenancy(body.items[0].id);
        if (body.items.length === 0) setError("Your account has no active residence. Contact your property team to connect your account.");
      } catch (failure) {
        if (!controller.signal.aborted) setError(failure instanceof Error ? failure.message : "Unable to load your residence.");
      } finally {
        if (!controller.signal.aborted) setLoading(false);
      }
    }
    void load();
    return () => controller.abort();
  }, []);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (busy || emergency || !description.trim() || !tenancy) return;
    setBusy(true);
    setError(null);
    const body = JSON.stringify({
      description: description.trim(),
      tenancy_id: tenancy,
      ...(access !== "unknown" ? { access_permission: access === "yes" } : {}),
      ...(pets !== "unknown" ? { pets_present: pets === "yes" } : {}),
    });
    // Reuse the same identifier after a network failure so a retry cannot
    // create a second ticket for the same submission.
    if (request.current?.body !== body) request.current = { body, key: crypto.randomUUID() };
    try {
      const response = await fetch("/api/tickets", {
        method: "POST",
        headers: { "Content-Type": "application/json", "Idempotency-Key": request.current.key },
        body,
      });
      if (!response.ok) throw new Error(response.status === 409
        ? "Your residence information changed. Reload this page and try again."
        : requestError(response.status));
      const result: unknown = await response.json();
      if (!result || typeof result !== "object" || !("ticket_id" in result) || typeof result.ticket_id !== "string") {
        throw new Error("The request may have been saved. Try again to retrieve the same request, or check Your requests.");
      }
      if ("emergency" in result && result.emergency === true) {
        setEmergency({
          ticketId: result.ticket_id,
          message: "message" in result && typeof result.message === "string" ? result.message
            : "This may be an emergency. Move to safety and contact emergency services or your property emergency maintenance number. This service has not contacted anyone.",
        });
        setBusy(false);
      } else {
        router.push(`/app/tickets/${encodeURIComponent(result.ticket_id)}`);
      }
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : "Unable to send your request. You can safely try again.");
      setBusy(false);
    }
  }

  return (
    <PageFrame eyebrow="Maintenance" title="Report an issue" description="Save your report and follow its assessment and current status.">
      <div className="grid gap-6 lg:grid-cols-[minmax(0,1fr)_20rem]">
        <Card>
          <CardHeader><CardTitle>Your maintenance issue</CardTitle></CardHeader>
          <CardContent>
            {emergency ? (
              <section role="alert" className="mb-6 rounded-xl border border-destructive bg-destructive/5 p-4">
                <h2 className="font-semibold">Urgent safety guidance</h2>
                <p className="mt-3 whitespace-pre-wrap leading-7">{emergency.message}</p>
                <p className="mt-3">Your maintenance request has been saved.</p>
                <Link href={`/app/tickets/${encodeURIComponent(emergency.ticketId)}`} className="mt-3 inline-block font-medium underline">View saved request</Link>
              </section>
            ) : null}
            <form className="grid gap-4" onSubmit={submit} aria-busy={busy || loading}>
              <Label htmlFor="residence">Residence</Label>
              <select id="residence" required value={tenancy} disabled={busy || loading} onChange={(event) => setTenancy(event.target.value)} className="rounded-lg border bg-background p-3">
                <option value="">{loading ? "Loading your residence..." : "Select your residence"}</option>
                {tenancies.map((item) => <option key={item.id} value={item.id}>{item.property_name} Ã‚Â· Unit {item.unit_name}</option>)}
              </select>
              <Label htmlFor="issue-description">What needs attention?</Label>
              <textarea id="issue-description" className="min-h-48 w-full rounded-lg border p-3 focus-visible:outline-2 focus-visible:outline-ring" required maxLength={20000} value={description} disabled={busy} onChange={(event) => setDescription(event.target.value)} placeholder="Describe what you see, hear, or smell, and when it started." />
              <p className="text-sm text-muted-foreground">Avoid passwords, entry codes, and financial information.</p>
              <PreferenceSelect id="access" label="May maintenance enter while you are away?" value={access} onChange={setAccess} disabled={busy} />
              <PreferenceSelect id="pets" label="Are pets present?" value={pets} onChange={setPets} disabled={busy} />
              <Button disabled={busy || loading || Boolean(emergency) || !description.trim() || !tenancy} type="submit">{busy ? "Saving your request..." : "Submit request"}</Button>
              {error ? <p role="alert" className="text-sm text-destructive">{error} <Link href="/resident/sign-in" className="underline">Sign in</Link></p> : null}
            </form>
          </CardContent>
        </Card>
        <aside className="space-y-4 text-sm leading-6 text-muted-foreground">
          <p>If there is immediate danger, leave the area and contact emergency services.</p>
          <p>Your report is saved before assessment starts. You can follow progress in Your requests.</p>
          <p>A visit is only scheduled when your property confirms it.</p>
          <Link href="/app/tickets" className="text-primary underline">View your requests</Link>
        </aside>
      </div>
    </PageFrame>
  );
}

function PreferenceSelect({ id, label, value, onChange, disabled }: {
  id: string; label: string; value: Preference; onChange: (value: Preference) => void; disabled: boolean;
}) {
  return <div className="grid gap-2">
    <Label htmlFor={id}>{label}</Label>
    <select id={id} value={value} onChange={(event) => onChange(event.target.value as Preference)} disabled={disabled} className="rounded-lg border bg-background p-3">
      <option value="unknown">Not specified</option><option value="yes">Yes</option><option value="no">No</option>
    </select>
  </div>;
}
