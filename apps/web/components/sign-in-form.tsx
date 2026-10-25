"use client";
import Link from "next/link";
import Image from "next/image";
import { useState, type FormEvent } from "react";
import { useRouter } from "next/navigation";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { workspaces, type Workspace } from "@/lib/workspaces";

export function SignInForm({ workspace }: { workspace: Workspace }) {
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
        body: JSON.stringify({
          email: data.get("email"),
          password: data.get("password"),
          workspace,
        }),
      });
      if (!response.ok)
        throw new Error(
          response.status === 403
            ? "Your account does not have access to this workspace. Choose the workspace assigned to you."
            : response.status === 401
              ? "Check your email and password."
              : "Sign-in is unavailable. Please try again later.",
        );
      const result = await response.json();
      if (result.destination !== workspaces[workspace].path)
        throw new Error("Unable to verify workspace access.");
      router.push(result.destination);
      router.refresh();
    } catch (failure) {
      setError(
        failure instanceof Error ? failure.message : "Unable to sign in.",
      );
    } finally {
      setBusy(false);
    }
  }
  return (
    <div className="signin-layout">
      <form onSubmit={submit} className="signin-form" aria-busy={busy}>
        <p className="eyebrow">A familiar place to begin</p>
        <Label htmlFor="email">Email address</Label>
        <Input
          id="email"
          name="email"
          type="email"
          autoComplete="username"
          required
          disabled={busy}
        />
        <Label htmlFor="password">Password</Label>
        <Input
          id="password"
          name="password"
          type="password"
          autoComplete="current-password"
          required
          disabled={busy}
        />
        <Button type="submit" disabled={busy}>
          {busy ? "Signing in…" : `Sign in to ${workspaces[workspace].name}`}
        </Button>
        {error && (
          <p role="alert" className="text-sm text-destructive">
            {error}
          </p>
        )}
        <p className="text-sm text-muted-foreground">
          Access comes from your organization's account assignment.
        </p>
        <Link href="/#workspaces" className="text-sm underline">
          Choose another workspace
        </Link>
      </form>
      <aside className="signin-story" aria-label="Tento community">
        <Image
          src="/images/tento-courtyard.png"
          alt=""
          fill
          sizes="(max-width: 760px) 88vw, 50vw"
        />
        <div className="signin-story-copy">
          <p>THOUGHTFULLY CONNECTED</p>
          <h2>
            Your community.
            <br />
            <em>A little closer.</em>
          </h2>
        </div>
      </aside>
    </div>
  );
}
