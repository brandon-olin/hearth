"use client";

import { X, Globe } from "lucide-react";
import { useRouter } from "next/navigation";

interface LocaleDetectedBannerProps {
  timezone: string;
  onDismiss: () => void;
}

/**
 * Subtle toast-style banner shown once after timezone is auto-detected.
 * Appears bottom-right; links to Settings → Account so the user can review.
 */
export function LocaleDetectedBanner({ timezone, onDismiss }: LocaleDetectedBannerProps) {
  const router = useRouter();

  return (
    <div className="fixed bottom-4 right-4 z-50 flex items-start gap-3 rounded-lg border bg-card px-4 py-3 shadow-lg max-w-sm text-sm animate-in slide-in-from-bottom-2 duration-300">
      <Globe className="h-4 w-4 mt-0.5 shrink-0 text-muted-foreground" />
      <div className="flex-1 min-w-0">
        <p className="font-medium text-foreground leading-snug">Timezone detected</p>
        <p className="text-muted-foreground text-xs mt-0.5 truncate">{timezone}</p>
        <button
          type="button"
          onClick={() => { onDismiss(); router.push("/settings"); }}
          className="mt-1.5 text-xs text-primary hover:underline"
        >
          Review in Settings
        </button>
      </div>
      <button
        type="button"
        onClick={onDismiss}
        className="shrink-0 text-muted-foreground hover:text-foreground transition-colors mt-0.5"
        aria-label="Dismiss"
      >
        <X className="h-3.5 w-3.5" />
      </button>
    </div>
  );
}
