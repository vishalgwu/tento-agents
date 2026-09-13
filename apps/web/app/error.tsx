"use client";

import { useEffect } from "react";

import { Button } from "@/components/ui/button";

export default function ErrorPage({ error, reset }: { error: Error & { digest?: string }; reset: () => void }) {
  useEffect(() => {
    console.error(error);
  }, [error]);

  return (
    <main className="mx-auto grid min-h-screen max-w-lg place-items-center px-6 text-center">
      <div>
        <p className="font-mono text-xs font-medium tracking-[0.14em] text-primary uppercase">Resident OS</p>
        <h1 className="mt-3 text-2xl font-medium tracking-tight">This page could not be loaded.</h1>
        <p className="mt-3 text-sm leading-6 text-muted-foreground">No operational action was taken. You can safely retry.</p>
        <Button className="mt-6" onClick={reset}>Try again</Button>
      </div>
    </main>
  );
}
