"use client";

import Link from "next/link";
import { useId, useState } from "react";
import recordings from "@/lib/demo-recordings.json";

interface Citation {
  id: string;
  source: string;
  section: string;
  text: string;
}

interface TraceEntry {
  stage: string;
  outcome: string;
}

interface DemoResult {
  status: string;
  summary: string;
  citations: Citation[];
  trace: TraceEntry[];
  facts?: unknown;
  plan?: unknown;
  model_calls?: unknown;
  metrics?: unknown;
  demo_assumptions?: string[];
}

interface Scenario {
  id: string;
  query: string;
  expected_behavior: string;
  expected_doc_ids: string[];
  result: DemoResult;
}

interface DemoBundle {
  scenarios: Scenario[];
}

const scenarios = (recordings as unknown as DemoBundle).scenarios;
const card =
  "min-w-0 rounded-2xl border border-[var(--brand-forest)]/15 bg-white p-5 sm:p-7";

function resultFromResponse(value: unknown): DemoResult | null {
  if (!value || typeof value !== "object") return null;
  const candidate = value as Record<string, unknown>;
  if (
    typeof candidate.status !== "string" ||
    typeof candidate.summary !== "string" ||
    !Array.isArray(candidate.citations) ||
    !Array.isArray(candidate.trace)
  ) {
    return null;
  }
  const citations = candidate.citations.filter(
    (item): item is Citation =>
      Boolean(item) &&
      typeof item === "object" &&
      typeof item.id === "string" &&
      typeof item.source === "string" &&
      typeof item.section === "string" &&
      typeof item.text === "string",
  );
  const trace = candidate.trace.filter(
    (item): item is TraceEntry =>
      Boolean(item) &&
      typeof item === "object" &&
      typeof item.stage === "string" &&
      typeof item.outcome === "string",
  );
  return {
    status: candidate.status,
    summary: candidate.summary,
    citations,
    trace,
    facts: candidate.facts,
    plan: candidate.plan,
    model_calls: candidate.model_calls,
    metrics: candidate.metrics,
    demo_assumptions: Array.isArray(candidate.demo_assumptions)
      ? candidate.demo_assumptions.filter(
          (x): x is string => typeof x === "string",
        )
      : [],
  };
}

function planSummary(value: unknown): string | null {
  if (!value || typeof value !== "object" || !("proposal" in value))
    return null;
  const proposal = value.proposal;
  return proposal &&
    typeof proposal === "object" &&
    "scope_summary" in proposal &&
    typeof proposal.scope_summary === "string"
    ? proposal.scope_summary
    : null;
}

function Outcome({ result }: { result: DemoResult }) {
  const proposedScope = planSummary(result.plan);
  const status = result.status.replaceAll("_", " ");
  const badge =
    result.status === "emergency"
      ? "bg-red-50 text-red-950"
      : result.status === "abstained"
        ? "bg-amber-50 text-amber-950"
        : "bg-[var(--brand-lime)] text-[var(--brand-forest)]";
  return (
    <div className="mt-5">
      <p
        className={`inline-flex rounded-full px-3 py-1 text-xs font-semibold uppercase tracking-wide ${badge}`}
      >
        {status}
      </p>
      <p className="mt-4 whitespace-pre-wrap text-base leading-7">
        {result.summary}
      </p>
      {proposedScope && (
        <div className="mt-4 rounded-xl bg-[var(--brand-ivory)] p-4">
          <h3 className="font-semibold">Proposed demo scope</h3>
          <p className="mt-2 text-sm leading-6">{proposedScope}</p>
        </div>
      )}
      {result.demo_assumptions && result.demo_assumptions.length > 0 && (
        <details className="mt-4 text-sm leading-6">
          <summary className="cursor-pointer font-semibold">
            Fictional scenario assumptions
          </summary>
          <ul className="mt-2 list-disc pl-5">
            {result.demo_assumptions.map((item) => (
              <li key={item}>{item}</li>
            ))}
          </ul>
        </details>
      )}
      {result.trace.length > 0 && (
        <details className="mt-6 rounded-xl border border-[var(--brand-forest)]/15 px-4 py-3">
          <summary className="cursor-pointer text-sm font-semibold">
            Follow the assessment steps
          </summary>
          <ol className="mt-4 space-y-3 text-sm">
            {result.trace.map((entry, index) => (
              <li
                key={`${entry.stage}-${index}`}
                className="flex flex-wrap justify-between gap-2 border-t border-[var(--brand-forest)]/10 pt-3 first:border-0 first:pt-0"
              >
                <span>{entry.stage.replaceAll("_", " ")}</span>
                <span className="text-[var(--brand-ink)]/75">
                  {entry.outcome.replaceAll("_", " ")}
                </span>
              </li>
            ))}
          </ol>
        </details>
      )}
      {Array.isArray(result.model_calls) && result.model_calls.length > 0 && (
        <p className="mt-4 text-xs leading-5 text-[var(--brand-ink)]/75">
          {result.model_calls.length} recorded model-call receipt
          {result.model_calls.length === 1 ? "" : "s"} accompany this
          assessment.
        </p>
      )}
    </div>
  );
}

export function DemoExplorer() {
  const selectId = useId();
  const [selectedId, setSelectedId] = useState(
    scenarios.find((item) => item.id === "TC-003")?.id ??
      scenarios[0]?.id ??
      "",
  );
  const [liveResult, setLiveResult] = useState<DemoResult | null>(null);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState("");
  const [needsSignIn, setNeedsSignIn] = useState(false);
  const selected = scenarios.find((item) => item.id === selectedId);

  async function runLive() {
    if (!selected || pending) return;
    setPending(true);
    setError("");
    setNeedsSignIn(false);
    try {
      const response = await fetch("/api/demo", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ description: selected.query }),
        cache: "no-store",
        signal: AbortSignal.timeout(190000),
      });
      if (response.status === 401) {
        setNeedsSignIn(true);
        setError(
          "Sign in to run the connected model, then return to this demo.",
        );
        return;
      }
      if (!response.ok) {
        setError(
          response.status === 429
            ? "The request limit has been reached. Please try again later."
            : "The live assessment is unavailable. You can still inspect the recorded example.",
        );
        return;
      }
      const result = resultFromResponse(await response.json());
      if (!result) {
        setError(
          "The assessment response could not be verified. Try again later.",
        );
        return;
      }
      setLiveResult(result);
    } catch {
      setError(
        "The live assessment did not finish. The recorded example remains available.",
      );
    } finally {
      setPending(false);
    }
  }

  if (!selected) {
    return <p role="status">Demo recordings are being prepared.</p>;
  }

  const result = liveResult ?? selected.result;

  return (
    <div className="space-y-6 text-[var(--brand-ink)]">
      <section className={card} aria-labelledby="scenario-title">
        <h2 id="scenario-title" className="font-serif text-2xl sm:text-3xl">
          Start with a scenario
        </h2>
        <label
          htmlFor={selectId}
          className="mb-2 mt-5 block text-sm font-semibold"
        >
          Maintenance scenario
        </label>
        <select
          id={selectId}
          value={selectedId}
          disabled={pending}
          onChange={(event) => {
            setSelectedId(event.target.value);
            setLiveResult(null);
            setError("");
            setNeedsSignIn(false);
          }}
          className="min-h-12 w-full min-w-0 rounded-xl border border-[var(--brand-forest)]/25 bg-[var(--brand-ivory)] px-3 py-3 text-sm focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--brand-forest)] disabled:opacity-60"
        >
          {scenarios.map((scenario) => (
            <option key={scenario.id} value={scenario.id}>
              {scenario.id} — {scenario.query}
            </option>
          ))}
        </select>
        <p className="mt-5 whitespace-pre-wrap text-lg leading-8">
          “{selected.query}”
        </p>
        <details className="mt-4 text-sm leading-6">
          <summary className="cursor-pointer font-semibold">
            What this example checks
          </summary>
          <p className="mt-2">{selected.expected_behavior}</p>
          {selected.expected_doc_ids.length > 0 && (
            <p className="mt-2 break-words text-xs">
              Expected policy sources: {selected.expected_doc_ids.join(", ")}
            </p>
          )}
        </details>
      </section>

      <div className="grid items-start gap-6 lg:grid-cols-2">
        <section
          className={card}
          aria-labelledby="assessment-title"
          aria-busy={pending}
        >
          <p className="text-xs font-semibold uppercase tracking-widest text-[var(--brand-ink)]/65">
            {liveResult
              ? "Connected model assessment"
              : "Recorded AI assessment"}
          </p>
          <h2
            id="assessment-title"
            className="mt-2 font-serif text-2xl sm:text-3xl"
          >
            The considered response
          </h2>
          <div aria-live="polite" aria-atomic="true">
            <Outcome result={result} />
          </div>
          <div className="mt-7 border-t border-[var(--brand-forest)]/15 pt-5">
            <button
              type="button"
              disabled={pending}
              onClick={() => void runLive()}
              className="brand-button max-w-full disabled:cursor-wait disabled:opacity-60"
            >
              {pending ? "Assessing the scenario…" : "Run a fresh assessment"}
              <span aria-hidden="true">↗</span>
            </button>
            <p className="mt-3 text-xs leading-5 text-[var(--brand-ink)]/75">
              Sign-in required for a fresh model run. This demo never creates a
              real ticket or dispatches a person.
            </p>
            {error && (
              <div
                role="alert"
                className="mt-4 rounded-xl bg-[var(--brand-ivory)] px-4 py-3 text-sm leading-6"
              >
                <p>{error}</p>
                {needsSignIn && (
                  <Link href="/sign-in" className="text-link mt-2 inline-flex">
                    Sign in to continue ↗
                  </Link>
                )}
              </div>
            )}
          </div>
        </section>

        <section className={card} aria-labelledby="evidence-title">
          <p className="text-xs font-semibold uppercase tracking-widest text-[var(--brand-ink)]/65">
            FICTIONAL MAPLE COURT POLICY PACK
          </p>
          <h2
            id="evidence-title"
            className="mt-2 font-serif text-2xl sm:text-3xl"
          >
            Inspect the evidence
          </h2>
          {result.citations.length === 0 ? (
            <p className="mt-5 text-sm leading-7">
              No supporting policy passage was used for this outcome. Safety
              screening and abstention may stop an assessment before retrieval.
            </p>
          ) : (
            <ul className="mt-5 space-y-5">
              {result.citations.map((citation, index) => (
                <li
                  key={`${citation.id}-${index}`}
                  className="min-w-0 border-t border-[var(--brand-forest)]/15 pt-5 first:border-0 first:pt-0"
                >
                  <p className="break-words text-sm font-semibold">
                    {citation.id} · {citation.source}
                  </p>
                  <p className="mt-1 break-words text-xs leading-5 text-[var(--brand-ink)]/70">
                    {citation.section}
                  </p>
                  <blockquote className="mt-3 whitespace-pre-wrap break-words border-l-2 border-[var(--brand-lime)] pl-4 text-sm leading-7">
                    {citation.text}
                  </blockquote>
                </li>
              ))}
            </ul>
          )}
        </section>
      </div>
    </div>
  );
}
