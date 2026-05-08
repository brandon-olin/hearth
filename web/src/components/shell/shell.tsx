"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useResizablePanel } from "@/lib/hooks/use-resizable-panel";
import { useAuth } from "@/lib/auth/context";
import { useSidebarConfig, useFolderOpen, type SidebarConfig, type SidebarFolder } from "@/lib/sidebar/context";
import { ALL_NAV_ITEMS, type NavItem } from "@/lib/sidebar/nav-items";
import { resolveFolderIcon, DEFAULT_FOLDER_ICON } from "@/lib/sidebar/folder-icons";
import { Button } from "@/components/ui/button";
import { Sheet, SheetContent, SheetTrigger } from "@/components/ui/sheet";
import { CommandPalette } from "@/components/shell/command-palette";
import { cn } from "@/lib/utils";
import {
  ChevronRight,
  Settings,
  Menu,
  MessageSquare,
  LogOut,
  Search,
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

function getRootRenderList(config: SidebarConfig): RenderEntry[] {
  const folderedHrefs = new Set(config.folders.flatMap((f) => f.hrefs));
  const allHrefs = ALL_NAV_ITEMS.map((n) => n.href);
  const folderIds = config.folders.map((f) => f.id);

  let order: string[];
  if (config.order.length > 0) {
    // Use stored order. Append anything new (new nav items or folders) at the end.
    const unknownNavHrefs = allHrefs.filter(
      (h) => !config.order.includes(h) && !folderedHrefs.has(h),
    );
    const unknownFolderIds = folderIds.filter((id) => !config.order.includes(id));
    order = [...config.order, ...unknownNavHrefs, ...unknownFolderIds];
  } else {
    // Default: unfoldred nav items in definition order, then folders
    order = [
      ...allHrefs.filter((h) => !folderedHrefs.has(h)),
      ...folderIds,
    ];
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
      const item = ALL_NAV_ITEMS.find((n) => n.href === id);
      if (item) result.push(item);
    } else {
      // Folder ID
      const folder = config.folders.find((f) => f.id === id);
      if (folder) result.push(folder);
    }
  }

  return result;
}

// ── folder nav item ───────────────────────────────────────────────────────────

function FolderNavItem({
  folder,
  hidden,
  onNavigate,
}: {
  folder: SidebarFolder;
  hidden: string[];
  onNavigate?: () => void;
}) {
  const pathname = usePathname();
  const { folderOpen, toggleFolder } = useFolderOpen();
  const isOpen = folderOpen[folder.id] ?? false;

  const visibleItems = folder.hrefs
    .map((href) => ALL_NAV_ITEMS.find((n) => n.href === href))
    .filter((n): n is NavItem => !!n && !hidden.includes(n.href));

  const hasActive = visibleItems.some((item) =>
    item.href === "/" ? pathname === "/" : pathname.startsWith(item.href),
  );

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
          const ResolvedIcon = resolveFolderIcon(folder.icon) ?? resolveFolderIcon(DEFAULT_FOLDER_ICON)!;
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
          {visibleItems.map((item) => {
            const active =
              item.href === "/" ? pathname === "/" : pathname.startsWith(item.href);
            const Icon = item.icon;
            return (
              <Link
                key={item.href}
                href={item.href}
                onClick={onNavigate}
                className={cn(
                  "flex items-center gap-3 px-3 py-1.5 rounded-md text-sm font-medium transition-colors",
                  active
                    ? "bg-primary/10 text-primary"
                    : "text-muted-foreground hover:bg-muted hover:text-foreground",
                )}
              >
                <Icon className="h-4 w-4 shrink-0" />
                {item.label}
              </Link>
            );
          })}
        </div>
      )}
    </div>
  );
}

// ── nav links ─────────────────────────────────────────────────────────────────

function NavLinks({
  onNavigate,
  onSearchOpen,
}: {
  onNavigate?: () => void;
  onSearchOpen: () => void;
}) {
  const pathname = usePathname();
  const { sidebarConfig } = useSidebarConfig();
  const renderList = getRootRenderList(sidebarConfig);

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

          <Tooltip>
            <TooltipTrigger asChild>
              <button
                type="button"
                disabled
                className="flex items-center justify-center h-8 w-8 rounded-md text-muted-foreground opacity-40 cursor-not-allowed"
              >
                <MessageSquare className="h-4 w-4 shrink-0" />
              </button>
            </TooltipTrigger>
            <TooltipContent side="right">
              <p>
                Ask AI <span className="ml-1 opacity-60">(coming soon)</span>
              </p>
            </TooltipContent>
          </Tooltip>
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
              onNavigate={onNavigate}
            />
          );
        }

        // Plain nav item
        const { href, label, icon: Icon } = entry;
        const active = href === "/" ? pathname === "/" : pathname.startsWith(href);
        return (
          <Link
            key={href}
            href={href}
            onClick={onNavigate}
            className={cn(
              "flex items-center gap-3 px-3 py-2 rounded-md text-sm font-medium transition-colors",
              active
                ? "bg-primary/10 text-primary"
                : "text-muted-foreground hover:bg-muted hover:text-foreground",
            )}
          >
            <Icon className="h-4 w-4 shrink-0" />
            {label}
          </Link>
        );
      })}
    </nav>
  );
}

// ── sidebar content ───────────────────────────────────────────────────────────

function SidebarContent({
  onNavigate,
  onSearchOpen,
}: {
  onNavigate?: () => void;
  onSearchOpen: () => void;
}) {
  const { user, logout } = useAuth();
  const router = useRouter();

  async function handleLogout() {
    await logout();
    router.replace("/login");
  }

  return (
    <div className="flex flex-col h-full">
      <div className="px-4 pt-5 pb-3 shrink-0">
        <span className="px-2 text-base font-semibold tracking-tight">
          Life Dashboard
        </span>
      </div>

      <NavLinks onNavigate={onNavigate} onSearchOpen={onSearchOpen} />

      {/* Footer — avatar → account settings | settings icon | logout */}
      <div className="px-3 pb-4 pt-2 shrink-0 border-t mt-2">
        <div className="flex items-center gap-1">
          {/* Avatar — initials, links to Account section of settings */}
          <button
            type="button"
            onClick={() => {
              onNavigate?.();
              router.push("/settings");
            }}
            title={user?.display_name ?? user?.email ?? "Account settings"}
            className="h-7 w-7 shrink-0 rounded-full bg-primary text-primary-foreground text-xs font-semibold flex items-center justify-center hover:opacity-80 transition-opacity cursor-pointer"
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

export function Shell({ children }: { children: React.ReactNode }) {
  const [mobileOpen, setMobileOpen] = useState(false);
  const [paletteOpen, setPaletteOpen] = useState(false);
  const { width: sidebarWidth, startResize } = useResizablePanel({
    defaultWidth: 256,
    minWidth: 180,
    maxWidth: 380,
    storageKey: "ld-sidebar-width",
  });

  useEffect(() => {
    function handleKeyDown(e: KeyboardEvent) {
      if ((e.metaKey || e.ctrlKey) && e.key === "p") {
        e.preventDefault();
        setPaletteOpen(true);
      }
    }
    document.addEventListener("keydown", handleKeyDown);
    return () => document.removeEventListener("keydown", handleKeyDown);
  }, []);

  return (
    <div className="flex h-full">
      {/* Desktop sidebar */}
      <aside
        className="hidden md:flex flex-col shrink-0 border-r bg-card"
        style={{ width: sidebarWidth }}
      >
        <SidebarContent onSearchOpen={() => setPaletteOpen(true)} />
      </aside>

      {/* Sidebar resize handle */}
      <div
        className="hidden md:block w-1 shrink-0 cursor-col-resize hover:bg-primary/30 active:bg-primary/50 transition-colors"
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
              />
            </SheetContent>
          </Sheet>
          <span className="font-semibold text-sm">Life Dashboard</span>
        </header>

        <main className="flex-1 overflow-y-auto">{children}</main>
      </div>

      <CommandPalette
        open={paletteOpen}
        onClose={() => setPaletteOpen(false)}
      />
    </div>
  );
}
