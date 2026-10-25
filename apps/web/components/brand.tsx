import Link from "next/link";

export function Brand({ inverted = false }: { inverted?: boolean }) {
  return (
    <Link
      href="/"
      aria-label="Tento Resident OS home"
      className={`brand ${inverted ? "brand--inverse" : ""}`}
    >
      <svg aria-hidden="true" viewBox="0 0 32 32" className="brand-symbol">
        <path
          fill="currentColor"
          d="M3 3h11v11H3zm15 0h11v11H18zM3 18h11v11H3zm15 0h11v11H18z"
        />
        <path fill="var(--brand-lime)" d="M21 21h5v8h-5z" />
      </svg>
      <span className="brand-wordmark">
        tento<span className="brand-caption">RESIDENT OS</span>
      </span>
    </Link>
  );
}

export function WorkspaceIcon({ kind }: { kind: string }) {
  const paths: Record<string, React.ReactNode> = {
    resident: (
      <>
        <path d="m3 10 9-7 9 7v10H3z" />
        <path d="M9 20v-7h6v7" />
      </>
    ),
    maintenance: (
      <>
        <path d="M14 6a5 5 0 0 0-6 6l-5 5a2.8 2.8 0 0 0 4 4l5-5a5 5 0 0 0 6-6l-3 3-4-4z" />
      </>
    ),
    owner: (
      <>
        <path d="M5 21V3h10v18M15 9h5v12M2 21h20M8 7h4M8 11h4M8 15h4" />
      </>
    ),
    admin: (
      <>
        <path d="M4 5h16M4 12h16M4 19h16" />
        <circle cx="9" cy="5" r="2" />
        <circle cx="16" cy="12" r="2" />
        <circle cx="8" cy="19" r="2" />
      </>
    ),
  };
  return (
    <svg
      aria-hidden="true"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.5"
      strokeLinecap="round"
      strokeLinejoin="round"
    >
      {paths[kind]}
    </svg>
  );
}
