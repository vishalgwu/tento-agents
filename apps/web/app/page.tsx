import Link from "next/link";
import { workspaces, type Workspace } from "@/lib/workspaces";

const roles: Workspace[] = ["resident", "maintenance", "owner", "admin"];
const workflow = [
  [
    "01",
    "Describe the issue",
    "A resident selects an authorized residence and saves a maintenance report.",
  ],
  [
    "02",
    "Understand and protect",
    "Safety rules screen the report. AI turns the description into structured maintenance facts.",
  ],
  [
    "03",
    "Check the evidence",
    "The agent looks for applicable property policies and validates its proposed assessment.",
  ],
  [
    "04",
    "Show a grounded result",
    "A supported in-house plan can create an internal work order. Missing evidence produces an explicit abstention.",
  ],
];
export default function HomePage() {
  return (
    <main className="mx-auto min-h-screen max-w-7xl px-6 py-6 sm:px-12">
      <header className="flex flex-wrap items-center justify-between gap-6 border-b py-4">
        <Link href="/" className="text-2xl font-semibold tracking-tight">
          tento
          <span className="ml-2 align-middle text-xs font-normal uppercase tracking-widest text-muted-foreground">
            Resident OS
          </span>
        </Link>
        <nav aria-label="Platform navigation" className="flex gap-6 text-sm">
          <a href="#workflow">How it works</a>
          <a href="#workspaces">Workspaces</a>
          <Link href="/sign-in">Sign in ↗</Link>
        </nav>
      </header>
      <section className="grid gap-12 py-16 sm:py-24 lg:grid-cols-[1.2fr_1fr] lg:items-center">
        <div>
          <p className="mb-6 text-xs font-medium uppercase tracking-[0.22em] text-primary">
            Community operations, connected.
          </p>
          <h1 className="max-w-3xl text-5xl font-medium leading-[1.05] tracking-[-0.05em] sm:text-7xl">
            One home for your community.
          </h1>
          <p className="mt-7 max-w-xl text-lg leading-8 text-muted-foreground">
            Tento connects residents, maintenance teams, property owners and
            technical administrators through one application. Our GenAI
            maintenance assistant helps turn a report into a clear,
            evidence-backed next step.
          </p>
          <a
            href="#workspaces"
            className="mt-9 inline-flex rounded-full bg-primary px-7 py-3 text-sm font-medium text-primary-foreground hover:opacity-90 focus-visible:outline-2 focus-visible:outline-offset-4"
          >
            Choose your workspace ↓
          </a>
          <p className="mt-5 text-xs text-muted-foreground">
            Current release: AI-assisted maintenance, with saved requests and
            visible outcomes.
          </p>
        </div>
        <aside
          aria-label="Application workflow"
          className="rounded-3xl border bg-card p-7 shadow-sm sm:p-9"
        >
          <div className="mb-8 flex items-center justify-between">
            <span className="text-xs uppercase tracking-widest text-muted-foreground">
              Inside the application
            </span>
            <span className="rounded-full bg-secondary px-3 py-1 text-xs">
              Live MVP
            </span>
          </div>
          <div className="space-y-0">
            {[
              "Resident report",
              "Safety + AI intake",
              "Policy evidence + validation",
              "Saved assessment + next step",
            ].map((label, i) => (
              <div
                className="flex items-center gap-5 border-b py-5 last:border-0"
                key={label}
              >
                <span className="flex size-9 shrink-0 items-center justify-center rounded-full border font-mono text-xs text-primary">
                  0{i + 1}
                </span>
                <span className="font-medium">{label}</span>
              </div>
            ))}
          </div>
          <p className="mt-7 text-sm leading-6 text-muted-foreground">
            The assistant shows when evidence is missing. It does not invent
            policies, dispatch receipts or scheduled visits.
          </p>
        </aside>
      </section>
      <section id="workspaces" className="scroll-mt-8 border-t py-14">
        <div className="mb-9 flex flex-wrap items-end justify-between gap-5">
          <div>
            <p className="text-xs uppercase tracking-widest text-primary">
              Your place in Tento
            </p>
            <h2 className="mt-3 text-3xl font-medium tracking-tight">
              One application. Your workspace.
            </h2>
          </div>
          <p className="max-w-sm text-sm leading-6 text-muted-foreground">
            Sign in with an existing organization account. Your verified role
            determines what you can access.
          </p>
        </div>
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
          {roles.map((key, i) => (
            <Link
              key={key}
              href={`/sign-in?workspace=${key}`}
              className="group flex min-h-64 flex-col rounded-2xl border bg-card p-6 transition-colors hover:border-primary focus-visible:outline-2 focus-visible:outline-primary"
            >
              <span className="font-mono text-xs text-muted-foreground">
                0{i + 1} / WORKSPACE
              </span>
              <h3 className="mt-7 text-xl font-medium">
                {workspaces[key].name}
              </h3>
              <p className="mt-3 text-sm leading-6 text-muted-foreground">
                {workspaces[key].description}
              </p>
              <span className="mt-auto pt-7 text-sm font-medium text-primary">
                Sign in <span aria-hidden="true">↗</span>
              </span>
            </Link>
          ))}
        </div>
      </section>
      <section id="workflow" className="scroll-mt-8 border-t py-14">
        <p className="text-xs uppercase tracking-widest text-primary">
          GenAI with a clear purpose
        </p>
        <h2 className="mt-3 text-3xl font-medium tracking-tight">
          From a resident's words to a grounded assessment.
        </h2>
        <div className="mt-10 grid gap-8 md:grid-cols-2 lg:grid-cols-4">
          {workflow.map(([number, title, description]) => (
            <article key={number}>
              <p className="font-mono text-sm text-primary">{number}</p>
              <h3 className="mt-4 font-medium">{title}</h3>
              <p className="mt-3 text-sm leading-7 text-muted-foreground">
                {description}
              </p>
            </article>
          ))}
        </div>
        <p className="mt-10 rounded-xl border p-5 text-sm leading-6 text-muted-foreground">
          Approved property policy sources are still required for policy-backed
          work orders. Maintenance and owner workspaces currently provide
          read-only views; repair assignment, vendor contact, financial
          reporting and user administration are outside this release.
        </p>
      </section>
      <footer className="flex flex-wrap justify-between gap-4 border-t py-7 text-xs text-muted-foreground">
        <p>Tento Resident OS / AI-assisted community maintenance</p>
        <Link href="/sign-in">Access your workspace ↗</Link>
      </footer>
    </main>
  );
}
