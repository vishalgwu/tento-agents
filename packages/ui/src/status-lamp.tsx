import { cva, type VariantProps } from "class-variance-authority";

import { cn } from "./utils";

const lampVariants = cva("size-2.5 shrink-0 rounded-full", {
  variants: {
    priority: {
      p0: "bg-red-600",
      p1: "bg-orange-500",
      p2: "bg-sky-600",
      p3: "bg-emerald-600",
      unassigned: "bg-slate-400",
    },
  },
  defaultVariants: {
    priority: "unassigned",
  },
});

const priorityCopy = {
  p0: "P0 life safety",
  p1: "P1 habitability",
  p2: "P2 urgent",
  p3: "P3 routine",
  unassigned: "Priority not assigned",
} as const;

export type StatusLampProps = VariantProps<typeof lampVariants> & {
  className?: string;
  label?: string;
};

/**
 * Presents urgency as a colour *and* a human-readable label. The label is
 * deliberately never optional in the rendered output, so priority does not
 * rely on colour alone.
 */
export function StatusLamp({
  className,
  label,
  priority = "unassigned",
}: StatusLampProps) {
  const safePriority = priority ?? "unassigned";

  return (
    <span className={cn("inline-flex items-center gap-2 text-sm font-medium", className)}>
      <span aria-hidden="true" className={lampVariants({ priority: safePriority })} />
      <span>{label ?? priorityCopy[safePriority]}</span>
    </span>
  );
}
