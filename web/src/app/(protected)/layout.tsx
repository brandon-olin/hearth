"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";
import { useAuth } from "@/lib/auth/context";
import { Shell } from "@/components/shell/shell";
import { FocusModeProvider } from "@/lib/focus/context";
import { FocusOverlay } from "@/components/focus/focus-overlay";
import { LocaleDetectedBanner } from "@/components/locale-detected-banner";
import { CurrentResourceProvider } from "@/lib/chat-context/current-resource";

export default function ProtectedLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  const { user, isLoading, localeAutoDetected, dismissLocaleNotice } = useAuth();
  const router = useRouter();

  useEffect(() => {
    if (isLoading) return;
    if (!user) {
      router.replace("/login");
    } else if (user.force_password_change) {
      // Admin-created accounts must set a real password before accessing the app.
      router.replace("/set-password");
    }
  }, [isLoading, user, router]);

  if (isLoading) {
    return (
      <div className="min-h-full flex items-center justify-center">
        <div className="text-muted-foreground text-sm">Loading…</div>
      </div>
    );
  }

  if (!user) return null;

  return (
    <FocusModeProvider>
      <CurrentResourceProvider>
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
