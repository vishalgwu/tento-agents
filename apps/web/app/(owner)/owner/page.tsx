import { PageFrame } from "@/components/page-frame";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";

export const metadata = { title: "Owner workspace" };

export default function OwnerWorkspacePage() {
  return (
    <PageFrame
      description="A governance-oriented home for measured outcomes and audit coverage. Metrics wait for a reproducible evaluation plan and real authorised data."
      eyebrow="Owner workspace"
      title="Operational visibility without invented metrics."
    >
      <Card className="max-w-3xl">
        <CardHeader>
          <Badge variant="outline">Evaluation required</Badge>
          <CardTitle>Portfolio reporting is intentionally empty</CardTitle>
          <CardDescription>
            Resident OS will not present performance numbers until their source, calculation, evaluation window, and audit coverage are documented.
          </CardDescription>
        </CardHeader>
        <CardContent className="grid gap-3 text-sm leading-6 text-muted-foreground sm:grid-cols-3">
          <p><span className="font-mono text-foreground">01</span> Source-controlled data</p>
          <p><span className="font-mono text-foreground">02</span> Reproducible calculation</p>
          <p><span className="font-mono text-foreground">03</span> Auditable coverage</p>
        </CardContent>
      </Card>
    </PageFrame>
  );
}
