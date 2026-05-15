"use client";

import { useEffect, useRef, useState } from "react";
import { usePathname, useRouter } from "next/navigation";
import { Loader2 } from "lucide-react";
import { apiClient } from "@/lib/api/client";

type Status = "loading" | "needs_setup" | "ready";

/**
 * Checks /setup/status on every mount and redirects accordingly:
 *   - needs_setup=true  + not on /setup  → replace("/setup")
 *   - needs_setup=false + on /setup      → replace("/")
 *
 * Uses apiClient so the correct base URL is used in both web and Tauri builds
 * (raw fetch("/api/…") doesn't work in Tauri's static export — no Next.js proxy).
 *
 * Renders a full-screen spinner while the check is in flight so there's no
 * flash of whichever page was requested before the redirect fires.
 */
export function SetupGuard({ children }: { children: React.ReactNode }) {
  const [status, setStatus] = useState<Status>("loading");
  const pathname = usePathname();
  const router = useRouter();
  const checkedRef = useRef(false);

  useEffect(() => {
    // Only run once per session — the status doesn't change while the app is open.
    if (checkedRef.current) return;
    checkedRef.current = true;

    apiClient.GET("/setup/status")
      .then(({ data }) => {
        if (data?.needs_setup) {
          if (pathname !== "/setup") router.replace("/setup");
          setStatus("needs_setup");
        } else {
          if (pathname === "/setup") router.replace("/");
          setStatus("ready");
        }
      })
      .catch(() => {
        // If the API is unreachable, don't block the UI — fall through.
        setStatus("ready");
      });
  // Run once on mount; pathname is captured via closure.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Keep the spinner up until we've safely landed on the right page.
  // Without this, the protected layout mounts as a child while the router is
  // still navigating to /setup, sees no auth token, and fires its own
  // router.replace("/login") which wins the race.
  if (status === "loading" || (status === "needs_setup" && pathname !== "/setup")) {
    return (
      <div className="min-h-screen flex items-center justify-center text-muted-foreground">
        <Loader2 className="h-5 w-5 animate-spin" />
      </div>
    );
  }

  return <>{children}</>;
}
