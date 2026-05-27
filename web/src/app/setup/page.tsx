"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { apiClient } from "@/lib/api/client";
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
import { Eye, EyeOff, LayoutGrid } from "lucide-react";

/**
 * First-run setup page — shown when no users exist in the database.
 *
 * Collects name, email, and password.  Submits to POST /setup which
 * creates the first household + admin account, sends a verification email,
 * and returns a pending response.  The user then continues to /verify-email
 * and /onboarding for household naming, theme, and nav customization.
 */
export default function SetupPage() {
  const router = useRouter();

  const [displayName, setDisplayName]         = useState("");
  const [email, setEmail]                     = useState("");
  const [password, setPassword]               = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [showPw, setShowPw]                   = useState(false);
  const [error, setError]                     = useState<string | null>(null);
  const [isPending, setIsPending]             = useState(false);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);

    if (!displayName.trim()) {
      setError("Please enter your name.");
      return;
    }
    if (password.length < 8) {
      setError("Password must be at least 8 characters.");
      return;
    }
    if (password !== confirmPassword) {
      setError("Passwords don't match.");
      return;
    }

    setIsPending(true);
    try {
      const { data, error: apiError } = await apiClient.POST("/setup", {
        body: {
          display_name: displayName.trim(),
          email: email.trim(),
          password,
        },
      });

      if (apiError || !data) {
        const detail = (apiError as { detail?: string } | undefined)?.detail;
        throw new Error(detail ?? "Setup failed. Please try again.");
      }

      // Redirect to email verification — same flow as /register
      const params = new URLSearchParams({ user_id: data.user_id, email: data.email });
      router.replace(`/verify-email?${params.toString()}`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Something went wrong.");
    } finally {
      setIsPending(false);
    }
  }

  return (
    <div className="min-h-full flex items-center justify-center p-4">
      <Card className="w-full max-w-sm">
        <CardHeader className="text-center">
          <div className="inline-flex items-center justify-center w-12 h-12 rounded-xl bg-primary/10 mx-auto mb-2">
            <LayoutGrid className="h-6 w-6 text-primary" />
          </div>
          <CardTitle>Welcome to Hearth</CardTitle>
          <CardDescription>Create your account to get started</CardDescription>
        </CardHeader>
        <CardContent>
          <form onSubmit={handleSubmit} className="space-y-4">
            <div className="space-y-1.5">
              <Label htmlFor="display_name">Your name</Label>
              <Input
                id="display_name"
                placeholder="e.g. Alex"
                value={displayName}
                onChange={(e) => setDisplayName(e.target.value)}
                autoFocus
                required
              />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="email">Email address</Label>
              <Input
                id="email"
                type="email"
                autoComplete="email"
                placeholder="you@example.com"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                required
              />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="password">Password</Label>
              <div className="relative">
                <Input
                  id="password"
                  type={showPw ? "text" : "password"}
                  autoComplete="new-password"
                  placeholder="At least 8 characters"
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  className="pr-10"
                  required
                />
                <button
                  type="button"
                  onClick={() => setShowPw((v) => !v)}
                  className="absolute right-3 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground"
                  aria-label={showPw ? "Hide password" : "Show password"}
                >
                  {showPw ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
                </button>
              </div>
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="confirm_password">Confirm password</Label>
              <Input
                id="confirm_password"
                type={showPw ? "text" : "password"}
                autoComplete="new-password"
                placeholder="Same password again"
                value={confirmPassword}
                onChange={(e) => setConfirmPassword(e.target.value)}
                required
              />
            </div>
            {error && <p className="text-sm text-destructive">{error}</p>}
            <Button type="submit" className="w-full" disabled={isPending}>
              {isPending ? "Creating account…" : "Create account"}
            </Button>
          </form>
        </CardContent>
      </Card>
    </div>
  );
}
