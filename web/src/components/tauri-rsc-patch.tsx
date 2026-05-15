"use client";

import { useEffect } from "react";

/**
 * Patches window.fetch in Tauri builds to fix client-side navigation to
 * dynamic route pages (e.g. /recipes/<uuid>, /projects/<uuid>).
 *
 * WHY: Next.js's client-side router fetches RSC payload files
 * (e.g. /recipes/<uuid>/__next.*.txt) during navigation. In a Tauri static
 * export, those files only exist for the pre-generated "index" param
 * (e.g. /recipes/index/__next.*.txt). When Tauri's asset server returns 404
 * for the UUID path, the Next.js router falls back to the root, sending the
 * user back to the dashboard.
 *
 * FIX: Intercept RSC payload fetches whose second path segment is a UUID and
 * rewrite them to use "index" instead. The payload content is identical
 * regardless of the UUID — it's just a client-component shell reference with
 * varyParams: null, so reusing the "index" payload is safe.
 */

const UUID_RE =
  /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

const DYNAMIC_ROUTE_PREFIXES = new Set([
  "recipes",
  "projects",
  "documents",
  "collections",
]);

export function TauriRscPatch() {
  useEffect(() => {
    // Only active inside Tauri
    if (
      typeof window === "undefined" ||
      window.location.protocol !== "tauri:"
    ) {
      return;
    }

    const originalFetch = window.fetch.bind(window);

    window.fetch = function patchedFetch(
      input: RequestInfo | URL,
      init?: RequestInit,
    ) {
      try {
        const urlStr =
          typeof input === "string"
            ? input
            : input instanceof Request
              ? input.url
              : input.toString();

        const url = new URL(urlStr, window.location.origin);

        // CRITICAL: only rewrite same-origin (tauri://localhost) fetches.
        // API calls go to http://localhost:1338 (different origin) and must
        // never be rewritten — doing so would corrupt the resource ID path
        // and cause the API to return 422 for the fake "index" UUID.
        if (url.origin !== window.location.origin) {
          return originalFetch(input, init);
        }

        const parts = url.pathname.split("/").filter(Boolean);

        // Match: /<known-prefix>/<uuid>[/...] with any query params (RSC uses ?_rsc=...)
        if (
          parts.length >= 2 &&
          DYNAMIC_ROUTE_PREFIXES.has(parts[0]) &&
          UUID_RE.test(parts[1])
        ) {
          const newParts = [...parts];
          newParts[1] = "index";
          const rewritten = new URL(url.toString());
          rewritten.pathname = "/" + newParts.join("/");
          return originalFetch(rewritten.toString(), init);
        }
      } catch {
        // Fall through to original fetch on any parse error
      }

      return originalFetch(input, init);
    };

    return () => {
      window.fetch = originalFetch;
    };
  }, []);

  return null;
}
