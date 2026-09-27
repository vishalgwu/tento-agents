"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import type { components } from "@resident-os/shared-types";
import { DecisionMarker, EvidenceClaim, EvidenceRail, StatusLamp, type EvidenceItem } from "@resident-os/ui";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardFooter, CardHeader, CardTitle } from "@/components/ui/card";

const rejectionReasons = [
  ["insufficient_evidence", "Insufficient evidence"],
  ["incorrect_priority", "Incorrect priority"],
  ["incorrect_routing", "Incorrect routing"],
  ["cost_or_scope", "Cost or scope"],
  ["policy_conflict", "Policy conflict"],
] as const;
const currencyFormatter = new Intl.NumberFormat("en-US", { currency: "USD", style: "currency" });
const deadlineFormatter = new Intl.DateTimeFormat("en-US", {
  dateStyle: "medium",
  timeStyle: "short",
  timeZone: "UTC",
});
const formElementPattern = /^(INPUT|SELECT|TEXTAREA)$/;

type PreviewClaim = {
  citation?: EvidenceItem;
  text: string;
};

export type PreviewApproval = components["schemas"]["ApprovalQueueItem"] & {
  claims: readonly PreviewClaim[];
  title: string;
};

type ApprovalQueueProps = {
  items: readonly PreviewApproval[];
};

function Key({ children }: { children: string }) {
  return <kbd className="rounded border bg-background px-1.5 py-0.5 font-mono text-[0.7rem]">{children}</kbd>;
}

function formatCost(cents: number | null) {
  if (cents === null) {
    return "Not estimated";
  }

  return currencyFormatter.format(cents / 100);
}

/**
 * A deliberately local-only keyboard review preview. Approval actions must not
 * call the API until browser identity and idempotency-key issuance are wired.
 */
export function ApprovalQueue({ items }: ApprovalQueueProps) {
  const [activeIndex, setActiveIndex] = useState(0);
  const [humanTouched, setHumanTouched] = useState<ReadonlySet<string>>(() => new Set());
  const [isChoosingRejection, setIsChoosingRejection] = useState(false);
  const [notice, setNotice] = useState("Preview only. No approval API request has been sent.");
  const evidenceRef = useRef<HTMLDivElement>(null);
  const item = items[activeIndex] ?? null;

  const touch = useCallback(
    (message: string) => {
      if (!item) {
        return;
      }

      setHumanTouched((current) => new Set(current).add(item.approval_id));
      setNotice(`${message} Preview only: no approval API request has been sent.`);
    },
    [item],
  );

  const move = useCallback(
    (direction: 1 | -1) => {
      if (items.length === 0) {
        return;
      }

      setActiveIndex((current) => (current + direction + items.length) % items.length);
      setIsChoosingRejection(false);
      setNotice("Moved to another SLA-ordered preview. No approval API request has been sent.");
    },
    [items.length],
  );

  const focusEvidence = useCallback(() => {
    evidenceRef.current?.querySelector<HTMLElement>("[role='button'], button")?.focus();
    setNotice("Evidence controls focused. Preview only: no approval API request has been sent.");
  }, []);

  const chooseRejection = useCallback(
    (reasonIndex: number) => {
      const reason = rejectionReasons[reasonIndex];
      if (!reason || !isChoosingRejection) {
        return;
      }

      touch(`Rejection reason selected: ${reason[1]}.`);
      setIsChoosingRejection(false);
    },
    [isChoosingRejection, touch],
  );

  const startRejection = useCallback(() => {
    if (!item) {
      return;
    }

    setHumanTouched((current) => new Set(current).add(item.approval_id));
    setIsChoosingRejection(true);
    setNotice("Choose a rejection reason with 1–5. Preview only: no approval API request has been sent.");
  }, [item]);

  useEffect(() => {
    if (!item) {
      return;
    }

    const onKeyDown = (event: KeyboardEvent) => {
      const target = event.target;
      if (
        event.altKey ||
        event.ctrlKey ||
        event.metaKey ||
        (target instanceof HTMLElement && (target.isContentEditable || formElementPattern.test(target.tagName)))
      ) {
        return;
      }

      if (event.key === "j") {
        event.preventDefault();
        move(1);
      } else if (event.key === "k") {
        event.preventDefault();
        move(-1);
      } else if (event.key === "a") {
        event.preventDefault();
        touch("Approve preview selected.");
      } else if (event.key === "e") {
        event.preventDefault();
        focusEvidence();
      } else if (event.key === "r") {
        event.preventDefault();
        startRejection();
      } else if (event.key === "t") {
        event.preventDefault();
        touch("Reassignment preview selected.");
      } else if (/^[1-5]$/.test(event.key)) {
        event.preventDefault();
        chooseRejection(Number(event.key) - 1);
      }
    };

    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [chooseRejection, focusEvidence, item, move, startRejection, touch]);

  if (!item) {
    return (
      <main className="mx-auto grid h-dvh max-w-6xl place-items-center overflow-hidden px-4 py-4 sm:px-6">
        <Card className="w-full max-w-xl" size="sm">
          <CardHeader>
            <Badge variant="secondary">Preview only</Badge>
            <CardTitle>No approval previews</CardTitle>
            <CardDescription>There are no local approval cards to review.</CardDescription>
          </CardHeader>
        </Card>
      </main>
    );
  }

  const evidence = item.claims.flatMap((claim) => (claim.citation ? [claim.citation] : []));
  const isHumanTouched = humanTouched.has(item.approval_id);

  return (
    <main className="mx-auto grid h-dvh max-w-6xl grid-rows-[auto_minmax(0,1fr)_auto] gap-3 overflow-hidden px-4 py-4 sm:px-6">
      <header className="flex items-start justify-between gap-4">
        <div>
          <p className="text-xs font-semibold tracking-[0.16em] text-muted-foreground uppercase">Manager review</p>
          <h1 className="font-heading text-xl font-semibold tracking-tight">Approval queue</h1>
        </div>
        <p className="text-right text-xs text-muted-foreground">
          {activeIndex + 1} of {items.length} · SLA-risk order
        </p>
      </header>

      <Card className="min-h-0 justify-between" size="sm">
        <CardHeader className="border-b">
          <div className="flex items-start justify-between gap-3">
            <div className="min-w-0">
              <div className="mb-1 flex flex-wrap items-center gap-2">
                <Badge variant="secondary">Preview only</Badge>
                <Badge variant="outline">Ticket #{item.ticket_number}</Badge>
                <StatusLamp priority={item.priority ?? "unassigned"} />
              </div>
              <CardTitle>{item.title}</CardTitle>
              <CardDescription>{item.symptom_summary ?? "No symptom summary supplied."}</CardDescription>
            </div>
            <DecisionMarker authority={isHumanTouched ? "human" : "machine"} />
          </div>
        </CardHeader>

        <CardContent className="grid min-h-0 gap-3 overflow-hidden pt-3 lg:grid-cols-[0.9fr_1.1fr]">
          <dl className="grid content-start grid-cols-2 gap-x-4 gap-y-3 text-sm">
            <div>
              <dt className="text-xs text-muted-foreground">Proposed trade</dt>
              <dd className="font-medium">{item.proposed_trade ?? "Not specified"}</dd>
            </div>
            <div>
              <dt className="text-xs text-muted-foreground">Responsible party</dt>
              <dd className="font-medium">{item.proposed_responsible_party}</dd>
            </div>
            <div>
              <dt className="text-xs text-muted-foreground">Estimated cost</dt>
              <dd className="font-medium">{formatCost(item.estimated_cost_cents)}</dd>
            </div>
            <div>
              <dt className="text-xs text-muted-foreground">Required role</dt>
              <dd className="font-medium capitalize">{item.required_role.replaceAll("_", " ")}</dd>
            </div>
            <div className="col-span-2 rounded-md border bg-muted/40 px-3 py-2 text-xs text-muted-foreground">
              SLA deadline:{" "}
              <span className="font-medium text-foreground">
                {deadlineFormatter.format(new Date(item.sla_expires_at))} UTC
              </span>
            </div>
          </dl>

          <div className="min-h-0 overflow-hidden" ref={evidenceRef}>
            <EvidenceRail className="h-full content-start gap-2 p-3" items={evidence}>
              <p className="mb-2 text-xs font-semibold tracking-[0.14em] text-muted-foreground uppercase">Claims</p>
              <ul className="grid gap-2">
                {item.claims.map((claim) => (
                  <li key={claim.text}>
                    {claim.citation ? (
                      <EvidenceClaim evidenceId={claim.citation.id}>{claim.text}</EvidenceClaim>
                    ) : (
                      <span className="inline-flex rounded border border-amber-600/60 bg-amber-100 px-2 py-1 text-amber-950 dark:bg-amber-950/40 dark:text-amber-100">
                        <span className="mr-1 font-semibold">Unsupported:</span>
                        {claim.text}
                      </span>
                    )}
                  </li>
                ))}
              </ul>
            </EvidenceRail>
          </div>
        </CardContent>

        <CardFooter className="flex-wrap justify-between gap-2">
          <div className="flex flex-wrap gap-2">
            <Button onClick={() => touch("Approve preview selected.")} size="sm" type="button">
              Approve <Key>a</Key>
            </Button>
            <Button
              onClick={startRejection}
              size="sm"
              type="button"
              variant="destructive"
            >
              Reject <Key>r</Key>
            </Button>
            <Button onClick={() => touch("Reassignment preview selected.")} size="sm" type="button" variant="outline">
              Reassign <Key>t</Key>
            </Button>
          </div>
          <div className="flex flex-wrap gap-1 text-xs text-muted-foreground">
            <span>Next</span><Key>j</Key><span>Previous</span><Key>k</Key><span>Evidence</span><Key>e</Key>
          </div>
        </CardFooter>
      </Card>

      <div aria-live="polite" className="flex min-h-5 items-center justify-between gap-3 text-xs text-muted-foreground">
        <p>{notice}</p>
        {isChoosingRejection ? (
          <p className="shrink-0 font-medium text-destructive">
            {rejectionReasons.map(([_, label], index) => (
              <span className="ml-2" key={label}>
                <Key>{String(index + 1)}</Key> {label}
              </span>
            ))}
          </p>
        ) : null}
      </div>
    </main>
  );
}
