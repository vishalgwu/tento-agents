import Link from "next/link";

import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";

const destinations = [
  {
    href: "/app",
    eyebrow: "Resident",
    title: "Report and track a maintenance issue",
    description: "Mobile-first issue intake and plain-language status.",
  },
  {
    href: "/manage",
    eyebrow: "Property manager",
    title: "Review the decision queue",
    description: "Evidence, risk, cost, and a human decision in one place.",
  },
  {
    href: "/tech",
    eyebrow: "Maintenance technician",
    title: "Prepare for the authorised job",
    description: "Safe job context, parts, and status updates.",
  },
  {
    href: "/owner",
    eyebrow: "Asset owner",
    title: "See outcomes and governance",
    description: "Operational performance with audit coverage.",
  },
] as const;

export default function HomePage() {
  return (
    <main className="mx-auto flex min-h-screen w-full max-w-6xl flex-col px-6 py-10 sm:px-10 lg:py-16">
      <header className="flex items-center gap-3">
        <span
          aria-hidden="true"
          className="grid size-10 place-items-center rounded-xl border-2 border-primary bg-card shadow-sm"
        >
          <span className="h-4 w-5 rounded-sm border-2 border-primary bg-secondary" />
        </span>
        <div>
          <p className="font-mono text-xs font-medium tracking-[0.16em] text-muted-foreground uppercase">
            Resident OS
          </p>
          <p className="text-sm text-muted-foreground">Decisions with receipts.</p>
        </div>
      </header>

      <section className="grid flex-1 content-center gap-8 py-16 lg:grid-cols-[1.1fr_0.9fr] lg:gap-16">
        <div className="max-w-2xl">
          <p className="mb-4 font-mono text-xs font-medium tracking-[0.16em] text-primary uppercase">
            Phase 1 web foundation
          </p>
          <h1 className="max-w-xl text-4xl font-medium tracking-[-0.045em] text-balance sm:text-6xl">
            Apartment operations that can explain their decisions.
          </h1>
          <p className="mt-6 max-w-xl text-base leading-7 text-muted-foreground sm:text-lg">
            Resident OS turns a maintenance report into a safe, evidence-backed,
            human-reviewable dispatch decision. The measured Maintenance Loop is
            intentionally the only workflow in scope.
          </p>
        </div>

        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-1">
          {destinations.map((destination) => (
            <Card className="transition-shadow hover:shadow-md" key={destination.href}>
              <CardHeader>
                <p className="font-mono text-xs tracking-wide text-primary uppercase">
                  {destination.eyebrow}
                </p>
                <CardTitle>
                  <Link
                    className="outline-none hover:underline focus-visible:rounded-sm focus-visible:ring-2 focus-visible:ring-ring"
                    href={destination.href}
                  >
                    {destination.title}
                  </Link>
                </CardTitle>
                <CardDescription>{destination.description}</CardDescription>
              </CardHeader>
              <CardContent>
                <Link
                  className="text-sm font-medium text-primary underline-offset-4 hover:underline focus-visible:rounded-sm focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none"
                  href={destination.href}
                >
                  Open workspace <span aria-hidden="true">→</span>
                </Link>
              </CardContent>
            </Card>
          ))}
        </div>
      </section>
    </main>
  );
}
