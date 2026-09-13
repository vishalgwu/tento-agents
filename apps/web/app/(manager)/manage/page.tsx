import { PageFrame } from "@/components/page-frame";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { DecisionMarker, EvidenceClaim, EvidenceRail, StatusLamp } from "@resident-os/ui";

export const metadata = { title: "Manager workspace" };

const evidence = [
  {
    excerpt: "This is a component interaction example, not an operational claim or live ticket record.",
    id: "scope",
    label: "Interface boundary",
  },
  {
    excerpt: "Human authorisation remains required for any material dispatch decision.",
    id: "authority",
    label: "Operating rule",
  },
] as const;

export default function ManagerWorkspacePage() {
  return (
    <PageFrame
      description="The decision review surface keeps a machine proposal and a human authorisation visibly distinct. Live dispatch remains outside the current API contract."
      eyebrow="Manager workspace"
      title="Review evidence before authorising work."
    >
      <div className="grid gap-5 lg:grid-cols-[minmax(0,1.25fr)_0.75fr]">
        <EvidenceRail items={evidence}>
          <p>
            This card demonstrates how a <EvidenceClaim evidenceId="scope">supported claim</EvidenceClaim> exposes its citation without treating an example as a real ticket. A <EvidenceClaim evidenceId="authority">person must authorise</EvidenceClaim> material work.
          </p>
        </EvidenceRail>

        <Card size="sm">
          <CardHeader>
            <Badge variant="outline">Display sample</Badge>
            <CardTitle>Decision provenance</CardTitle>
            <CardDescription>Semantics are explicit, not colour-only.</CardDescription>
          </CardHeader>
          <CardContent className="grid gap-3">
            <StatusLamp priority="unassigned" />
            <DecisionMarker authority="machine" />
            <DecisionMarker authority="human" />
          </CardContent>
        </Card>
      </div>
    </PageFrame>
  );
}
