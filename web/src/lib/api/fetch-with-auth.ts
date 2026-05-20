/**
 * fetchWithAuth — a thin fetch wrapper that mirrors the token-refresh logic
 * built into the openapi-fetch apiClient middleware.
 *
 * Use this for raw fetch() calls to budget (and other) routes that aren't yet
 * included in schema.d.ts, so they can't go through apiClient directly.
 *
 * Behaviour:
 *  1. Attaches the current access token as a Bearer header.
 *  2. On 401, calls tryRefreshToken() (singleton — no concurrent storm).
 *  3. If a new token is obtained, retries the request once.
 *  4. If the retry also fails, or no token was obtained, throws.
 */

import { getAccessToken } from "@/lib/auth/token";
import { tryRefreshToken } from "@/lib/api/client";

function withAuth(init?: RequestInit, token?: string | null): RequestInit {
  const headers = new Headers(init?.headers);
  if (token) headers.set("Authorization", `Bearer ${token}`);
  return { ...init, headers };
}

export async function fetchWithAuth(
  input: RequestInfo | URL,
  init?: RequestInit
): Promise<Response> {
  const token = getAccessToken();
  const res = await fetch(input, withAuth(init, token));

  if (res.status !== 401) return res;

  // Access token expired — attempt a silent refresh
  const newToken = await tryRefreshToken();
  if (!newToken) {
    throw new Error("401: Session expired — please log in again");
  }

  // Retry once with the new token
  const retried = await fetch(input, withAuth(init, newToken));
  if (!retried.ok) {
    const text = await retried.text().catch(() => retried.statusText);
    throw new Error(`${retried.status}: ${text}`);
  }
  return retried;
}
