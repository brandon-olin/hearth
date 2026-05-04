"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useAuth } from "@/lib/auth/context";
import { Button } from "@/components/ui/button";
import { Sheet, SheetContent, SheetTrigger } from "@/components/ui/sheet";
import { ThemeToggle } from "@/components/ui/theme-toggle";
import { CommandPalette } from "@/components/shell/command-palette";
import { cn } from "@/lib/utils";
import {
  LayoutDashboard,
  CheckSquare,
  Target,
  Repeat,
  FileText,
  Calendar,
  Users,
  ChefHat,
  ShoppingCart,
  Menu,
  MessageSquare,
  LogOut,
  Search,
} from "lucide-react";

// ── nav items ─────────────────────────────────────────────────────────────────

const ALL_NAV_ITEMS = [
  { href: "/",              label: "Dashboard",     icon: LayoutDashboard, modes: ["work", "personal"] },
  { href: "/todos",         label: "To-dos",        icon: CheckSquare,     modes: ["work"] },
  { href: "/goals",         label: "Goals",         icon: Target,          modes: ["work"] },
  { href: "/habits",        label: "Habits",        icon: Repeat,          modes: ["work", "personal"] },
  { href: "/notes",         label: "Notes",         icon: FileText,        modes: ["work", "personal"] },
  { href: "/calendar",      label: "Calendar",      icon: Calendar,        modes: ["work"] },
  { href: "/recipes",       label: "Recipes",       icon: ChefHat,         modes: ["personal"] },
  { href: "/grocery-lists", label: "Grocery Lists", icon: ShoppingCart,    modes: ["personal"] },
  { href: "/contacts",      label: "Contacts",      icon: Users,           modes: ["personal"] },
] as const;

type Mode = "work" | "personal";

// ── mode persistence ──────────────────────────────────────────────────────────

function useMode(): [Mode, (m: Mode) => void] {
  const [mode, setModeState] = useState<Mode>("work");

  useEffect(() => {
    const stored = localStorage.getItem("nav-mode");
    if (stored === "work" || stored === "personal") setModeState(stored);
  }, []);

  function setMode(m: Mode) {
    setModeState(m);
    localStorage.setItem("nav-mode", m);
  }

  return [mode, setMode];
}

// ── mode toggle pill ──────────────────────────────────────────────────────────

function ModeToggle({ mode, setMode }: { mode: Mode; setMode: (m: Mode) => void }) {
  return (
    <div className="flex rounded-full bg-muted p-0.5 text-xs font-medium">
      {(["work", "personal"] as Mode[]).map((m) => (
        <button
          key={m}
          type="button"
          onClick={() => setMode(m)}
          className={cn(
            "flex-1 px-3 py-1 rounded-full transition-all cursor-pointer capitalize",
            mode === m
              ? "bg-background text-foreground shadow-sm"
              : "text-muted-foreground hover:text-foreground"
          )}
        >
          {m}
        </button>
      ))}
    </div>
  );
}

// ── nav links ─────────────────────────────────────────────────────────────────

function NavLinks({
  mode,
  onNavigate,
  onSearchOpen,
}: {
  mode: Mode;
  onNavigate?: () => void;
  onSearchOpen: () => void;
}) {
  const pathname = usePathname();
  const items = ALL_NAV_ITEMS.filter((item) =>
    (item.modes as readonly string[]).includes(mode)
  );

  return (
    <nav className="flex-1 px-3 py-2 space-y-0.5 overflow-y-auto">
      {/* Search trigger */}
      <button
        type="button"
        onClick={() => { onNavigate?.(); onSearchOpen(); }}
        className="flex items-center gap-3 w-full px-3 py-2 rounded-md text-sm font-medium text-muted-foreground hover:bg-muted hover:text-foreground transition-colors cursor-pointer"
      >
        <Search className="h-4 w-4 shrink-0" />
        <span className="flex-1 text-left">Search…</span>
        <kbd className="text-xs bg-muted rounded px-1.5 py-0.5 font-mono leading-none">
          ⌘P
        </kbd>
      </button>

      <div className="my-1 border-t" />

      {items.map(({ href, label, icon: Icon }) => {
        const active =
          href === "/" ? pathname === "/" : pathname.startsWith(href);
        return (
          <Link
            key={href}
            href={href}
            onClick={onNavigate}
            className={cn(
              "flex items-center gap-3 px-3 py-2 rounded-md text-sm font-medium transition-colors",
              active
                ? "bg-primary/10 text-primary"
                : "text-muted-foreground hover:bg-muted hover:text-foreground"
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
  mode,
  setMode,
  onNavigate,
  onSearchOpen,
}: {
  mode: Mode;
  setMode: (m: Mode) => void;
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
      <div className="px-4 pt-5 pb-3 shrink-0 space-y-3">
        <span className="px-2 text-base font-semibold tracking-tight">
          Life Dashboard
        </span>
        <ModeToggle mode={mode} setMode={setMode} />
      </div>

      <NavLinks mode={mode} onNavigate={onNavigate} onSearchOpen={onSearchOpen} />

      <div className="px-3 pb-5 pt-3 shrink-0 space-y-1 border-t mt-2">
        <Button
          variant="outline"
          className="w-full justify-start gap-3"
          disabled
        >
          <MessageSquare className="h-4 w-4 shrink-0" />
          Ask AI
        </Button>

        <div className="flex items-center justify-between px-3 py-1.5">
          <span className="text-sm text-muted-foreground truncate">
            {user?.display_name ?? user?.email}
          </span>
          <div className="flex items-center gap-0.5 shrink-0">
            <ThemeToggle />
            <Button
              variant="ghost"
              size="icon"
              onClick={handleLogout}
              aria-label="Log out"
            >
              <LogOut className="h-4 w-4" />
            </Button>
          </div>
        </div>
      </div>
    </div>
  );
}

// ── shell ─────────────────────────────────────────────────────────────────────

export function Shell({ children }: { children: React.ReactNode }) {
  const [mobileOpen, setMobileOpen] = useState(false);
  const [paletteOpen, setPaletteOpen] = useState(false);
  const [mode, setMode] = useMode();

  // Global Cmd+P / Ctrl+P shortcut
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
      <aside className="hidden md:flex flex-col w-64 shrink-0 border-r bg-card">
        <SidebarContent
          mode={mode}
          setMode={setMode}
          onSearchOpen={() => setPaletteOpen(true)}
        />
      </aside>

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
                mode={mode}
                setMode={setMode}
                onNavigate={() => setMobileOpen(false)}
                onSearchOpen={() => { setMobileOpen(false); setPaletteOpen(true); }}
              />
            </SheetContent>
          </Sheet>
          <span className="font-semibold text-sm">Life Dashboard</span>
        </header>

        <main className="flex-1 overflow-y-auto">
          {children}
        </main>
      </div>

      <CommandPalette open={paletteOpen} onClose={() => setPaletteOpen(false)} />
    </div>
  );
}
