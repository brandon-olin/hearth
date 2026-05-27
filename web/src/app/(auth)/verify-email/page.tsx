"use client";

import { useEffect, useRef, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { apiClient } from "@/lib/api/client";
import { setAccessToken } from "@/lib/auth/token";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";

export default function VerifyEmailPage() {
  const router = useRouter();
  const params = useSearchParams();

  const userId = params.get("user_id") ?? "";
  const email = params.get("email") ?? "";

  // Six individual digit inputs for a nice OTP UX
  const [digits, setDigits] = useState<string[]>(["", "", "", "", "", ""]);
  const inputRefs = useRef<Array<HTMLInputElement | null>>([]);

  const [error, setError] = useState<string | null>(null);
  const [isPending, setIsPending] = useState(false);
  const [resendCooldown, setResendCooldown] = useState(0);
  const [resendMessage, setResendMessage] = useState<string | null>(null);

  // Redirect away if we somehow land here without params
  useEffect(() => {
    if (!userId || !email) {
      router.replace("/register");
    }
  }, [userId, email, router]);

  // Countdown timer for resend cooldown
  useEffect(() => {
    if (resendCooldown <= 0) return;
    const id = setTimeout(() => setResendCooldown((c) => c - 1), 1000);
    return () => clearTimeout(id);
  }, [resendCooldown]);

  const code = digits.join("");

  function handleDigitChange(index: number, value: string) {
    // Accept only digits; handle paste of full code
    const cleaned = value.replace(/\D/g, "");
    if (cleaned.length > 1) {
      // Pasted a multi-char string — distribute across remaining slots
      const next = [...digits];
      let slot = index;
      for (const ch of cleaned) {
        if (slot >= 6) break;
        next[slot++] = ch;
      }
      setDigits(next);
      const focusTarget = Math.min(slot, 5);
      inputRefs.current[focusTarget]?.focus();
      return;
    }
    const next = [...digits];
    next[index] = cleaned;
    setDigits(next);
    if (cleaned && index < 5) {
      inputRefs.current[index + 1]?.focus();
    }
  }

  function handleKeyDown(index: number, e: React.KeyboardEvent<HTMLInputElement>) {
    if (e.key === "Backspace" && !digits[index] && index > 0) {
      inputRefs.current[index - 1]?.focus();
    }
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (code.length < 6) {
      setError("Please enter all 6 digits.");
      return;
    }
    setError(null);
    setIsPending(true);
    try {
      const { data, error: apiError } = await apiClient.POST("/auth/verify-email", {
        body: { user_id: userId, code },
      });

      if (apiError || !data) {
        const detail = (apiError as { detail?: string } | undefined)?.detail;
        throw new Error(detail ?? "Verification failed. Please try again.");
      }

      setAccessToken(data.access_token);
      // Always land on /onboarding after a fresh verification.
      // The onboarding page itself redirects to / if the user has already
      // completed it, so returning users who somehow land here are safe.
      window.location.replace("/onboarding");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Verification failed.");
      // Clear digits so the user can re-enter
      setDigits(["", "", "", "", "", ""]);
      inputRefs.current[0]?.focus();
    } finally {
      setIsPending(false);
    }
  }

  async function handleResend() {
    if (resendCooldown > 0 || !email) return;
    setResendMessage(null);
    try {
      await apiClient.POST("/auth/resend-verification", {
        body: { email },
      });
      setResendMessage("A new code has been sent.");
      setResendCooldown(60);
    } catch {
      setResendMessage("Could not resend — please try again shortly.");
    }
  }

  return (
    <div className="min-h-full flex items-center justify-center p-4">
      <Card className="w-full max-w-sm">
        <CardHeader>
          <CardTitle>Check your email</CardTitle>
          <CardDescription>
            We sent a 6-digit code to{" "}
            <span className="font-medium text-foreground">{email}</span>
          </CardDescription>
        </CardHeader>
        <CardContent>
          <form onSubmit={handleSubmit} className="space-y-5">
            {/* OTP digit inputs */}
            <div className="flex gap-2 justify-center">
              {digits.map((digit, i) => (
                <Input
                  key={i}
                  ref={(el) => { inputRefs.current[i] = el; }}
                  type="text"
                  inputMode="numeric"
                  pattern="[0-9]*"
                  maxLength={6}
                  value={digit}
                  onChange={(e) => handleDigitChange(i, e.target.value)}
                  onKeyDown={(e) => handleKeyDown(i, e)}
                  className="w-10 text-center text-lg font-mono px-0"
                  autoComplete={i === 0 ? "one-time-code" : "off"}
                  autoFocus={i === 0}
                />
              ))}
            </div>

            {error && (
              <p className="text-sm text-destructive text-center">{error}</p>
            )}

            <Button type="submit" className="w-full" disabled={isPending || code.length < 6}>
              {isPending ? "Verifying…" : "Verify email"}
            </Button>

            <div className="text-center space-y-1">
              <button
                type="button"
                onClick={handleResend}
                disabled={resendCooldown > 0}
                className="text-sm text-muted-foreground underline underline-offset-4 hover:text-foreground disabled:no-underline disabled:cursor-not-allowed disabled:opacity-50"
              >
                {resendCooldown > 0
                  ? `Resend in ${resendCooldown}s`
                  : "Didn't get it? Resend code"}
              </button>
              {resendMessage && (
                <p className="text-xs text-muted-foreground">{resendMessage}</p>
              )}
            </div>
          </form>
        </CardContent>
      </Card>
    </div>
  );
}
