"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";
import { Loader2 } from "lucide-react";

/**
 * Legacy alias for the first-run wizard, which lives at /welcome (onboarding-001).
 *
 * Kept because this path is baked into places we can't retroactively edit:
 * invite emails already in people's inboxes, and the API docstrings that
 * describe the post-verification redirect. Anyone landing here is bounced to
 * the real wizard, which decides for itself whether they still need it.
 */
export default function OnboardingRedirectPage() {
  const router = useRouter();

  useEffect(() => {
    router.replace("/welcome");
  }, [router]);

  return (
    <div className="min-h-screen flex items-center justify-center text-muted-foreground">
      <Loader2 className="h-5 w-5 animate-spin" />
    </div>
  );
}
