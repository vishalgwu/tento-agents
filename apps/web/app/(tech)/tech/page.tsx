import Link from "next/link";

import { PageFrame } from "@/components/page-frame";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardFooter, CardHeader, CardTitle } from "@/components/ui/card";
import { DecisionMarker } from "@resident-os/ui";

export const metadata = { title: "Technician workspace" };

export default function TechnicianWorkspacePage() {
  return (
    <PageFrame
      description="A technician sees only the context needed after a manager has authorised work. The current foundation does not expose jobs or allow work-status changes."
      eyebrow="Technician workspace"
      title="Arrive with the authorised context."
    >
      <Card className="max-w-3xl">
        <CardHeader>
          <DecisionMarker authority="human" label="Human authorisation required" />
          <CardTitle>No active jobs are displayed</CardTitle>
          <CardDescription>
            Job reads, scopes, work completion, and vendor coordination need explicit API contracts and role policy before this workspace can show operational data.
          </CardDescription>
        </CardHeader>
        <CardContent className="text-sm leading-6 text-muted-foreground">
          Staff authentication is modelled separately from resident access: password plus time-based one-time password, with no session created by this scaffold.
        </CardContent>
        <CardFooter>
          <Button render={<Link href="/staff/sign-in" />} variant="outline">
            View staff sign-in
          </Button>
        </CardFooter>
      </Card>
    </PageFrame>
  );
}
