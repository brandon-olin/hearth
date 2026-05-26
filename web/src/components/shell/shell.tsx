"use client";

import { useEffect, useState } from "react";
import { useFocusMode } from "@/lib/focus/context";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useResizablePanel } from "@/lib/hooks/use-resizable-panel";
import { useAuth } from "@/lib/auth/context";
import {
  useSidebarConfig,
  useFolderOpen,
  type SidebarConfig,
  type SidebarFolder,
} from "@/lib/sidebar/context";
import { ALL_NAV_ITEMS, type NavItem } from "@/lib/sidebar/nav-items";
import { ROLE_LABEL } from "@/lib/roles";
import { useNavItems } from "@/lib/sidebar/use-nav-items";
import {
  resolveFolderIcon,
  DEFAULT_FOLDER_ICON,
} from "@/lib/sidebar/folder-icons";
import type { LucideIcon } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Sheet, SheetContent, SheetTrigger } from "@/components/ui/sheet";
import { CommandPalette } from "@/components/shell/command-palette";
import { NotificationBell } from "@/components/shell/notification-bell";
import { AiChat } from "@/components/ai/ai-chat";
import { cn } from "@/lib/utils";
import {
  ChevronRight,
  Settings,
  Menu,
  MessageSquare,
  LogOut,
  Search,
  UserRound,
  Users,
  X,
} from "lucide-react";
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip";

// ── nav items ─────────────────────────────────────────────────────────────────
// Defined in lib/sidebar/nav-items.ts — import from there directly.
// Settings lives in the sidebar footer; it is intentionally excluded from
// ALL_NAV_ITEMS so it doesn't appear in the sidebar customizer.
export { ALL_NAV_ITEMS } from "@/lib/sidebar/nav-items";

// ── root render list ──────────────────────────────────────────────────────────
// Builds the ordered list of things to render at the root of the nav:
// a mix of NavItem (direct links) and SidebarFolder (collapsible groups).
// Items assigned to a folder are excluded from the root level.

type RenderEntry = NavItem | SidebarFolder;

function isFolder(entry: RenderEntry): entry is SidebarFolder {
  return "hrefs" in entry;
}

function getRootRenderList(
  config: SidebarConfig,
  allNavItems: NavItem[],
): RenderEntry[] {
  const folderedHrefs = new Set(config.folders.flatMap((f) => f.hrefs));
  const allHrefs = allNavItems.map((n) => n.href);
  const folderIds = config.folders.map((f) => f.id);

  let order: string[];
  if (config.order.length > 0) {
    // Use stored order. Append anything new (new nav items or folders) at the end.
    const unknownNavHrefs = allHrefs.filter(
      (h) => !config.order.includes(h) && !folderedHrefs.has(h),
    );
    const unknownFolderIds = folderIds.filter(
      (id) => !config.order.includes(id),
    );
    order = [...config.order, ...unknownNavHrefs, ...unknownFolderIds];
  } else {
    // Default: unfoldered nav items in definition order, then folders
    order = [...allHrefs.filter((h) => !folderedHrefs.has(h)), ...folderIds];
  }

  // Resolve IDs → entries, deduplicating and filtering hidden / missing items
  const seen = new Set<string>();
  const result: RenderEntry[] = [];

  for (const id of order) {
    if (seen.has(id)) continue;
    seen.add(id);

    if (id.startsWith("/")) {
      // Nav item href
      if (folderedHrefs.has(id)) continue; // assigned to a folder — skip at root
      if (config.hidden.includes(id)) continue;
      const item = allNavItems.find((n) => n.href === id);
      if (item) result.push(item);
    } else {
      // Folder ID
      const folder = config.folders.find((f) => f.id === id);
      if (folder) result.push(folder);
    }
  }

  return result;
}

/** Renders a NavItem icon — handles both Lucide components and emoji strings. */
function NavIcon({
  icon,
  className,
}: {
  icon: LucideIcon | string;
  className?: string;
}) {
  if (typeof icon === "string") {
    return (
      <span className={cn("shrink-0 text-base leading-none", className)}>
        {icon}
      </span>
    );
  }
  const Icon = icon;
  return <Icon className={cn("h-4 w-4 shrink-0", className)} />;
}

// ── active href resolution ────────────────────────────────────────────────────
// Among all nav items, find the *most specific* one whose href matches the
// current pathname. "Most specific" = longest href, so /projects/abc wins over
// /projects when the user is on a project detail page.
//
// This is the single source of truth for active state — both the flat nav list
// and folder contents use it, so the rule is universal regardless of item type.

function getActiveHref(
  pathname: string,
  allNavItems: NavItem[],
): string | null {
  let best: string | null = null;
  for (const item of allNavItems) {
    const matches =
      item.href === "/"
        ? pathname === "/"
        : pathname === item.href || pathname.startsWith(item.href + "/");
    if (matches && (best === null || item.href.length > best.length)) {
      best = item.href;
    }
  }
  return best;
}

// ── folder nav item ───────────────────────────────────────────────────────────

function FolderNavItem({
  folder,
  hidden,
  allNavItems,
  activeHref,
  onNavigate,
}: {
  folder: SidebarFolder;
  hidden: string[];
  allNavItems: NavItem[];
  activeHref: string | null;
  onNavigate?: () => void;
}) {
  const { folderOpen, toggleFolder } = useFolderOpen();
  const isOpen = folderOpen[folder.id] ?? false;

  const visibleItems = folder.hrefs
    .map((href) => allNavItems.find((n) => n.href === href))
    .filter((n): n is NavItem => !!n && !hidden.includes(n.href));

  const hasActive = visibleItems.some((item) => item.href === activeHref);

  return (
    <div>
      <button
        type="button"
        onClick={() => toggleFolder(folder.id)}
        className={cn(
          "flex items-center gap-3 w-full px-3 py-2 rounded-md text-sm font-medium transition-colors cursor-pointer select-none",
          hasActive && !isOpen
            ? "text-primary"
            : "text-muted-foreground hover:bg-muted hover:text-foreground",
        )}
      >
        {(() => {
          const ResolvedIcon =
            resolveFolderIcon(folder.icon) ??
            resolveFolderIcon(DEFAULT_FOLDER_ICON)!;
          return <ResolvedIcon className="h-4 w-4 shrink-0" />;
        })()}
        <span className="flex-1 text-left truncate">{folder.label}</span>
        <ChevronRight
          className={cn(
            "h-3.5 w-3.5 shrink-0 transition-transform duration-150",
            isOpen && "rotate-90",
          )}
        />
      </button>

      {isOpen && visibleItems.length > 0 && (
        <div className="ml-3 mt-0.5 pl-3 border-l border-border/50 space-y-0.5 pb-0.5">
          {visibleItems.map((item) => (
            <Link
              key={item.href}
              href={item.href}
              onClick={onNavigate}
              className={cn(
                "flex items-center gap-3 px-3 py-1.5 rounded-md text-sm font-medium transition-colors",
                item.href === activeHref
                  ? "bg-primary/10 text-primary"
                  : "text-muted-foreground hover:bg-muted hover:text-foreground",
              )}
            >
              <NavIcon icon={item.icon} />
              {item.label}
            </Link>
          ))}
        </div>
      )}
    </div>
  );
}

// ── nav links ─────────────────────────────────────────────────────────────────

function NavLinks({
  onNavigate,
  onSearchOpen,
  onAiOpen,
  aiEnabled,
}: {
  onNavigate?: () => void;
  onSearchOpen: () => void;
  onAiOpen: () => void;
  /** ai-access-001: when false, hide the Ask-AI icon entirely. */
  aiEnabled: boolean;
}) {
  const pathname = usePathname();
  const { sidebarConfig } = useSidebarConfig();
  const { items: allNavItems } = useNavItems();
  const renderList = getRootRenderList(sidebarConfig, allNavItems);

  // Compute once — the single most-specific nav item matching the current URL.
  // All active-state checks below use this value so only one item is ever lit.
  const activeHref = getActiveHref(pathname, allNavItems);

  return (
    <nav className="flex-1 px-3 py-2 space-y-0.5 overflow-y-auto">
      {/* Search + Ask AI — compact icon row */}
      <TooltipProvider delayDuration={500}>
        <div className="flex items-center justify-between gap-0.5 mb-0.5">
          <Tooltip>
            <TooltipTrigger asChild>
              <button
                type="button"
                onClick={() => {
                  onNavigate?.();
                  onSearchOpen();
                }}
                className="flex items-center justify-center h-8 w-8 rounded-md text-muted-foreground hover:bg-muted hover:text-foreground transition-colors cursor-pointer"
              >
                <Search className="h-4 w-4 shrink-0" />
              </button>
            </TooltipTrigger>
            <TooltipContent side="right">
              <p>
                Search <kbd className="ml-1 font-mono opacity-60">⌘P</kbd>
              </p>
            </TooltipContent>
          </Tooltip>

          {aiEnabled && (
            <Tooltip>
              <TooltipTrigger asChild>
                <button
                  type="button"
                  onClick={() => {
                    onNavigate?.();
                    onAiOpen();
                  }}
                  className="flex items-center justify-center h-8 w-8 rounded-md text-muted-foreground hover:bg-muted hover:text-foreground transition-colors cursor-pointer"
                >
                  <MessageSquare className="h-4 w-4 shrink-0" />
                </button>
              </TooltipTrigger>
              <TooltipContent side="right">
                <p>
                  Ask AI <kbd className="ml-1 font-mono opacity-60">⌘K</kbd>
                </p>
              </TooltipContent>
            </Tooltip>
          )}

          <NotificationBell />
        </div>
      </TooltipProvider>

      <div className="my-1 border-t" />

      {renderList.map((entry) => {
        if (isFolder(entry)) {
          return (
            <FolderNavItem
              key={entry.id}
              folder={entry}
              hidden={sidebarConfig.hidden}
              allNavItems={allNavItems}
              activeHref={activeHref}
              onNavigate={onNavigate}
            />
          );
        }

        // Plain nav item — active only if it is the most-specific match
        const { href, label, icon } = entry;
        return (
          <Link
            key={href}
            href={href}
            onClick={onNavigate}
            className={cn(
              "flex items-center gap-3 px-3 py-2 rounded-md text-sm font-medium transition-colors",
              href === activeHref
                ? "bg-primary/10 text-primary"
                : "text-muted-foreground hover:bg-muted hover:text-foreground",
            )}
          >
            <NavIcon icon={icon} />
            {label}
          </Link>
        );
      })}
    </nav>
  );
}

// ── sidebar content ───────────────────────────────────────────────────────────

// ── Dev user-switcher popover ─────────────────────────────────────────────────

function DevUserSwitcher({ onClose }: { onClose: () => void }) {
  const { user, impersonating, impersonateUser, stopImpersonating } = useAuth();
  const [members, setMembers] = useState<Array<{
    user_id: string;
    display_name: string | null;
    email: string;
    role: string;
  }>>([]);
  const [loading, setLoading] = useState(true);
  const [switching, setSwitching] = useState<string | null>(null);

  useEffect(() => {
    async function load() {
      try {
        const { getAccessToken } = await import("@/lib/auth/token");
        const token = getAccessToken();
        const res = await fetch("/api/households/members", {
          headers: token ? { Authorization: `Bearer ${token}` } : {},
        });
        if (res.ok) {
          const data = await res.json() as Array<{
            user_id: string;
            display_name: string | null;
            email: string;
            role: string;
          }>;
          setMembers(data.filter((m) => m.user_id !== user?.id));
        }
      } finally {
        setLoading(false);
      }
    }
    void load();
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  function initials(name: string | null, email: string) {
    return (name ?? email)
      .trim()
      .split(/\s+/)
      .slice(0, 2)
      .map((w) => w[0]?.toUpperCase() ?? "")
      .join("");
  }

  async function handleSwitch(userId: string) {
    setSwitching(userId);
    try {
      await impersonateUser(userId);
      onClose();
    } catch {
      setSwitching(null);
    }
  }

  return (
    <div className="absolute bottom-full left-0 mb-2 w-64 rounded-lg border bg-card shadow-lg z-50">
      <div className="flex items-center justify-between px-3 py-2.5 border-b">
        <div className="flex items-center gap-1.5 text-xs font-semibold text-muted-foreground">
          <Users className="h-3.5 w-3.5" />
          <span>Dev: View as…</span>
        </div>
        <button type="button" onClick={onClose} className="text-muted-foreground hover:text-foreground cursor-pointer">
          <X className="h-3.5 w-3.5" />
        </button>
      </div>

      <div className="p-1.5 space-y-0.5">
        {/* Current user row */}
        <div className="flex items-center gap-2.5 px-2.5 py-2 rounded-md bg-primary/5 text-primary">
          <div className="h-6 w-6 rounded-full bg-primary text-primary-foreground text-xs font-semibold flex items-center justify-center shrink-0">
            {initials(user?.display_name ?? null, user?.email ?? "?")}
          </div>
          <div className="flex-1 min-w-0">
            <p className="text-xs font-medium truncate">{user?.display_name ?? user?.email}</p>
            <p className="text-[10px] opacity-70 truncate">{impersonating ? "admin (you)" : "you"}</p>
          </div>
          <span className="text-[10px] font-medium opacity-60 shrink-0">active</span>
        </div>

        {impersonating && (
          <button
            type="button"
            onClick={() => { stopImpersonating(); onClose(); }}
            className="flex items-center gap-2.5 px-2.5 py-2 w-full rounded-md text-left hover:bg-muted transition-colors cursor-pointer"
          >
            <div className="h-6 w-6 rounded-full bg-muted text-muted-foreground flex items-center justify-center shrink-0">
              <UserRound className="h-3.5 w-3.5" />
            </div>
            <span className="text-xs text-muted-foreground">← Back to your account</span>
          </button>
        )}

        {loading && (
          <p className="text-xs text-muted-foreground px-2.5 py-2">Loading…</p>
        )}

        {!loading && members.length === 0 && !impersonating && (
          <p className="text-xs text-muted-foreground px-2.5 py-2">No other members yet.</p>
        )}

        {members.map((m) => {
          const isSwitching = switching === m.user_id;
          return (
            <button
              key={m.user_id}
              type="button"
              disabled={!!switching}
              onClick={() => handleSwitch(m.user_id)}
              className="flex items-center gap-2.5 px-2.5 py-2 w-full rounded-md text-left hover:bg-muted transition-colors cursor-pointer disabled:opacity-50 disabled:cursor-default"
            >
              <div className="h-6 w-6 rounded-full bg-muted text-muted-foreground text-xs font-semibold flex items-center justify-center shrink-0">
                {isSwitching ? "…" : initials(m.display_name, m.email)}
              </div>
              <div className="flex-1 min-w-0">
                <p className="text-xs font-medium truncate">{m.display_name ?? m.email}</p>
                <p className="text-[10px] text-muted-foreground truncate">{ROLE_LABEL[m.role] ?? m.role}</p>
              </div>
            </button>
          );
        })}
      </div>
    </div>
  );
}

function SidebarContent({
  onNavigate,
  onSearchOpen,
  onAiOpen,
}: {
  onNavigate?: () => void;
  onSearchOpen: () => void;
  onAiOpen: () => void;
}) {
  const { user, impersonating, logout } = useAuth();
  const router = useRouter();
  const [switcherOpen, setSwitcherOpen] = useState(false);
  // ai-access-001: per-membership AI gate. Default true for older API
  // responses that don't carry the field. Affects the Ask-AI icon in
  // the nav and the ⌘K shortcut in Shell.
  const aiEnabled = user?.ai_features_enabled !== false;

  async function handleLogout() {
    await logout();
    router.replace("/login");
  }

  return (
    <div className="flex flex-col h-full">
      <div className="px-4 pt-5 pb-3 shrink-0">
        <span className="text-base font-semibold tracking-tight">
          {user?.household_name ?? "Hearth"}
        </span>
      </div>

      <NavLinks
        onNavigate={onNavigate}
        onSearchOpen={onSearchOpen}
        onAiOpen={onAiOpen}
        aiEnabled={aiEnabled}
      />

      {/* Impersonation banner */}
      {impersonating && (
        <div
          className="mx-3 mb-2 px-2.5 py-1.5 rounded-md text-[11px] font-medium flex items-center gap-1.5 border"
          style={{
            background: "var(--badge-warning-bg)",
            color: "var(--badge-warning-fg)",
            borderColor: "var(--badge-warning-fg)",
            opacity: 0.9,
          }}
        >
          <Users className="h-3 w-3 shrink-0" />
          Viewing as {user?.display_name ?? user?.email}
        </div>
      )}

      {/* Footer — avatar | settings | logout */}
      <div className="px-3 pb-4 pt-2 shrink-0 border-t mt-2 relative">
        {switcherOpen && (
          <DevUserSwitcher onClose={() => setSwitcherOpen(false)} />
        )}
        <div className="flex items-center gap-1">
          {/* Avatar — click to open dev user-switcher */}
          <button
            type="button"
            onClick={() => setSwitcherOpen((o) => !o)}
            title={user?.display_name ?? user?.email ?? "Account"}
            className={cn(
              "h-7 w-7 shrink-0 rounded-full text-xs font-semibold flex items-center justify-center hover:opacity-80 transition-opacity cursor-pointer",
              impersonating
                ? "bg-amber-500 text-white"
                : "bg-primary text-primary-foreground",
            )}
          >
            {(user?.display_name ?? user?.email ?? "?")
              .trim()
              .split(/\s+/)
              .slice(0, 2)
              .map((w: string) => w[0]?.toUpperCase() ?? "")
              .join("")}
          </button>

          <span className="flex-1" />

          {/* Settings */}
          <Button
            variant="ghost"
            size="icon"
            className="h-8 w-8 text-muted-foreground hover:text-foreground"
            onClick={() => {
              onNavigate?.();
              router.push("/settings");
            }}
            title="Settings"
          >
            <Settings className="h-4 w-4" />
          </Button>

          {/* Logout */}
          <Button
            variant="ghost"
            size="icon"
            className="h-8 w-8 shrink-0 text-muted-foreground hover:text-foreground"
            onClick={handleLogout}
            aria-label="Log out"
            title="Log out"
          >
            <LogOut className="h-4 w-4" />
          </Button>
        </div>
      </div>
    </div>
  );
}

// ── shell ─────────────────────────────────────────────────────────────────────

const AI_PANEL_MIN = 360;
const AI_PANEL_MAX = 900;
const AI_PANEL_DEFAULT = 480;
const AI_PANEL_STORAGE_KEY = "ld-ai-panel-width";

export function Shell({ children }: { children: React.ReactNode }) {
  const [mobileOpen, setMobileOpen] = useState(false);
  const [paletteOpen, setPaletteOpen] = useState(false);
  const [aiPanelOpen, setAiPanelOpen] = useState(false);
  const { toggle: toggleFocus, focused } = useFocusMode();
  const { user } = useAuth();
  // ai-access-001: gate the AI chat panel + ⌘K shortcut on the
  // per-membership flag. Default true for older API responses.
  const aiEnabled = user?.ai_features_enabled !== false;
  const { width: sidebarWidth, startResize } = useResizablePanel({
    defaultWidth: 256,
    minWidth: 180,
    maxWidth: 380,
    storageKey: "ld-sidebar-width",
  });

  // AI panel width — persisted, resizable from the left edge
  const [aiPanelWidth, setAiPanelWidth] = useState<number>(() => {
    if (typeof window === "undefined") return AI_PANEL_DEFAULT;
    const stored = localStorage.getItem(AI_PANEL_STORAGE_KEY);
    const parsed = stored ? parseInt(stored, 10) : NaN;
    return isNaN(parsed)
      ? AI_PANEL_DEFAULT
      : Math.min(AI_PANEL_MAX, Math.max(AI_PANEL_MIN, parsed));
  });

  function startAiResize(e: React.MouseEvent) {
    e.preventDefault();
    const startX = e.clientX;
    const startWidth = aiPanelWidth;
    const onMouseMove = (ev: MouseEvent) => {
      // Dragging left increases width (panel is on the right)
      const next = Math.min(
        AI_PANEL_MAX,
        Math.max(AI_PANEL_MIN, startWidth + (startX - ev.clientX)),
      );
      setAiPanelWidth(next);
      localStorage.setItem(AI_PANEL_STORAGE_KEY, String(next));
    };
    const onMouseUp = () => {
      document.removeEventListener("mousemove", onMouseMove);
      document.removeEventListener("mouseup", onMouseUp);
      document.body.style.cursor = "";
      document.body.style.userSelect = "";
    };
    document.body.style.cursor = "col-resize";
    document.body.style.userSelect = "none";
    document.addEventListener("mousemove", onMouseMove);
    document.addEventListener("mouseup", onMouseUp);
  }

  useEffect(() => {
    function handleKeyDown(e: KeyboardEvent) {
      if ((e.metaKey || e.ctrlKey) && e.key === "p") {
        e.preventDefault();
        setPaletteOpen(true);
      }
      if ((e.metaKey || e.ctrlKey) && e.key === "k") {
        e.preventDefault();
        if (aiEnabled) {
          setAiPanelOpen((o) => !o);
        }
      }
      if ((e.metaKey || e.ctrlKey) && e.shiftKey && e.key === "f") {
        e.preventDefault();
        toggleFocus();
      }
    }
    document.addEventListener("keydown", handleKeyDown);
    return () => document.removeEventListener("keydown", handleKeyDown);
  }, []);

  return (
    <div className="flex h-full">
      {/* Desktop sidebar — collapses in focus mode */}
      <aside
        className="hidden md:flex flex-col shrink-0 border-r bg-card overflow-hidden transition-[width,opacity] duration-300 ease-in-out"
        style={{ width: focused ? 0 : sidebarWidth, opacity: focused ? 0 : 1 }}
      >
        <SidebarContent
          onSearchOpen={() => setPaletteOpen(true)}
          onAiOpen={() => setAiPanelOpen(true)}
        />
      </aside>

      {/* Sidebar resize handle — hidden in focus mode */}
      <div
        className="hidden md:block shrink-0 cursor-col-resize hover:bg-primary/30 active:bg-primary/50 transition-[width] duration-300 ease-in-out"
        style={{ width: focused ? 0 : 4 }}
        onMouseDown={startResize}
      />

      {/* Right column */}
      <div className="flex flex-col flex-1 min-w-0">
        {/* Mobile top bar */}
        <header className="md:hidden flex items-center gap-3 px-4 h-14 border-b bg-card shrink-0">
          <Sheet open={mobileOpen} onOpenChange={setMobileOpen}>
            <SheetTrigger
              className="inline-flex h-9 w-9 items-center justify-center rounded-md hover:bg-muted cursor-pointer"
              aria-label="Open menu"
            >
              <Menu className="h-5 w-5" />
            </SheetTrigger>
            <SheetContent side="left" className="w-64 p-0">
              <SidebarContent
                onNavigate={() => setMobileOpen(false)}
                onSearchOpen={() => {
                  setMobileOpen(false);
                  setPaletteOpen(true);
                }}
                onAiOpen={() => {
                  setMobileOpen(false);
                  setAiPanelOpen(true);
                }}
              />
            </SheetContent>
          </Sheet>
          <span className="font-semibold text-sm">
            {user?.household_name ?? "Hearth"}
          </span>
        </header>

        <main className="flex-1 overflow-y-auto">{children}</main>
      </div>

      <CommandPalette
        open={paletteOpen}
        onClose={() => setPaletteOpen(false)}
      />

      {/* AI panel — custom right-side panel with draggable left edge */}
      {aiEnabled && aiPanelOpen && (
        <>
          {/* Backdrop */}
          <div
            className="fixed inset-0 z-40 bg-black/20 md:hidden"
            onClick={() => setAiPanelOpen(false)}
          />
          {/* Panel */}
          <div
            className="fixed top-0 right-0 bottom-0 z-50 flex bg-background border-l shadow-xl
                        animate-in slide-in-from-right duration-200"
            style={{ width: aiPanelOpen ? `min(${aiPanelWidth}px, 100vw)` : 0 }}
          >
            {/* Drag handle — desktop only */}
            <div
              className="hidden md:block w-1 shrink-0 cursor-col-resize hover:bg-primary/40 active:bg-primary/60 transition-colors self-stretch"
              onMouseDown={startAiResize}
            />
            <div className="flex-1 min-w-0 overflow-hidden">
              <AiChat onClose={() => setAiPanelOpen(false)} />
            </div>
          </div>
        </>
      )}
    </div>
  );
}
