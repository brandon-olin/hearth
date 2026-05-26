"use client";

import { createContext, useContext, useEffect, useRef, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { apiClient } from "@/lib/api/client";
import { setAccessToken, getAccessToken, loadStoredToken, isTokenExpiringSoon } from "./token";
import type { components } from "@/lib/api/schema";

// ── Locale auto-detect ────────────────────────────────────────────────────────

/**
 * Detect the user's timezone from the browser.
 * Returns an IANA timezone string (e.g. "America/Chicago") or null if unavailable.
 */
function detectTimezone(): string | null {
  try {
    return Intl.DateTimeFormat().resolvedOptions().timeZone ?? null;
  } catch {
    return null;
  }
}

/**
 * Patch the user's locale settings if they haven't been set yet.
 * Only sets timezone — date_format and week_start default to sensible values on the backend.
 * Returns the updated user if the patch succeeded.
 */
async function maybeAutoDetectLocale(user: User): Promise<User | null> {
  if (user.timezone) return null; // already set, nothing to do
  const tz = detectTimezone();
  if (!tz) return null;
  const { data } = await apiClient.PATCH("/auth/me", {
    body: { timezone: tz },
  });
  return data ?? null;
}

type User = components["schemas"]["UserResponse"];

interface AuthContextValue {
  user: User | null;
  isLoading: boolean;
  impersonating: boolean;
  /** True for one session after locale was auto-detected from the browser. Cleared when dismissed. */
  localeAutoDetected: boolean;
  dismissLocaleNotice: () => void;
  /** Merge partial fields into the in-memory user — call after a PATCH /auth/me so the context stays in sync. */
  updateUser: (patch: Partial<User>) => void;
  login: (email: string, password: string) => Promise<void>;
  logout: () => Promise<void>;
  impersonateUser: (targetUserId: string) => Promise<void>;
  stopImpersonating: () => void;
}

const AuthContext = createContext<AuthContextValue | null>(null);

const REFRESH_INTERVAL_MS = 14 * 60 * 1000; // fire 1 min before 15-min token expires

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const qc = useQueryClient();
  const [user, setUser]       = useState<User | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [impersonating, setImpersonating] = useState(false);
  const [localeAutoDetected, setLocaleAutoDetected] = useState(false);
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  // Saved state for when the admin wants to stop impersonating
  const savedSessionRef = useRef<{ token: string; user: User } | null>(null);

  function scheduleRefresh() {
    if (timerRef.current) clearTimeout(timerRef.current);
    timerRef.current = setTimeout(doRefresh, REFRESH_INTERVAL_MS);
  }

  async function doRefresh() {
    const { data } = await apiClient.POST("/auth/refresh", {});
    if (data?.access_token) {
      setAccessToken(data.access_token); // also persists to localStorage
      scheduleRefresh();
    } else {
      setAccessToken(null);
      setUser(null);
    }
  }

  // On mount: restore session.
  //
  // Strategy (fastest path first):
  //   1. localStorage — if we have a non-expired token, verify it with /auth/me
  //      and restore instantly with no extra round-trips.
  //   2. Cookie refresh — if the stored token is missing or expired, POST to
  //      /auth/refresh which uses the httpOnly refresh cookie.
  //   3. Give up — user sees the login page.
  useEffect(() => {
    async function restore() {
      try {
        // ── 1. Try stored access token ──────────────────────────────────────
        const stored = loadStoredToken();
        if (stored) {
          setAccessToken(stored);
          const { data: me } = await apiClient.GET("/auth/me");
          if (me) {
            const updated = await maybeAutoDetectLocale(me);
            setUser(updated ?? me);
            if (updated) setLocaleAutoDetected(true);
            scheduleRefresh();
            setIsLoading(false);
            return;
          }
          // Token was rejected (expired on server or revoked) — clear it and fall through.
          setAccessToken(null);
        }

        // ── 2. Try cookie refresh ───────────────────────────────────────────
        const { data } = await apiClient.POST("/auth/refresh", {});
        if (data?.access_token) {
          setAccessToken(data.access_token); // persists new token to localStorage
          const { data: me } = await apiClient.GET("/auth/me");
          if (me) {
            const updated = await maybeAutoDetectLocale(me);
            setUser(updated ?? me);
            if (updated) setLocaleAutoDetected(true);
          }
          scheduleRefresh();
        }
      } catch {
        // Network error or unexpected API failure — treat as unauthenticated.
        setAccessToken(null);
        setUser(null);
      } finally {
        setIsLoading(false);
      }
    }

    restore();

    // When the tab regains focus, browsers may have throttled the 14-minute
    // refresh timer (Chrome caps background timers to ~1 min intervals). If the
    // stored token has expired or is within 60 seconds of expiring, fire a
    // proactive refresh so the next API call doesn't get a 401.
    function onVisibilityChange() {
      if (document.visibilityState !== "visible") return;
      if (isTokenExpiringSoon()) {
        doRefresh();
      }
    }

    document.addEventListener("visibilitychange", onVisibilityChange);

    return () => {
      if (timerRef.current) clearTimeout(timerRef.current);
      document.removeEventListener("visibilitychange", onVisibilityChange);
    };
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  async function login(email: string, password: string) {
    // Clear any cached data from a previous session before setting new credentials.
    qc.clear();
    const { data, error } = await apiClient.POST("/auth/login", {
      body: { email, password },
    });
    if (error || !data) {
      const detail = (error as { detail?: string } | undefined)?.detail;
      throw new Error(detail ?? "Login failed");
    }
    setAccessToken(data.access_token); // persists to localStorage
    const updated = await maybeAutoDetectLocale(data.user);
    setUser(updated ?? data.user);
    if (updated) setLocaleAutoDetected(true);
    scheduleRefresh();
  }

  function dismissLocaleNotice() {
    setLocaleAutoDetected(false);
  }

  function updateUser(patch: Partial<User>) {
    setUser((prev) => (prev ? { ...prev, ...patch } : null));
  }

  async function logout() {
    await apiClient.POST("/auth/logout", {});
    setAccessToken(null); // clears localStorage too
    setUser(null);
    setImpersonating(false);
    savedSessionRef.current = null;
    if (timerRef.current) clearTimeout(timerRef.current);
    // Clear cached query data so a subsequent login doesn't see this user's data.
    qc.clear();
  }

  async function impersonateUser(targetUserId: string) {
    // If already impersonating, use the saved admin token — the active token
    // belongs to the impersonated user (member role) and would fail the admin check.
    const adminToken = savedSessionRef.current?.token ?? getAccessToken();
    const adminUser  = savedSessionRef.current?.user  ?? user;
    if (!adminToken || !adminUser) throw new Error("Not authenticated");

    const res = await fetch(
      `/api/households/dev/impersonate/${targetUserId}`,
      {
        method: "POST",
        headers: { Authorization: `Bearer ${adminToken}` },
      },
    );
    if (!res.ok) {
      const body = await res.json().catch(() => ({}));
      throw new Error((body as { detail?: string }).detail ?? "Impersonation failed");
    }
    const data = (await res.json()) as {
      access_token: string;
      user_id: string;
      email: string;
      display_name: string | null;
    };

    // Save the original admin's session only if not already saved
    // (switching between impersonated users must not overwrite the real admin).
    if (!savedSessionRef.current) {
      savedSessionRef.current = { token: adminToken, user: adminUser };
    }

    // Clear all cached queries — the new user has different data access.
    qc.clear();

    // Fetch the full user object for the impersonated account.
    setAccessToken(data.access_token);
    const { data: impersonatedUser } = await apiClient.GET("/auth/me");
    if (!impersonatedUser) throw new Error("Failed to load impersonated user");

    setUser(impersonatedUser);
    setImpersonating(true);
  }

  function stopImpersonating() {
    const saved = savedSessionRef.current;
    if (!saved) return;
    setAccessToken(saved.token);
    setUser(saved.user);
    setImpersonating(false);
    savedSessionRef.current = null;
    // Clear cache so the admin doesn't see the impersonated user's data.
    qc.clear();
  }

  return (
    <AuthContext.Provider value={{ user, isLoading, impersonating, localeAutoDetected, dismissLocaleNotice, updateUser, login, logout, impersonateUser, stopImpersonating }}>
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth() {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used inside AuthProvider");
  return ctx;
}
