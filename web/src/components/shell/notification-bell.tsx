"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { $api } from "@/lib/api/query";
import { Bell } from "lucide-react";
import { cn } from "@/lib/utils";
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import type { components } from "@/lib/api/schema";

type Notification = components["schemas"]["NotificationResponse"];

// ── helpers ───────────────────────────────────────────────────────────────────

function notificationLabel(n: Notification): string {
  const title = (n.payload as { title?: string } | null)?.title ?? "an item";
  switch (n.type) {
    case "todo_assigned":
      return `You were assigned: ${title}`;
    case "event_created":
      return `New event added: ${title}`;
    case "mentioned":
      return `You were mentioned in: ${title}`;
    default:
      return title;
  }
}

function notificationHref(n: Notification): string | null {
  switch (n.entity_type) {
    case "todo":
      return "/todos";
    case "calendar_event":
      return "/calendar";
    case "document":
      return "/documents";
    default:
      return null;
  }
}

function timeAgo(iso: string): string {
  const diff = Date.now() - new Date(iso).getTime();
  const minutes = Math.floor(diff / 60_000);
  if (minutes < 1) return "just now";
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.floor(hours / 24);
  return `${days}d ago`;
}

// ── component ─────────────────────────────────────────────────────────────────

export function NotificationBell() {
  const router = useRouter();
  const qc = useQueryClient();
  const [open, setOpen] = useState(false);
  const panelRef = useRef<HTMLDivElement>(null);

  // Lightweight poll — just the count.
  const { data: countData } = $api.useQuery("get", "/notifications/unread-count", undefined, {
    refetchInterval: 30_000,
    refetchIntervalInBackground: false,
  });

  // Full list — fetched on demand when the panel opens.
  const { data: listData, isLoading } = $api.useQuery(
    "get",
    "/notifications",
    { params: { query: { limit: 30 } } },
    { enabled: open },
  );

  const markReadMutation = $api.useMutation("patch", "/notifications/{notification_id}/read");
  const markAllMutation  = $api.useMutation("post", "/notifications/read-all");

  const unreadCount = countData?.unread_count ?? 0;

  // Close on outside click.
  useEffect(() => {
    if (!open) return;
    function onPointerDown(e: PointerEvent) {
      if (panelRef.current && !panelRef.current.contains(e.target as Node)) {
        setOpen(false);
      }
    }
    document.addEventListener("pointerdown", onPointerDown);
    return () => document.removeEventListener("pointerdown", onPointerDown);
  }, [open]);

  const invalidate = useCallback(() => {
    qc.invalidateQueries({ queryKey: ["get", "/notifications/unread-count"] });
    qc.invalidateQueries({ queryKey: ["get", "/notifications"] });
  }, [qc]);

  async function handleNotificationClick(n: Notification) {
    if (!n.read_at) {
      await markReadMutation.mutateAsync({ params: { path: { notification_id: n.id } } });
      invalidate();
    }
    const href = notificationHref(n);
    if (href) {
      setOpen(false);
      router.push(href);
    }
  }

  async function handleMarkAllRead() {
    await markAllMutation.mutateAsync({});
    invalidate();
  }

  const notifications = listData?.items ?? [];

  return (
    <div className="relative" ref={panelRef}>
      <TooltipProvider delayDuration={500}>
        <Tooltip>
          <TooltipTrigger asChild>
            <button
              type="button"
              onClick={() => setOpen((o) => !o)}
              className="relative flex items-center justify-center h-8 w-8 rounded-md text-muted-foreground hover:bg-muted hover:text-foreground transition-colors cursor-pointer"
              aria-label={`Notifications${unreadCount > 0 ? ` (${unreadCount} unread)` : ""}`}
            >
              <Bell className="h-4 w-4 shrink-0" />
              {unreadCount > 0 && (
                <span className="absolute top-1 right-1 flex h-[7px] w-[7px] items-center justify-center rounded-full bg-primary" />
              )}
            </button>
          </TooltipTrigger>
          <TooltipContent side="right">
            <p>Notifications{unreadCount > 0 ? ` · ${unreadCount} unread` : ""}</p>
          </TooltipContent>
        </Tooltip>
      </TooltipProvider>

      {open && (
        <div
          className="absolute left-full top-0 ml-2 z-50 w-80 rounded-lg border border-border bg-popover shadow-lg
                     animate-in fade-in-0 zoom-in-95 duration-100"
        >
          {/* Header */}
          <div className="flex items-center justify-between px-4 py-3 border-b border-border">
            <span className="text-sm font-semibold">Notifications</span>
            {listData && listData.unread_count > 0 && (
              <button
                type="button"
                onClick={handleMarkAllRead}
                className="text-xs text-muted-foreground hover:text-foreground transition-colors cursor-pointer"
              >
                Mark all read
              </button>
            )}
          </div>

          {/* Body */}
          <div className="max-h-[420px] overflow-y-auto">
            {isLoading && (
              <div className="px-4 py-8 text-center text-sm text-muted-foreground">
                Loading…
              </div>
            )}

            {!isLoading && notifications.length === 0 && (
              <div className="px-4 py-8 text-center text-sm text-muted-foreground">
                No notifications yet
              </div>
            )}

            {!isLoading && notifications.map((n) => (
              <button
                key={n.id}
                type="button"
                onClick={() => handleNotificationClick(n)}
                className={cn(
                  "w-full text-left flex items-start gap-3 px-4 py-3 border-b border-border/50 last:border-b-0",
                  "hover:bg-muted/60 transition-colors cursor-pointer",
                  !n.read_at && "bg-primary/5",
                )}
              >
                {/* Unread dot */}
                <span
                  className={cn(
                    "mt-1.5 h-2 w-2 shrink-0 rounded-full",
                    n.read_at ? "bg-transparent" : "bg-primary",
                  )}
                />
                <div className="flex-1 min-w-0">
                  <p className={cn(
                    "text-sm leading-snug truncate",
                    n.read_at ? "text-muted-foreground" : "text-foreground font-medium",
                  )}>
                    {notificationLabel(n)}
                  </p>
                  <p className="mt-0.5 text-xs text-muted-foreground">
                    {timeAgo(n.created_at)}
                  </p>
                </div>
              </button>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
