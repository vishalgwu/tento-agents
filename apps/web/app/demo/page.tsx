import Link from "next/link";
import { Brand } from "@/components/brand";
import { DemoExplorer } from "@/components/demo-explorer";

export const metadata = {
  title: "Policy-grounded demo | Tento Resident OS",
  description:
    "Explore recorded AI maintenance assessments grounded in a fictional Maple Court policy pack.",
};

export default function DemoPage() {
  return (
    <main className="marketing min-h-screen">
      <header className="site-header">
        <Brand />
        <nav aria-label="Demo navigation">
          <Link href="/">Home</Link>
          <Link href="/sign-in" className="nav-signin">
            Sign in <span aria-hidden="true">↗</span>
          </Link>
        </nav>
      </header>
      <section className="mx-auto max-w-7xl px-5 pb-16 pt-12 sm:px-8 sm:pt-20">
        <p className="eyebrow">THE POLICY-GROUNDED DEMO</p>
        <h1 className="mt-4 max-w-4xl font-serif text-4xl leading-tight tracking-tight text-[var(--brand-forest)] sm:text-6xl">
          A report. Its evidence.
          <br />
          <em>A considered next step.</em>
        </h1>
        <p className="mt-6 max-w-3xl text-base leading-7 text-[var(--brand-ink)]">
          Follow a maintenance scenario through a recorded AI assessment.
          Inspect the policy passages behind the result, then sign in to run the
          selected scenario again with the connected model.
        </p>
        <p className="mt-6 max-w-3xl rounded-2xl border border-[var(--brand-forest)]/15 bg-white/70 px-5 py-4 text-sm leading-6">
          <strong>Synthetic demo.</strong> Maple Court is a fictional property.
          These examples are not legal advice or approved real-property
          policies. No real work order, dispatch, notification or repair is
          performed here.
        </p>
        <div className="mt-10">
          <DemoExplorer />
        </div>
      </section>
    </main>
  );
}
