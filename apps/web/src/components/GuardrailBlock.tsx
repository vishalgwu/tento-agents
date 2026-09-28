import { useId } from "react";

import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { cn } from "@/lib/utils";

export type GuardrailBlockReason = {
  /** Stable machine-safe rule or reason identifier, never inspected content. */
  code: string;
  /** Plain-language explanation suitable for the assigned human reviewer. */
  label: string;
};

export type GuardrailBlockProps = {
  /** The guardrail category, such as fair housing or prompt injection. */
  kind: string;
  /** Safe, human-readable explanations returned by the guardrail receipt. */
  reasons: readonly GuardrailBlockReason[];
  /** Required review actions. This component never retries or releases content. */
  nextSteps?: readonly string[];
  /** Optional stable policy/rule version for audit traceability. */
  ruleVersion?: string;
  className?: string;
};

const defaultNextSteps = [
  "Review the original content in the secured audit view.",
  "Confirm a compliant, evidence-supported response or decision.",
  "Record the review outcome before releasing any replacement content.",
] as const;

/**
 * A content-safe explanation of a guardrail block.
 *
 * It intentionally accepts only safe rule metadata and reviewer instructions;
 * raw prompts, drafts, and protected attributes must stay out of this UI layer.
 */
export function GuardrailBlock({
  className,
  kind,
  nextSteps = defaultNextSteps,
  reasons,
  ruleVersion,
}: GuardrailBlockProps) {
  const reviewSteps = nextSteps.length > 0 ? nextSteps : defaultNextSteps;
  const blockId = useId();
  const titleId = `${blockId}-title`;
  const reasonsId = `${blockId}-reasons`;
  const nextStepsId = `${blockId}-next-steps`;

  return (
    <Card
      aria-labelledby={titleId}
      className={cn("border-destructive/40 bg-destructive/[0.04]", className)}
      role="alert"
      size="sm"
    >
      <CardHeader className="border-b border-destructive/20">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <Badge variant="destructive">Blocked before release</Badge>
            <CardTitle className="mt-2" id={titleId}>
              {formatGuardrailKind(kind)} guardrail requires human review
            </CardTitle>
            <CardDescription>
              No content was sent or automatically rewritten. A reviewer must resolve this block.
            </CardDescription>
          </div>
          {ruleVersion ? (
            <span className="font-mono text-xs text-muted-foreground">Rule {ruleVersion}</span>
          ) : null}
        </div>
      </CardHeader>

      <CardContent className="grid gap-5 pt-4 sm:grid-cols-2">
        <section aria-labelledby={reasonsId}>
          <h2 className="text-sm font-semibold" id={reasonsId}>
            Why it was blocked
          </h2>
          {reasons.length > 0 ? (
            <ul className="mt-2 grid gap-2">
              {reasons.map((reason, index) => (
                <li
                  className="rounded-md border border-destructive/20 bg-background/70 px-3 py-2"
                  key={`${reason.code}-${index}`}
                >
                  <p className="text-sm font-medium">{reason.label}</p>
                  <p className="mt-0.5 font-mono text-xs text-muted-foreground">{reason.code}</p>
                </li>
              ))}
            </ul>
          ) : (
            <p className="mt-2 text-sm text-muted-foreground">
              The guardrail returned no displayable reason. Review the secured audit receipt before proceeding.
            </p>
          )}
        </section>

        <section aria-labelledby={nextStepsId}>
          <h2 className="text-sm font-semibold" id={nextStepsId}>
            What you must do next
          </h2>
          <ol className="mt-2 grid list-decimal gap-2 pl-5 text-sm">
            {reviewSteps.map((step) => (
              <li key={step}>{step}</li>
            ))}
          </ol>
        </section>
      </CardContent>
    </Card>
  );
}

function formatGuardrailKind(kind: string) {
  const cleaned = kind.trim().replaceAll("_", " ");
  return cleaned ? cleaned.replace(/^\w/, (character) => character.toUpperCase()) : "Safety";
}
