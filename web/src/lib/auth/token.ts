// Access token — held in memory for use by the API client middleware.
// Also persisted to localStorage so a page reload within the token's lifetime
// can restore the session without needing the httpOnly refresh cookie.

const LS_TOKEN_KEY  = "ld-access-token";
const LS_EXPIRY_KEY = "ld-token-expiry";

// Store with a 13-minute window (tokens live 15 min; refresh fires at 14 min).
// This avoids serving a stale token right before the scheduled refresh.
const TOKEN_TTL_MS = 13 * 60 * 1000;

let accessToken: string | null = null;

export function getAccessToken(): string | null {
  return accessToken;
}

export function setAccessToken(token: string | null): void {
  accessToken = token;
  try {
    if (token) {
      localStorage.setItem(LS_TOKEN_KEY,  token);
      localStorage.setItem(LS_EXPIRY_KEY, String(Date.now() + TOKEN_TTL_MS));
    } else {
      localStorage.removeItem(LS_TOKEN_KEY);
      localStorage.removeItem(LS_EXPIRY_KEY);
    }
  } catch {
    // localStorage unavailable (private browsing, etc.) — silent fail.
  }
}

/**
 * Returns the stored access token if it exists and hasn't expired.
 * Returns null if missing, expired, or localStorage is unavailable.
 */
export function loadStoredToken(): string | null {
  try {
    const token  = localStorage.getItem(LS_TOKEN_KEY);
    const expiry = Number(localStorage.getItem(LS_EXPIRY_KEY) ?? "0");
    if (token && Date.now() < expiry) return token;
  } catch {
    // ignore
  }
  return null;
}

/**
 * Returns true if the stored token is expired or will expire within 60 seconds.
 * Used by the visibilitychange listener to detect "tab backgrounded, timer fired
 * late" situations so we can proactively refresh before the next API call.
 */
export function isTokenExpiringSoon(): boolean {
  if (!accessToken) return false;
  try {
    const expiry = Number(localStorage.getItem(LS_EXPIRY_KEY) ?? "0");
    return Date.now() >= expiry - 60_000;
  } catch {
    return false;
  }
}
