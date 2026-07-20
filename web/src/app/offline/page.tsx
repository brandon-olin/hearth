import type { Metadata } from "next";
import { RetryButton } from "./retry-button";

export const metadata: Metadata = {
  title: "Offline — Hearth",
};

/**
 * Static fallback served by the service worker when a navigation request fails
 * and no cached copy of the requested page exists. Must not fetch anything —
 * it renders while the device is offline.
 */
export default function OfflinePage() {
  return (
    <main className="flex min-h-full flex-col items-center justify-center gap-4 px-6 text-center">
      <h1 className="text-2xl font-semibold">You&apos;re offline</h1>
      <p className="max-w-sm text-sm text-muted-foreground">
        Hearth can&apos;t reach the server right now. Pages you&apos;ve already opened stay
        available — reconnect to load anything new.
      </p>
      <RetryButton />
    </main>
  );
}
