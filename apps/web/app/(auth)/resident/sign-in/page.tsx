"use client";

import Link from "next/link";
import { useState, type FormEvent } from "react";
import { useRouter } from "next/navigation";
import { PageFrame } from "@/components/page-frame";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";

export default function SignInPage() {
  const router = useRouter();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (busy) return;
    const data = new FormData(event.currentTarget);
    setBusy(true);
    setError(null);
    try {
      const response = await fetch("/api/session", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email: data.get("email"), password: data.get("password") }),
      });
      if (!response.ok) {
        throw new Error(response.status === 401
          ? "Check your email and password."
          : "Sign-in is unavailable. Please try again later.");
      }
      router.push("/app/report");
      router.refresh();
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : "Unable to sign in.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <PageFrame eyebrow="Account access" title="Sign in" description="Use your community account to access the maintenance assistant.">
      <form onSubmit={submit} className="grid max-w-md gap-4" aria-busy={busy}>
        <Label htmlFor="email">Email address</Label>
        <Input id="email" name="email" type="email" autoComplete="username" required disabled={busy} />
        <Label htmlFor="password">Password</Label>
        <Input id="password" name="password" type="password" autoComplete="current-password" required disabled={busy} />
        <Button disabled={busy} type="submit">{busy ? "Signing in…" : "Sign in"}</Button>
        {error ? <p role="alert" className="text-sm text-destructive">{error}</p> : null}
        <Link href="/app/report" className="text-sm underline">Return to assistant</Link>
      </form>
    </PageFrame>
  );
}
