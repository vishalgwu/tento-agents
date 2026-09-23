import { notFound } from "next/navigation";

import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { DecisionMarker } from "@resident-os/ui";
import { verifyVendorLink } from "@/lib/vendor-link";

export const metadata = { title: "Vendor work order" };
export const runtime = "nodejs";
export const dynamic = "force-dynamic";

type VendorLinkPageProps = {
  params: Promise<{ token: string }>;
};

export default async function VendorLinkPage({ params }: VendorLinkPageProps) {
  const { token } = await params;
  const claim = verifyVendorLink(token);
  if (!claim) {
    notFound();
  }
  const expiry = new Intl.DateTimeFormat("en-US", {
    dateStyle: "medium",
    timeStyle: "short",
    timeZone: "UTC",
  }).format(new Date(claim.expiresAt * 1_000));

  return (
    <main className="mx-auto grid min-h-screen w-full max-w-2xl place-items-center px-6 py-10">
      <Card className="w-full">
        <CardHeader>
          <p className="font-mono text-xs font-medium tracking-[0.14em] text-primary uppercase">Vendor work order</p>
          <CardTitle>Verified link, no account required</CardTitle>
          <CardDescription>
            This expiring link was verified on the server. Job details and status mutations remain unavailable until the authorised dispatch API is published.
          </CardDescription>
        </CardHeader>
        <CardContent className="grid gap-4">
          <DecisionMarker authority="human" label="Authorised dispatch context" />
          <dl className="grid gap-3 rounded-lg border bg-secondary/50 p-4 text-sm">
            <div className="grid gap-1 sm:grid-cols-[9rem_1fr] sm:gap-4">
              <dt className="text-muted-foreground">Work order</dt>
              <dd className="font-mono break-all">{claim.workOrderId}</dd>
            </div>
            <div className="grid gap-1 sm:grid-cols-[9rem_1fr] sm:gap-4">
              <dt className="text-muted-foreground">Vendor reference</dt>
              <dd className="font-mono break-all">{claim.vendorId}</dd>
            </div>
            <div className="grid gap-1 sm:grid-cols-[9rem_1fr] sm:gap-4">
              <dt className="text-muted-foreground">Link expiry</dt>
              <dd>{expiry} UTC</dd>
            </div>
          </dl>
        </CardContent>
      </Card>
    </main>
  );
}
