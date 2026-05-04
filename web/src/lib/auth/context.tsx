"use client";

import { createContext, useContext, useEffect, useRef, useState } from "react";
import { apiClient } from "@/lib/api/client";
import { setAccessToken } from "./token";
import type { components } from "@/lib/api/schema";

type User = components["schemas"]["UserResponse"];

interface AuthContextValue {
  user: User | null;
  isLoading: boolean;
  login: (email: string, password: string) => Promise<void>;
  logout: () => Promise<void>;
}

const AuthContext = createContext<AuthContextValue | null>(null);

const REFRESH_INTERVAL_MS = 14 * 60 * 1000; // 1 min before the 15-min token expires

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  function scheduleRefresh() {
    if (timerRef.current) clearTimeout(timerRef.current);
    timerRef.current = setTimeout(doRefresh, REFRESH_INTERVAL_MS);
  }

  async function doRefresh() {
    const { data } = await apiClient.POST("/auth/refresh", {});
    if (data?.access_token) {
      setAccessToken(data.access_token);
      scheduleRefresh();
    } else {
      setAccessToken(null);
      setUser(null);
    }
  }

  // On mount: try to restore session from the httpOnly refresh cookie.
  useEffect(() => {
    async function restore() {
      const { data } = await apiClient.POST("/auth/refresh", {});
      if (data?.access_token) {
        setAccessToken(data.access_token);
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
    setAccessToken(data.access_token);
    setUser(data.user);
    scheduleRefresh();
  }

  async function logout() {
    await apiClient.POST("/auth/logout", {});
    setAccessToken(null);
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
