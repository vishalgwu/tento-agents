import Link from "next/link";

import { PageFrame } from "@/components/page-frame";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardFooter, CardHeader, CardTitle } from "@/components/ui/card";
import { StatusLamp } from "@resident-os/ui";

export const metadata = { title: "Resident workspace" };

export default function ResidentWorkspacePage() {
  return (
    <PageFrame
      description="A mobile-first starting point for residents. Ticket creation is held until the API publishes its mutation contract."
      eyebrow="Resident workspace"
      title="Your maintenance, explained plainly."
    >
      <div className="grid gap-5 lg:grid-cols-[1.25fr_0.75fr]">
        <Card>
          <CardHeader>
            <Badge variant="outline">Resident report</Badge>
            <CardTitle>Report a maintenance issue</CardTitle>
            <CardDescription>
              Use the guided report flow to describe an issue, select photos, and choose access preferences. Ticket creation remains unavailable until its tenant-safe POST contract is accepted.
            </CardDescription>
          </CardHeader>
          <CardContent className="text-sm leading-6 text-muted-foreground">
            The form preserves a clear boundary: it does not upload media, queue a model call, or invent an acknowledgement while the write API is pending.
          </CardContent>
          <CardFooter>
            <Button render={<Link href="/app/report" />}>
              Start a report
            </Button>
          </CardFooter>
        </Card>

        <Card size="sm">
          <CardHeader>
            <CardTitle>How priority is shown</CardTitle>
            <CardDescription>Colour is always paired with a written label.</CardDescription>
          </CardHeader>
          <CardContent className="grid gap-3">
            <StatusLamp priority="p1" />
            <StatusLamp priority="p2" />
            <StatusLamp priority="p3" />
          </CardContent>
        </Card>
      </div>
    </PageFrame>
  );
}
