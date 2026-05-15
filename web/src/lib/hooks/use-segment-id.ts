"use client";

import { useParams } from "next/navigation";

/**
 * Like useParams<{ id: string }>(), but falls back to reading the segment
 * from window.location.pathname when the param is undefined or stale.
 *
 * WHY: In Tauri static-export builds, hard-navigating to a dynamic URL like
 * /projects/<uuid> tries to load web/out/projects/<uuid>/index.html.  That
 * file doesn't exist (only web/out/projects/index/index.html was pre-rendered
 * via generateStaticParams).  Tauri ends up serving the wrong HTML file, so
 * Next.js hydrates with router params from the wrong page — useParams()
 * returns undefined or "index" instead of the real UUID, which causes
 * openapi-react-query to disable the query (required path param is falsy).
 *
 * The fallback reads the *actual* URL, where the UUID lives at segment index
 * 1 for all current dynamic routes:
 *   /projects/<id>
 *   /documents/<id>
 *   /collections/<id>
 *   /recipes/<id>
 *   /recipes/<id>/edit
 */
export function useSegmentId(): string {
  const params = useParams<{ id: string }>();

  // Happy path: useParams returned a real, non-sentinel value.
  if (params.id && params.id !== "index") {
    return params.id;
  }

  // Fallback for Tauri (or any env where the router params are stale).
  if (typeof window !== "undefined") {
    // pathname = "/projects/31662b7b-..." → ["projects", "31662b7b-..."]
    const segments = window.location.pathname.split("/").filter(Boolean);
    const candidate = segments[1]; // always the second segment for these routes
    if (candidate && candidate !== "index") {
      return candidate;
    }
  }

  // Last resort: return whatever useParams gave us (may be "" or "index").
  // Callers that pass this to openapi-react-query will see queries auto-disabled
  // when the value is falsy, so a "" fallback is safe.
  return params.id ?? "";
}
