"use client";

import { useEffect } from "react";

// Tauri serves the static export from tauri://localhost, where service workers
// are unavailable — and unnecessary, since the assets are already on disk.
const isTauri = process.env.NEXT_PUBLIC_TAURI === "true";

/**
 * Registers the app-shell service worker (public/sw.js) so the installed PWA
 * opens instantly and shows the offline page instead of a blank screen.
 *
 * Mounted once from the root layout.
 */
export function ServiceWorkerRegister() {
  useEffect(() => {
    if (isTauri) return;
    if (typeof navigator === "undefined" || !("serviceWorker" in navigator)) return;

    // Registering after load keeps the SW request off the critical path.
    const register = () => {
      navigator.serviceWorker.register("/sw.js").catch((error) => {
        console.error("[hearth] service worker registration failed", error);
      });
    };

    if (document.readyState === "complete") {
      register();
      return;
    }

    window.addEventListener("load", register);
    return () => window.removeEventListener("load", register);
  }, []);

  return null;
}
