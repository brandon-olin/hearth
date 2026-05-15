"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";
import { useAuth } from "@/lib/auth/context";
import { Shell } from "@/components/shell/shell";
import { FocusModeProvider } from "@/lib/focus/context";
import { FocusOverlay } from "@/components/focus/focus-overlay";
import { LocaleDetectedBanner } from "@/components/locale-detected-banner";

export default function ProtectedLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  const { user, isLoading, localeAutoDetected, dismissLocaleNotice } = useAuth();
  const router = useRouter();

  useEffect(() => {
    if (!isLoading && !user) {
      router.replace("/login");
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
      <Shell>{children}</Shell>
      <FocusOverlay />
      {localeAutoDetected && (
        <LocaleDetectedBanner
          timezone={user.timezone ?? ""}
          onDismiss={dismissLocaleNotice}
        />
      )}
    </FocusModeProvider>
  );
}
