"use client";

import { createContext, useContext, useEffect, useRef, useState } from "react";
import { apiClient } from "@/lib/api/client";
import { setAccessToken, loadStoredToken } from "./token";
import type { components } from "@/lib/api/schema";

type User = components["schemas"]["UserResponse"];

interface AuthContextValue {
  user: User | null;
  isLoading: boolean;
  login: (email: string, password: string) => Promise<void>;
  logout: () => Promise<void>;
}

const AuthContext = createContext<AuthContextValue | null>(null);

const REFRESH_INTERVAL_MS = 14 * 60 * 1000; // fire 1 min before 15-min token expires

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [user, setUser]       = useState<User | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

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
      // ── 1. Try stored access token ────────────────────────────────────────
      const stored = loadStoredToken();
      if (stored) {
        setAccessToken(stored);
        const { data: me } = await apiClient.GET("/auth/me");
        if (me) {
          setUser(me);
          scheduleRefresh();
          setIsLoading(false);
          return;
        }
        // Token was rejected (expired on server or revoked) — clear it and fall through.
        setAccessToken(null);
      }

      // ── 2. Try cookie refresh ─────────────────────────────────────────────
      const { data } = await apiClient.POST("/auth/refresh", {});
      if (data?.access_token) {
        setAccessToken(data.access_token); // persists new token to localStorage
        const { data: me } = await apiClient.GET("/auth/me");
        if (me) setUser(me);
        scheduleRefresh();
      }

      setIsLoading(false);
    }

    restore();
    return () => {
      if (timerRef.current) clearTimeout(timerRef.current);
    };
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  async function login(email: string, password: string) {
    const { data, error } = await apiClient.POST("/auth/login", {
      body: { email, password },
    });
    if (error || !data) {
      const detail = (error as { detail?: string } | undefined)?.detail;
      throw new Error(detail ?? "Login failed");
    }
    setAccessToken(data.access_token); // persists to localStorage
    setUser(data.user);
    scheduleRefresh();
  }

  async function logout() {
    await apiClient.POST("/auth/logout", {});
    setAccessToken(null); // clears localStorage too
    setUser(null);
    if (timerRef.current) clearTimeout(timerRef.current);
  }

  return (
    <AuthContext.Provider value={{ user, isLoading, login, logout }}>
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth() {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used inside AuthProvider");
  return ctx;
}
