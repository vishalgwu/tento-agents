import Link from "next/link";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardFooter, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";

export const metadata = { title: "Resident sign-in" };

export default function ResidentSignInPage() {
  return (
    <main className="mx-auto grid min-h-screen w-full max-w-md place-items-center px-6 py-10">
      <Card className="w-full">
        <CardHeader>
          <p className="font-mono text-xs font-medium tracking-[0.14em] text-primary uppercase">Resident access</p>
          <CardTitle>Sign in with a magic link</CardTitle>
          <CardDescription>
            Magic-link delivery is represented here, but disabled until the identity provider and resident membership contract are connected.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <form className="grid gap-4" noValidate>
            <div className="grid gap-2">
              <Label htmlFor="resident-email">Email address</Label>
              <Input autoComplete="email" id="resident-email" name="email" placeholder="you@example.com" type="email" />
            </div>
            <Button aria-describedby="resident-auth-note" disabled type="submit">
              Send magic link
            </Button>
          </form>
          <p className="mt-3 text-xs leading-5 text-muted-foreground" id="resident-auth-note">
            Disabled by design: no email is sent and no session is persisted in this foundation.
          </p>
        </CardContent>
        <CardFooter>
          <Button render={<Link href="/app" />} variant="link">Return to resident workspace</Button>
        </CardFooter>
      </Card>
    </main>
  );
}
