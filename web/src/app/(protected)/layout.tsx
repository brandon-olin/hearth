"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";
import { useAuth } from "@/lib/auth/context";
import { Shell } from "@/components/shell/shell";
import { FocusModeProvider } from "@/lib/focus/context";
import { FocusOverlay } from "@/components/focus/focus-overlay";
import { LocaleDetectedBanner } from "@/components/locale-detected-banner";
import { CurrentResourceProvider } from "@/lib/chat-context/current-resource";
import { LoadingScreen } from "@/components/ui/loading-screen";
import { InvalidationStream } from "@/lib/realtime/invalidation-stream";

export default function ProtectedLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  const { user, isLoading, localeAutoDetected, dismissLocaleNotice } = useAuth();
  const router = useRouter();

  // onboarding-001: the wizard flag is per member, and only an explicit `false`
  // sends someone to it. A missing key means an account that predates the
  // wizard — established users must never be dropped back into onboarding. It
  // is set to false at signup and when an admin invites a new member, so a
  // partner joining a household that is already full of data still gets asked
  // what they care about.
  const needsWizard =
    (user?.preferences as Record<string, unknown> | null | undefined)?.[
      "onboarding_completed"
    ] === false;

  useEffect(() => {
    if (isLoading) return;
    if (!user) {
      router.replace("/login");
    } else if (user.force_password_change) {
      // Admin-created accounts must set a real password before accessing the app.
      router.replace("/set-password");
    } else if (needsWizard) {
      router.replace("/welcome");
    }
  }, [isLoading, user, needsWizard, router]);

  if (isLoading) {
    return <LoadingScreen />;
  }

  if (!user) return null;

  // Hold the loading screen while the router navigates to /welcome rather than
  // letting the shell mount and flash a dashboard the user is about to leave.
  if (needsWizard) return <LoadingScreen />;

  return (
    <FocusModeProvider>
      <CurrentResourceProvider>
        {/* realtime-001: subscribe to the SSE invalidation stream so writes on
            other devices refetch here. Renders nothing. */}
        <InvalidationStream />
        <Shell>{children}</Shell>
        <FocusOverlay />
        {localeAutoDetected && (
          <LocaleDetectedBanner
            timezone={user.timezone ?? ""}
            onDismiss={dismissLocaleNotice}
          />
        )}
      </CurrentResourceProvider>
    </FocusModeProvider>
  );
}
