/**
 * Fetches /app/config once and caches it.
 *
 * Tells the frontend which deployment tier is active, so it can show/hide
 * features like household invites and the forgot-password link.
 */

export type AppConfig = {
  deployment_tier: "local" | "self_hosted" | "cloud";
  email_enabled: boolean;
};

let _cached: AppConfig | null = null;

export async function getAppConfig(): Promise<AppConfig> {
  if (_cached) return _cached;
  try {
    const res = await fetch("/api/app/config");
    if (res.ok) {
      _cached = (await res.json()) as AppConfig;
      return _cached;
    }
  } catch {
    // Network error — fall back to local defaults
  }
  _cached = { deployment_tier: "local", email_enabled: false };
  return _cached;
}

/** React hook that reads the cached app config synchronously (or kicks off the fetch). */
import { useEffect, useState } from "react";

export function useAppConfig(): AppConfig {
  const [config, setConfig] = useState<AppConfig>(
    _cached ?? { deployment_tier: "local", email_enabled: false }
  );

  useEffect(() => {
    getAppConfig().then(setConfig);
  }, []);

  return config;
}
