"use client";

import { useCallback, useEffect, useRef, useState } from "react";

/**
 * useWakeLock — wraps the Screen Wake Lock API.
 *
 * Returns:
 *   isActive   — whether the wake lock is currently held
 *   isSupported — whether the browser supports the API
 *   toggle     — request or release the lock
 */
export function useWakeLock() {
  const [isActive, setIsActive] = useState(false);
  const sentinelRef = useRef<WakeLockSentinel | null>(null);

  const isSupported =
    typeof navigator !== "undefined" && "wakeLock" in navigator;

  const release = useCallback(async () => {
    if (sentinelRef.current) {
      await sentinelRef.current.release();
      sentinelRef.current = null;
    }
    setIsActive(false);
  }, []);

  const request = useCallback(async () => {
    if (!isSupported) return;
    try {
      const sentinel = await navigator.wakeLock.request("screen");
      sentinelRef.current = sentinel;
      setIsActive(true);

      // The browser releases the lock automatically when the tab is hidden.
      // Listen for that so our state stays in sync.
      sentinel.addEventListener("release", () => {
        sentinelRef.current = null;
        setIsActive(false);
      });
    } catch {
      // User denied or API unavailable — silently no-op.
      setIsActive(false);
    }
  }, [isSupported]);

  const toggle = useCallback(() => {
    if (isActive) {
      release();
    } else {
      request();
    }
  }, [isActive, release, request]);

  // Re-acquire the lock when the user returns to the tab (browsers drop it
  // on tab switch / screen lock and don't re-acquire automatically).
  useEffect(() => {
    const handleVisibility = () => {
      if (document.visibilityState === "visible" && isActive && !sentinelRef.current) {
        request();
      }
    };
    document.addEventListener("visibilitychange", handleVisibility);
    return () => document.removeEventListener("visibilitychange", handleVisibility);
  }, [isActive, request]);

  // Release on unmount.
  useEffect(() => {
    return () => {
      sentinelRef.current?.release().catch(() => {});
    };
  }, []);

  return { isActive, isSupported, toggle };
}
