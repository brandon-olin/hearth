"use client";

import { useEffect } from "react";

// Tauri serves the static export from tauri://localhost, where service workers
// are unavailable — and unnecessary, since the assets are already on disk.
const isTauri = process.env.NEXT_PUBLIC_TAURI === "true";

// `next dev` serves its chunks from /_next/static/ under names that are reused
// across rebuilds, so the SW's cache-first rule for that prefix pins the first
// build a developer ever loaded and silently breaks hot reload. The filenames
// are content-hashed only in production, so the rule is safe there and the SW
// is registered there alone.
const isDev = process.env.NODE_ENV === "development";

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

    // Tear down a worker installed by an earlier production build (or an older
    // build of this file) so a developer isn't stuck serving stale chunks from
    // its cache on localhost.
    if (isDev) {
      navigator.serviceWorker.getRegistrations().then((regs) => {
        for (const reg of regs) reg.unregister();
      });
      // CacheStorage is absent on insecure origins — `next dev` is reachable
      // over plain http on the LAN, so this cannot assume `caches` exists.
      if (typeof caches !== "undefined") {
        caches.keys().then((keys) => {
          for (const key of keys) {
            if (key.startsWith("hearth-")) caches.delete(key);
          }
        });
      }
      return;
    }

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
