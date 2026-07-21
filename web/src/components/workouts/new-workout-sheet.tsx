"use client";

import { useState } from "react";
import { ClipboardList, Dumbbell, Loader2, Search } from "lucide-react";
import { $api } from "@/lib/api/query";
import { useDebounce } from "@/lib/hooks/use-debounce";
import {
  Sheet,
  SheetContent,
  SheetHeader,
  SheetTitle,
  SheetDescription,
} from "@/components/ui/sheet";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";

/** "3 days ago" style recency. Never-used templates say so rather than lying. */
function relativeLastUsed(iso: string | null | undefined): string {
  if (!iso) return "You haven't used this yet";
  const days = Math.floor((Date.now() - new Date(iso).getTime()) / 86_400_000);
  if (days <= 0) return "Used today";
  if (days === 1) return "Used yesterday";
  if (days < 7) return `Used ${days} days ago`;
  if (days < 30) return `Used ${Math.floor(days / 7)} wk ago`;
  return `Used ${Math.floor(days / 30)} mo ago`;
}

/**
 * Starting a workout: pick a template or start blank.
 *
 * The list is every household template — they are shared — but the ORDER is
 * personal: `last_used_at` is derived from this member's own sessions, so a
 * template someone else ran this morning does not jump to the top of your list.
 */
export function NewWorkoutSheet({
  open,
  onClose,
  onStart,
  starting,
}: {
  open: boolean;
  onClose: () => void;
  onStart: (templateId: string | null) => void | Promise<void>;
  starting: string | null;
}) {
  const [search, setSearch] = useState("");
  const debounced = useDebounce(search, 300);

  const { data, isLoading } = $api.useQuery(
    "get",
    "/workouts/templates",
    { params: { query: { search: debounced || undefined, limit: 100 } } },
    { enabled: open, staleTime: 30_000 },
  );

  const templates = data?.items ?? [];

  return (
    <Sheet open={open} onOpenChange={(o) => !o && onClose()}>
      <SheetContent className="w-full sm:max-w-md overflow-hidden flex flex-col gap-0 p-0">
        <SheetHeader className="px-6 py-4 border-b shrink-0">
          <SheetTitle>New workout</SheetTitle>
          <SheetDescription className="sr-only">
            Start from a template or log a blank workout
          </SheetDescription>
        </SheetHeader>

        <div className="px-6 py-3 border-b shrink-0 space-y-3">
          <Button
            variant="outline"
            className="w-full justify-start"
            onClick={() => onStart(null)}
            disabled={starting !== null}
          >
            {starting === "blank"
              ? <Loader2 className="h-4 w-4 mr-2 animate-spin" />
              : <Dumbbell className="h-4 w-4 mr-2" />}
            Start blank workout
          </Button>
          <div className="relative">
            <Search className="h-4 w-4 text-muted-foreground absolute left-2.5 top-1/2 -translate-y-1/2" />
            <Input
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="Search templates…"
              className="pl-8"
            />
          </div>
        </div>

        <div className="flex-1 overflow-y-auto px-6 py-4 space-y-1.5">
          {isLoading && (
            <div className="flex items-center gap-2 text-sm text-muted-foreground">
              <Loader2 className="h-4 w-4 animate-spin" /> Loading…
            </div>
          )}
          {!isLoading && templates.length === 0 && (
            <p className="text-sm text-muted-foreground text-center py-4">
              {debounced ? "No templates match." : "No templates yet — start blank."}
            </p>
          )}
          {templates.map((t) => (
            <button
              key={t.id}
              type="button"
              onClick={() => onStart(t.id)}
              disabled={starting !== null}
              className="w-full text-left border rounded-lg px-3 py-2.5 bg-card hover:bg-muted/30 transition-colors flex items-center gap-2.5 disabled:opacity-50"
            >
              <ClipboardList className="h-4 w-4 text-muted-foreground shrink-0" />
              <div className="flex-1 min-w-0">
                <span className="text-sm font-medium block truncate">{t.name}</span>
                <span className="text-xs text-muted-foreground">
                  {t.exercise_count === 1 ? "1 exercise" : `${t.exercise_count} exercises`}
                  {" · "}
                  {relativeLastUsed(t.last_used_at)}
                </span>
              </div>
              {starting === t.id && <Loader2 className="h-4 w-4 animate-spin shrink-0" />}
            </button>
          ))}
        </div>
      </SheetContent>
    </Sheet>
  );
}
