"use client";

import { createContext, useCallback, useContext, useEffect, useState } from "react";

export const SIDEBAR_STORAGE_KEY = "ld-sidebar-config";
export const FOLDER_OPEN_KEY     = "ld-folder-open";

// ── Types ─────────────────────────────────────────────────────────────────────

export type SidebarFolder = {
  id: string;       // stable ID, e.g. "f-abc123" — never starts with "/"
  label: string;    // display name
  icon: string;     // single emoji
  hrefs: string[];  // nav item hrefs contained in this folder, in order
};

export type SidebarConfig = {
  hidden: string[];          // hrefs hidden from sidebar (can also apply inside folders)
  order: string[];           // root-level render order: mix of hrefs and folder IDs
  folders: SidebarFolder[];  // folder definitions (synced to server)
};

// folderOpen is NOT part of SidebarConfig — it's localStorage-only so that
// toggling a folder open/closed doesn't trigger a debounced server PATCH.
// Use useFolderOpen() to read and toggle it.

// ── Default ───────────────────────────────────────────────────────────────────

const DEFAULT_SIDEBAR_CONFIG: SidebarConfig = { hidden: [], order: [], folders: [] };

// ── Persistence helpers ───────────────────────────────────────────────────────

/** Normalise any config object — fills in missing fields added after the
 *  initial release so old stored/server values don't cause runtime crashes. */
export function normalizeSidebarConfig(raw: Partial<SidebarConfig>): SidebarConfig {
  return {
    hidden:  raw.hidden  ?? [],
    order:   raw.order   ?? [],
    folders: raw.folders ?? [],
  };
}

export function loadSidebarConfig(): SidebarConfig {
  if (typeof window === "undefined") return DEFAULT_SIDEBAR_CONFIG;
  try {
    const raw = localStorage.getItem(SIDEBAR_STORAGE_KEY);
    if (!raw) return DEFAULT_SIDEBAR_CONFIG;
    return normalizeSidebarConfig(JSON.parse(raw) as Partial<SidebarConfig>);
  } catch {
    return DEFAULT_SIDEBAR_CONFIG;
  }
}

export function saveSidebarConfig(config: SidebarConfig): void {
  if (typeof window === "undefined") return;
  localStorage.setItem(SIDEBAR_STORAGE_KEY, JSON.stringify(config));
}

export function loadFolderOpen(): Record<string, boolean> {
  if (typeof window === "undefined") return {};
  try {
    const raw = localStorage.getItem(FOLDER_OPEN_KEY);
    return raw ? (JSON.parse(raw) as Record<string, boolean>) : {};
  } catch {
    return {};
  }
}

export function saveFolderOpen(state: Record<string, boolean>): void {
  if (typeof window === "undefined") return;
  localStorage.setItem(FOLDER_OPEN_KEY, JSON.stringify(state));
}

// ── ID generator ──────────────────────────────────────────────────────────────

export function newFolderId(): string {
  return `f-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 6)}`;
}

// ── SidebarConfig context ─────────────────────────────────────────────────────

type SidebarConfigContextValue = {
  sidebarConfig: SidebarConfig;
  setSidebarConfig: (config: SidebarConfig) => void;
};

const SidebarConfigContext = createContext<SidebarConfigContextValue>({
  sidebarConfig: DEFAULT_SIDEBAR_CONFIG,
  setSidebarConfig: () => {},
});

export function SidebarConfigProvider({ children }: { children: React.ReactNode }) {
  const [sidebarConfig, setSidebarConfigState] = useState<SidebarConfig>(DEFAULT_SIDEBAR_CONFIG);

  useEffect(() => {
    setSidebarConfigState(loadSidebarConfig());

    // Sync when another tab changes sidebar config
    function onStorage(e: StorageEvent) {
      if (e.key === SIDEBAR_STORAGE_KEY) setSidebarConfigState(loadSidebarConfig());
    }
    window.addEventListener("storage", onStorage);
    return () => window.removeEventListener("storage", onStorage);
  }, []);

  const setSidebarConfig = useCallback((config: SidebarConfig) => {
    // Always normalize so configs arriving from the server (which may be
    // missing fields added after their initial save) don't cause crashes.
    const normalized = normalizeSidebarConfig(config);
    setSidebarConfigState(normalized);
    saveSidebarConfig(normalized);
  }, []);

  return (
    <SidebarConfigContext.Provider value={{ sidebarConfig, setSidebarConfig }}>
      {children}
    </SidebarConfigContext.Provider>
  );
}

export function useSidebarConfig() {
  return useContext(SidebarConfigContext);
}

// ── Folder open state (localStorage-only) ─────────────────────────────────────

type FolderOpenContextValue = {
  folderOpen: Record<string, boolean>;
  toggleFolder: (id: string) => void;
};

const FolderOpenContext = createContext<FolderOpenContextValue>({
  folderOpen: {},
  toggleFolder: () => {},
});

export function FolderOpenProvider({ children }: { children: React.ReactNode }) {
  const [folderOpen, setFolderOpenState] = useState<Record<string, boolean>>({});

  useEffect(() => {
    setFolderOpenState(loadFolderOpen());
  }, []);

  const toggleFolder = useCallback((id: string) => {
    setFolderOpenState((prev) => {
      const next = { ...prev, [id]: !prev[id] };
      saveFolderOpen(next);
      return next;
    });
  }, []);

  return (
    <FolderOpenContext.Provider value={{ folderOpen, toggleFolder }}>
      {children}
    </FolderOpenContext.Provider>
  );
}

export function useFolderOpen() {
  return useContext(FolderOpenContext);
}
