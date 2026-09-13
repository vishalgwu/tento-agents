import Link from "next/link";
import type { ReactNode } from "react";

type PageFrameProps = {
  children: ReactNode;
  description: string;
  eyebrow: string;
  title: string;
};

const destinations = [
  { href: "/app", label: "Resident" },
  { href: "/manage", label: "Manager" },
  { href: "/tech", label: "Technician" },
  { href: "/owner", label: "Owner" },
] as const;

/** A small, role-neutral frame so each workspace has the same route boundary. */
export function PageFrame({ children, description, eyebrow, title }: PageFrameProps) {
  return (
    <main className="mx-auto min-h-screen w-full max-w-6xl px-6 py-8 sm:px-10 lg:py-12">
      <header className="flex flex-col gap-6 border-b pb-6 sm:flex-row sm:items-start sm:justify-between">
        <div>
          <Link
            className="font-mono text-xs font-medium tracking-[0.16em] text-primary uppercase outline-none focus-visible:rounded-sm focus-visible:ring-2 focus-visible:ring-ring"
            href="/"
          >
            Resident OS
          </Link>
          <p className="mt-3 font-mono text-xs font-medium tracking-[0.14em] text-muted-foreground uppercase">
            {eyebrow}
          </p>
          <h1 className="mt-2 text-3xl font-medium tracking-[-0.035em] sm:text-4xl">{title}</h1>
          <p className="mt-3 max-w-2xl leading-7 text-muted-foreground">{description}</p>
        </div>
        <nav aria-label="Role workspaces" className="flex flex-wrap gap-x-4 gap-y-2 text-sm">
          {destinations.map((destination) => (
            <Link
              className="text-muted-foreground underline-offset-4 hover:text-foreground hover:underline focus-visible:rounded-sm focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none"
              href={destination.href}
              key={destination.href}
            >
              {destination.label}
            </Link>
          ))}
        </nav>
      </header>
      <section className="py-8 sm:py-10">{children}</section>
    </main>
  );
}
