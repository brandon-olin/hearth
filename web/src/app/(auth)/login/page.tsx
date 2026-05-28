"use client";

import { useState, Suspense } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import Link from "next/link";
import { useAuth } from "@/lib/auth/context";
import { useAppConfig } from "@/lib/app-config";
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

function LoginForm() {
  const { login } = useAuth();
  const router    = useRouter();
  const appConfig = useAppConfig();
  const searchParams = useSearchParams();

  // ?next= is used by /accept-invite to send the user to /onboarding after login.
  // Sanitise to relative paths only to prevent open redirect.
  const rawNext = searchParams.get("next") ?? "";
  const nextPath = rawNext.startsWith("/") ? rawNext : "/";

  const [email, setEmail]       = useState("");
  const [password, setPassword] = useState("");
  const [error, setError]       = useState<string | null>(null);
  const [isPending, setIsPending] = useState(false);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setIsPending(true);
    try {
      await login(email, password);
      router.replace(nextPath);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Login failed");
    } finally {
      setIsPending(false);
    }
  }

  return (
    <CardContent>
      <form onSubmit={handleSubmit} className="space-y-4">
        <div className="space-y-1.5">
          <Label htmlFor="email">Email</Label>
          <Input
            id="email"
            type="email"
            autoComplete="email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            required
            autoFocus
          />
        </div>
        <div className="space-y-1.5">
          <div className="flex items-center justify-between">
            <Label htmlFor="password">Password</Label>
            {appConfig.email_enabled && (
              <Link
                href="/forgot-password"
                className="text-xs text-muted-foreground underline underline-offset-4 hover:text-primary"
              >
                Forgot password?
              </Link>
            )}
          </div>
          <Input
            id="password"
            type="password"
            autoComplete="current-password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            required
          />
        </div>
        {error && (
          <p className="text-sm text-destructive">{error}</p>
        )}
        <Button type="submit" className="w-full" disabled={isPending}>
          {isPending ? "Signing in…" : "Sign in"}
        </Button>
        <p className="text-sm text-center text-muted-foreground">
          Don&apos;t have an account?{" "}
          <Link href="/register" className="text-foreground underline underline-offset-4 hover:text-primary">
            Create one
          </Link>
        </p>
      </form>
    </CardContent>
  );
}

export default function LoginPage() {
  return (
    <div className="min-h-full flex items-center justify-center p-4">
      <Card className="w-full max-w-sm">
        <CardHeader>
          <CardTitle>Hearth</CardTitle>
          <CardDescription>Sign in to your account</CardDescription>
        </CardHeader>
        {/* useSearchParams requires Suspense in Next.js App Router */}
        <Suspense fallback={<CardContent><p className="text-sm text-muted-foreground">Loading…</p></CardContent>}>
          <LoginForm />
        </Suspense>
      </Card>
    </div>
  );
}
