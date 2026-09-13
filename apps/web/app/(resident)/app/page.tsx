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
            <Badge variant="outline">Phase 1 boundary</Badge>
            <CardTitle>Report a maintenance issue</CardTitle>
            <CardDescription>
              The current API deliberately supports ticket reads only. No web form can create a ticket until a documented POST contract, tenant policy, and evidence requirements are approved.
            </CardDescription>
          </CardHeader>
          <CardContent className="text-sm leading-6 text-muted-foreground">
            Sign in with a resident magic link when the identity provider is connected. This scaffold does not send email, store a session, or collect issue details.
          </CardContent>
          <CardFooter>
            <Button render={<Link href="/resident/sign-in" />} variant="outline">
              View magic-link sign-in
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
