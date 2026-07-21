"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { $api } from "@/lib/api/query";
import { useQueryClient } from "@tanstack/react-query";
import { useDebounce } from "@/lib/hooks/use-debounce";
import { Button, buttonVariants } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { ClipboardList, Plus, Loader2, Search, ChevronRight, ChevronLeft } from "lucide-react";
import { cn } from "@/lib/utils";

function relativeLastUsed(iso: string | null | undefined): string {
  if (!iso) return "Never used";
  const then = new Date(iso).getTime();
  const days = Math.floor((Date.now() - then) / 86_400_000);
  if (days <= 0) return "Used today";
  if (days === 1) return "Used yesterday";
  if (days < 7) return `Used ${days} days ago`;
  if (days < 30) return `Used ${Math.floor(days / 7)} wk ago`;
  return `Used ${Math.floor(days / 30)} mo ago`;
}

export default function TemplatesPage() {
  const router = useRouter();
  const qc = useQueryClient();
  const [search, setSearch] = useState("");
  const debounced = useDebounce(search, 300);
  const [creating, setCreating] = useState(false);
  const [newName, setNewName] = useState("");

  const { data, isLoading, isError } = $api.useQuery("get", "/workouts/templates", {
    params: { query: { search: debounced || undefined, limit: 100 } },
  });
  const createTemplate = $api.useMutation("post", "/workouts/templates");

  const templates = data?.items ?? [];

  async function handleCreate() {
    if (!newName.trim()) return;
    try {
      const t = await createTemplate.mutateAsync({ body: { name: newName.trim() } });
      qc.invalidateQueries({ queryKey: ["get", "/workouts/templates"] });
      router.push(`/workouts/templates/${t.id}`);
    } catch { /* TODO: toast */ }
  }

  return (
    <div className="page-content">
      <div className="flex items-center justify-between mb-6">
        <div className="flex items-center gap-2">
          <ClipboardList className="h-5 w-5 text-muted-foreground" />
          <h1 className="text-xl font-semibold">Templates</h1>
        </div>
        <div className="flex items-center gap-2">
          <Link
            href="/workouts"
            className={cn(buttonVariants({ size: "sm", variant: "ghost" }), "text-muted-foreground")}
          >
            <ChevronLeft className="h-4 w-4 mr-1" /> Workouts
          </Link>
          {!creating && (
            <Button size="sm" onClick={() => setCreating(true)}>
              <Plus className="h-4 w-4 mr-1" /> New template
            </Button>
          )}
        </div>
      </div>

      {creating && (
        <div className="mb-5 flex gap-2 items-center border rounded-lg p-3 bg-muted/20">
          <Input
            autoFocus
            value={newName}
            onChange={(e) => setNewName(e.target.value)}
            onKeyDown={(e) => { if (e.key === "Enter") handleCreate(); }}
            placeholder="Template name (e.g. Push Day)"
            className="flex-1"
          />
          <Button size="sm" onClick={handleCreate} disabled={!newName.trim() || createTemplate.isPending}>
            {createTemplate.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : "Create"}
          </Button>
          <Button size="sm" variant="ghost" onClick={() => { setCreating(false); setNewName(""); }}>Cancel</Button>
        </div>
      )}

      <div className="relative mb-4 max-w-sm">
        <Search className="h-4 w-4 text-muted-foreground absolute left-2.5 top-1/2 -translate-y-1/2" />
        <Input
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          placeholder="Search templates…"
          className="pl-8"
        />
      </div>

      {isLoading && (
        <div className="flex items-center gap-2 py-8 text-sm text-muted-foreground">
          <Loader2 className="h-4 w-4 animate-spin" /> Loading…
        </div>
      )}
      {isError && <p className="py-8 text-sm text-destructive">Failed to load templates.</p>}

      {!isLoading && !isError && templates.length === 0 && (
        <div className="py-12 text-center">
          <ClipboardList className="h-8 w-8 text-muted-foreground/30 mx-auto mb-3" />
          <p className="text-sm text-muted-foreground">
            {debounced ? "No templates match your search." : "No templates yet."}
          </p>
          {!debounced && (
            <Button variant="outline" size="sm" className="mt-4" onClick={() => setCreating(true)}>
              <Plus className="h-4 w-4 mr-1" /> Create your first template
            </Button>
          )}
        </div>
      )}

      <div className="space-y-2">
        {templates.map((t) => (
          <button
            key={t.id}
            type="button"
            onClick={() => router.push(`/workouts/templates/${t.id}`)}
            className={cn(
              "w-full text-left border rounded-lg px-4 py-3 bg-card",
              "hover:bg-muted/30 transition-colors flex items-center gap-3",
            )}
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
            <ChevronRight className="h-4 w-4 text-muted-foreground shrink-0" />
          </button>
        ))}
      </div>
    </div>
  );
}
