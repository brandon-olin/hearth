"use client";

import { useState, Suspense } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import Link from "next/link";
import { apiBaseUrl } from "@/lib/api/client";
import { validatePassword } from "@/lib/auth/password-policy";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Button } from "@/components/ui/button";

function AcceptInviteForm() {
  const router       = useRouter();
  const searchParams = useSearchParams();
  const token        = searchParams.get("token") ?? "";

  const [password, setPassword] = useState("");
  const [confirm, setConfirm]   = useState("");
  const [error, setError]       = useState<string | null>(null);
  const [isPending, setIsPending] = useState(false);

  if (!token) {
    return (
      <CardContent>
        <p className="text-sm text-destructive">
          This invite link is invalid or has already been used. Ask the household admin to send a new invite.
        </p>
      </CardContent>
    );
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);

    const pwError = validatePassword(password);
    if (pwError) { setError(pwError); return; }
    if (password !== confirm) {
      setError("Passwords don't match.");
      return;
    }

    setIsPending(true);
    try {
      // Reuse the same reset-password endpoint — the token mechanism is identical.
      const res = await fetch(`${apiBaseUrl}/auth/reset-password`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ token, new_password: password }),
      });
      if (!res.ok) {
        const body = await res.json().catch(() => ({}));
        const detail = (body as { detail?: string }).detail;
        if (res.status === 400 || res.status === 422) {
          throw new Error(detail ?? "This invite link has expired or already been used.");
        }
        throw new Error(detail ?? "Failed to set password. Please try again.");
      }
      // Success — log the user in via the login page isn't needed; instead
      // redirect to /onboarding. The app will prompt login if no session exists,
      // so we redirect to /login with a flag so it can forward on after auth.
      router.replace("/login?next=/onboarding&invited=1");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to set password.");
    } finally {
      setIsPending(false);
    }
  }

  return (
    <CardContent>
      <form onSubmit={handleSubmit} className="space-y-4">
        <div className="space-y-1.5">
          <Label htmlFor="password">Password</Label>
          <Input
            id="password"
            type="password"
            autoComplete="new-password"
            placeholder="At least 8 characters"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            required
            minLength={8}
            autoFocus
          />
        </div>
        <div className="space-y-1.5">
          <Label htmlFor="confirm">Confirm password</Label>
          <Input
            id="confirm"
            type="password"
            autoComplete="new-password"
            value={confirm}
            onChange={(e) => setConfirm(e.target.value)}
            required
          />
        </div>
        {error && (
          <p className="text-sm text-destructive">{error}</p>
        )}
        <Button type="submit" className="w-full" disabled={isPending}>
          {isPending ? "Setting up…" : "Set password & continue"}
        </Button>
      </form>
    </CardContent>
  );
}

export default function AcceptInvitePage() {
  return (
    <div className="min-h-full flex items-center justify-center p-4">
      <Card className="w-full max-w-sm">
        <CardHeader>
          <CardTitle>You&apos;re invited to Hearth</CardTitle>
          <CardDescription>Choose a password to set up your account.</CardDescription>
        </CardHeader>
        {/* useSearchParams requires Suspense in Next.js App Router */}
        <Suspense fallback={<CardContent><p className="text-sm text-muted-foreground">Loading…</p></CardContent>}>
          <AcceptInviteForm />
        </Suspense>
      </Card>
    </div>
  );
}
