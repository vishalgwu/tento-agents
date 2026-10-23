import { cva, type VariantProps } from "class-variance-authority";

import { cn } from "./utils";

const markerVariants = cva(
  "inline-flex items-center gap-2 rounded-full border px-2.5 py-1 text-xs font-medium",
  {
    variants: {
      authority: {
        machine: "border-sky-700/25 bg-sky-50 text-sky-950",
      },
    },
    defaultVariants: {
      authority: "machine",
    },
  },
);

const markerCopy = {
  machine: "Agent assessment",
} as const;

export type DecisionMarkerProps = VariantProps<typeof markerVariants> & {
  className?: string;
  label?: string;
};

/** Identifies an automated system result. */
export function DecisionMarker({
  authority = "machine",
  className,
  label,
}: DecisionMarkerProps) {
  const safeAuthority = authority ?? "machine";

  return (
    <span className={cn(markerVariants({ authority: safeAuthority }), className)}>
      <span
        aria-hidden="true"
        className={cn(
          "size-2 rotate-45 rounded-[1px]",
          "bg-sky-700",
        )}
      />
      <span>{label ?? markerCopy[safeAuthority]}</span>
    </span>
  );
}
