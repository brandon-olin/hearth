import createClient from "openapi-fetch";
import type { paths } from "./schema";
import { getAccessToken, setAccessToken } from "@/lib/auth/token";

// In Tauri builds (NEXT_PUBLIC_TAURI=true), the frontend talks directly to the
// FastAPI sidecar — there is no Next.js proxy in a static export. The sidecar
// URL is injected at build time via NEXT_PUBLIC_API_BASE_URL.
//
// In web builds the proxy is at /api on the same origin, which keeps cookies
// same-site so SameSite=Lax refresh tokens work correctly.
const isTauri = process.env.NEXT_PUBLIC_TAURI === "true";
const BASE_URL = process.env.NEXT_PUBLIC_API_BASE_URL ?? "/api";

/**
 * The resolved API base URL for the current environment.
 * Use this wherever raw fetch() calls need to hit the backend directly,
 * to avoid hardcoding "/api" which doesn't work in Tauri static builds.
 */
export const apiBaseUrl = BASE_URL;

export const apiClient = createClient<paths>({
  baseUrl: BASE_URL,
  // "include" sends cookies cross-origin (needed for Tauri → localhost:1338).
  // It also works correctly for same-origin web builds.
  credentials: isTauri ? "include" : "same-origin",
});

// ── Token refresh ─────────────────────────────────────────────────────────────

// Singleton promise: prevents multiple concurrent refresh attempts when
// several queries fail with 401 at the same time (e.g. on window focus).
let pendingRefresh: Promise<string | null> | null = null;

async function tryRefreshToken(): Promise<string | null> {
  if (pendingRefresh) return pendingRefresh;

  pendingRefresh = (async () => {
    try {
      const res = await fetch(`${BASE_URL}/auth/refresh`, {
        method: "POST",
        credentials: isTauri ? "include" : "same-origin",
      });
      if (res.ok) {
        const data = (await res.json()) as { access_token?: string };
        if (data.access_token) {
          setAccessToken(data.access_token);
          return data.access_token;
        }
      }
    } catch {
      // Network error — fall through
    }
    setAccessToken(null);
    return null;
  })();

  const result = await pendingRefresh;
  pendingRefresh = null;
  return result;
}

// ── Middleware ────────────────────────────────────────────────────────────────

/**
 * Resolves a relative media path (e.g. /uploads/foo.jpg) to a browser-safe URL.
 *
 * In Tauri static-export builds there is no Next.js server to proxy requests,
 * so a bare /uploads/... path resolves against tauri://localhost which has no
 * upload files. Prepending the API base URL (http://localhost:1338) makes the
 * browser fetch directly from the FastAPI sidecar, where uploads are served.
 *
 * In web dev/prod builds the Next.js server proxies /api/* to the backend;
 * relative paths are left as-is and resolve via the proxy or same-origin rules.
 */
export function resolveMediaUrl(path: string | null | undefined): string | null {
  if (!path) return null;
  if (path.startsWith("http://") || path.startsWith("https://")) return path;
  if (isTauri && path.startsWith("/")) {
    return `${BASE_URL}${path}`;
  }
  return path;
}

apiClient.use({
  onRequest({ request }) {
    const token = getAccessToken();
    if (token) {
      request.headers.set("Authorization", `Bearer ${token}`);
    }
    return request;
  },

  async onResponse({ request, response }) {
    if (!response.ok) {
      // Auth endpoints return 401/403 as normal control flow (e.g. no session
      // yet on page load). Let the auth context handle those itself.
      // Note: in Tauri builds BASE_URL is "http://localhost:1338" so paths are
      // "/auth/…"; in web builds they're "/api/auth/…" via the Next.js proxy.
      const url = new URL(request.url, "http://localhost");
      if (url.pathname.startsWith("/api/auth/") || url.pathname.startsWith("/auth/")) return;

      if (response.status === 401) {
        // Access token expired. Attempt a silent token refresh and retry the
        // request once. Multiple concurrent 401s share one refresh call via
        // the pendingRefresh singleton above.
        const newToken = await tryRefreshToken();
        if (newToken) {
          const retryHeaders = new Headers(request.headers);
          retryHeaders.set("Authorization", `Bearer ${newToken}`);
          // Retry — only safe for methods with no body (GET, HEAD, DELETE).
          // POST/PATCH would need to re-read the body, so we let them fail.
          if (["GET", "HEAD", "DELETE"].includes(request.method)) {
            const retried = await fetch(request.url, {
              method: request.method,
              headers: retryHeaders,
              credentials: "same-origin",
            });
            if (retried.ok) return retried;
            // Retry also failed — fall through to throw below.
            const text = await retried.text().catch(() => retried.statusText);
            throw new Error(`${retried.status}: ${text}`);
          }
        }
        throw new Error("401: Session expired — please log in again");
      }

      // React Query v5 requires query functions to throw rather than return
      // undefined. Throwing here ensures errors surface correctly.
      const text = await response.text().catch(() => response.statusText);
      throw new Error(`${response.status}: ${text}`);
    }
  },
});
