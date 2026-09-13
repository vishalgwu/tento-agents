import Link from "next/link";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardFooter, CardHeader, CardTitle } from "@/components/ui/card";

export default function NotFound() {
  return (
    <main className="mx-auto grid min-h-screen w-full max-w-lg place-items-center px-6 py-10">
      <Card className="w-full">
        <CardHeader>
          <CardTitle>Page unavailable</CardTitle>
          <CardDescription>
            The page does not exist, or the link is invalid or expired.
          </CardDescription>
        </CardHeader>
        <CardContent className="text-sm leading-6 text-muted-foreground">
          Vendor links do not reveal validation details, so a failed link stays private.
        </CardContent>
        <CardFooter>
          <Button render={<Link href="/" />} variant="outline">Go to Resident OS</Button>
        </CardFooter>
      </Card>
    </main>
  );
}
