import Link from "next/link";
import type { ReactNode } from "react";
import { Brand } from "@/components/brand";

type PageFrameProps = {
  children: ReactNode;
  description: string;
  eyebrow: string;
  title: string;
};
export function PageFrame({
  children,
  description,
  eyebrow,
  title,
}: PageFrameProps) {
  return (
    <div className="app-shell">
      <header className="app-topbar">
        <Brand />
        <nav aria-label="Main navigation">
          <Link href="/">Home</Link>
          <Link href="/#workspaces">
            Workspaces <span aria-hidden="true">↗</span>
          </Link>
        </nav>
      </header>
      <main className="app-main">
        <header className="workspace-page-heading">
          <div>
            <p className="eyebrow">
              <span className="status-dot" />
              {eyebrow}
            </p>
            <h1>{title}</h1>
            <p className="page-description">{description}</p>
          </div>
          <span className="workspace-heading-mark" aria-hidden="true">
            ✳
          </span>
        </header>
        <section className="workspace-content">{children}</section>
      </main>
      <footer className="app-footer">
        <span>Tento Resident OS</span>
        <span>Thoughtfully connected.</span>
        <Link href="/#workspaces">All workspaces ↗</Link>
      </footer>
    </div>
  );
}
