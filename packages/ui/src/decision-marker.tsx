import { cva, type VariantProps } from "class-variance-authority";

import { cn } from "./utils";

const markerVariants = cva(
  "inline-flex items-center gap-2 rounded-full border px-2.5 py-1 text-xs font-medium",
  {
    variants: {
      authority: {
        machine: "border-sky-700/25 bg-sky-50 text-sky-950",
        human: "border-amber-700/30 bg-amber-50 text-amber-950",
      },
    },
    defaultVariants: {
      authority: "machine",
    },
  },
);

const markerCopy = {
  machine: "Machine proposal",
  human: "Human authorised",
} as const;

export type DecisionMarkerProps = VariantProps<typeof markerVariants> & {
  className?: string;
  label?: string;
};

/** Makes the distinction between a system proposal and human authority explicit. */
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
          safeAuthority === "machine" ? "bg-sky-700" : "bg-amber-700",
        )}
      />
      <span>{label ?? markerCopy[safeAuthority]}</span>
    </span>
  );
}
