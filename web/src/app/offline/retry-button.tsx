"use client";

import { Button } from "@/components/ui/button";

/**
 * Forces a full navigation rather than a client-side route change. While the
 * offline page is being served by the service worker the Next.js router can't
 * fetch RSC payloads, so only a hard navigation actually retries the network.
 */
export function RetryButton() {
  return (
    <Button className="min-h-11" onClick={() => window.location.assign("/")}>
      Try again
    </Button>
  );
}
