"use client";

import { useState, Suspense } from "react";
import { useSearchParams } from "next/navigation";
import Link from "next/link";
import { apiBaseUrl } from "@/lib/api/client";
import { setAccessToken } from "@/lib/auth/token";
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

function ResetPasswordForm() {
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
          Invalid or missing reset token. Please request a new password reset link.
        </p>
        <div className="mt-4">
          <Link href="/forgot-password">
            <Button variant="outline" className="w-full">Request new link</Button>
          </Link>
        </div>
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
      const res = await fetch(`${apiBaseUrl}/auth/reset-password`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        credentials: "include",
        body: JSON.stringify({ token, new_password: password, auto_login: true }),
      });
      if (!res.ok) {
        const body = await res.json().catch(() => ({}));
        throw new Error((body as { detail?: string }).detail ?? "Failed to reset password");
      }
      const data = await res.json() as { access_token: string };
      setAccessToken(data.access_token);
      window.location.replace("/");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to reset password");
    } finally {
      setIsPending(false);
    }
  }

  return (
    <CardContent>
      <form onSubmit={handleSubmit} className="space-y-4">
        <div className="space-y-1.5">
          <Label htmlFor="password">New password</Label>
          <Input
            id="password"
            type="password"
            autoComplete="new-password"
            placeholder="8+ chars, number & symbol"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            required
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
          {isPending ? "Saving…" : "Set new password"}
        </Button>
        <p className="text-sm text-center text-muted-foreground">
          <Link
            href="/login"
            className="text-foreground underline underline-offset-4 hover:text-primary"
          >
            Back to sign in
          </Link>
        </p>
      </form>
    </CardContent>
  );
}

export default function ResetPasswordPage() {
  return (
    <div className="min-h-full flex items-center justify-center p-4">
      <Card className="w-full max-w-sm">
        <CardHeader>
          <CardTitle>Set new password</CardTitle>
          <CardDescription>Choose a new password for your account.</CardDescription>
        </CardHeader>
        {/* useSearchParams requires Suspense in Next.js App Router */}
        <Suspense fallback={<CardContent><p className="text-sm text-muted-foreground">Loading…</p></CardContent>}>
          <ResetPasswordForm />
        </Suspense>
      </Card>
    </div>
  );
}
