import Link from "next/link";
import { PageFrame } from "@/components/page-frame";
import { Button } from "@/components/ui/button";

export default function HomePage() {
  return (
    <PageFrame eyebrow="Resident OS" title="Maintenance help, clearly explained." description="Report an issue, follow its assessment, and see the current status of your requests.">
      <div className="flex flex-wrap gap-4">
        <Button render={<Link href="/app/report" />}>Report an issue</Button>
        <Button variant="outline" render={<Link href="/app/tickets" />}>Your requests</Button>
      </div>
    </PageFrame>
  );
}
