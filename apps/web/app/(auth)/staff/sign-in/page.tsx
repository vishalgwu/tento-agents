import Link from "next/link";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardFooter, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";

export const metadata = { title: "Staff sign-in" };

export default function StaffSignInPage() {
  return (
    <main className="mx-auto grid min-h-screen w-full max-w-md place-items-center px-6 py-10">
      <Card className="w-full">
        <CardHeader>
          <p className="font-mono text-xs font-medium tracking-[0.14em] text-primary uppercase">Staff access</p>
          <CardTitle>Password and one-time password</CardTitle>
          <CardDescription>
            Managers, owners, and technicians require a password plus time-based one-time password. Verification is not connected in this scaffold.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <form className="grid gap-4" noValidate>
            <div className="grid gap-2">
              <Label htmlFor="staff-email">Work email</Label>
              <Input autoComplete="username" id="staff-email" name="email" placeholder="you@company.com" type="email" />
            </div>
            <div className="grid gap-2">
              <Label htmlFor="staff-password">Password</Label>
              <Input autoComplete="current-password" id="staff-password" name="password" type="password" />
            </div>
            <div className="grid gap-2">
              <Label htmlFor="staff-totp">One-time password</Label>
              <Input autoComplete="one-time-code" id="staff-totp" inputMode="numeric" name="totp" pattern="[0-9]*" type="text" />
            </div>
            <Button aria-describedby="staff-auth-note" disabled type="submit">Sign in</Button>
          </form>
          <p className="mt-3 text-xs leading-5 text-muted-foreground" id="staff-auth-note">
            Disabled by design: password and TOTP values are never submitted or stored by this foundation.
          </p>
        </CardContent>
        <CardFooter>
          <Button render={<Link href="/manage" />} variant="link">Return to manager workspace</Button>
        </CardFooter>
      </Card>
    </main>
  );
}
