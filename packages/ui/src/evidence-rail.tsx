"use client";

import {
  createContext,
  useCallback,
  useContext,
  useMemo,
  useState,
  type KeyboardEvent,
  type ReactNode,
} from "react";

import { cn } from "./utils";

export type EvidenceItem = {
  excerpt: string;
  id: string;
  label: string;
};

type EvidenceContextValue = {
  activeEvidenceId: string | null;
  setActiveEvidenceId: (id: string | null) => void;
};

const EvidenceContext = createContext<EvidenceContextValue | null>(null);

export type EvidenceRailProps = {
  children: ReactNode;
  className?: string;
  items: readonly EvidenceItem[];
};

/**
 * Groups citation chips and the claim text they support. Hovering or focusing
 * either side highlights the other through a shared, keyboard-accessible state.
 */
export function EvidenceRail({ children, className, items }: EvidenceRailProps) {
  const [activeEvidenceId, setActiveEvidenceId] = useState<string | null>(null);
  const contextValue = useMemo(
    () => ({ activeEvidenceId, setActiveEvidenceId }),
    [activeEvidenceId],
  );

  return (
    <EvidenceContext.Provider value={contextValue}>
      <section
        aria-label="Supporting evidence"
        className={cn("grid gap-4 rounded-lg border bg-card p-4", className)}
      >
        <div className="min-w-0 text-sm leading-6 text-card-foreground">{children}</div>
        <ol className="flex flex-wrap gap-2" aria-label="Evidence citations">
          {items.map((item) => (
            <EvidenceChip item={item} key={item.id} />
          ))}
        </ol>
        {activeEvidenceId ? (
          <EvidenceExcerpt item={items.find((item) => item.id === activeEvidenceId)} />
        ) : (
          <p className="text-xs text-muted-foreground">
            Focus a cited claim or citation chip to inspect its evidence.
          </p>
        )}
      </section>
    </EvidenceContext.Provider>
  );
}

export type EvidenceClaimProps = {
  children: ReactNode;
  className?: string;
  evidenceId: string;
};

/** A claim fragment that participates in its parent `EvidenceRail` interaction. */
export function EvidenceClaim({ children, className, evidenceId }: EvidenceClaimProps) {
  const evidence = useContext(EvidenceContext);
  const isActive = evidence?.activeEvidenceId === evidenceId;
  const activate = useCallback(() => evidence?.setActiveEvidenceId(evidenceId), [evidence, evidenceId]);
  const deactivate = useCallback(
    () => evidence?.setActiveEvidenceId(null),
    [evidence],
  );
  const handleKeyDown = useCallback(
    (event: KeyboardEvent<HTMLSpanElement>) => {
      if (event.key === "Enter" || event.key === " ") {
        event.preventDefault();
        activate();
      }
    },
    [activate],
  );

  return (
    <span
      className={cn(
        "rounded-sm decoration-primary decoration-2 underline-offset-2 focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none",
        isActive && "bg-sky-100 underline",
        className,
      )}
      onBlur={deactivate}
      onClick={activate}
      onFocus={activate}
      onKeyDown={handleKeyDown}
      onMouseEnter={activate}
      onMouseLeave={deactivate}
      role="button"
      tabIndex={0}
    >
      {children}
    </span>
  );
}

function EvidenceChip({ item }: { item: EvidenceItem }) {
  const evidence = useContext(EvidenceContext);
  const isActive = evidence?.activeEvidenceId === item.id;
  const activate = () => evidence?.setActiveEvidenceId(item.id);
  const deactivate = () => evidence?.setActiveEvidenceId(null);

  return (
    <li>
      <button
        aria-pressed={isActive}
        className={cn(
          "rounded-full border px-2.5 py-1 font-mono text-xs transition-colors focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none",
          isActive
            ? "border-primary bg-primary text-primary-foreground"
            : "border-border bg-secondary text-secondary-foreground hover:border-primary",
        )}
        onBlur={deactivate}
        onFocus={activate}
        onMouseEnter={activate}
        onMouseLeave={deactivate}
        type="button"
      >
        {item.label}
      </button>
    </li>
  );
}

function EvidenceExcerpt({ item }: { item: EvidenceItem | undefined }) {
  if (!item) {
    return null;
  }

  return (
    <p className="rounded-md bg-secondary px-3 py-2 text-xs leading-5 text-secondary-foreground">
      <span className="font-mono font-medium">{item.label}</span>: {item.excerpt}
    </p>
  );
}
