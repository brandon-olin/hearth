"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { $api } from "@/lib/api/query";
import { Button } from "@/components/ui/button";
import { ProjectCreateSheet } from "@/components/projects/project-create-sheet";
import { usePermissions } from "@/lib/hooks/use-permissions";
import { cn } from "@/lib/utils";
import {
  Plus,
  FolderKanban,
  ChevronRight,
  Lock,
  Loader2,
} from "lucide-react";
import type { components } from "@/lib/api/schema";

type Project = components["schemas"]["ProjectResponse"];
type ProjectStatus = Project["status"];

// ── constants ─────────────────────────────────────────────────────────────────

const STATUS_BADGE: Record<ProjectStatus, string> = {
  backlog:     "badge-neutral",
  active:      "badge-primary",
  on_deck:     "badge-warning",
  in_progress: "badge-progress",
  complete:    "badge-success",
  archived:    "badge-neutral badge-faded",
};

const STATUS_LABEL: Record<ProjectStatus, string> = {
  backlog:     "Backlog",
  active:      "Active",
  on_deck:     "On deck",
  in_progress: "In progress",
  complete:    "Complete",
  archived:    "Archived",
};

const STATUS_OPTIONS: ProjectStatus[] = [
  "backlog", "active", "on_deck", "in_progress", "complete", "archived",
];

type Filter = "active" | "complete" | "all";

const FILTERS: { key: Filter; label: string }[] = [
  { key: "active",   label: "Active"    },
  { key: "complete", label: "Completed" },
  { key: "all",      label: "All"       },
];

function applyFilter(projects: Project[], filter: Filter): Project[] {
  if (filter === "active")
    return projects.filter(
      (p) => p.archived_at === null && p.status !== "complete" && p.status !== "archived",
    );
  if (filter === "complete")
    return projects.filter(
      (p) => p.status === "complete" || p.status === "archived",
    );
  return projects;
}

// ── project row ───────────────────────────────────────────────────────────────

function ProjectRow({ project }: { project: Project }) {
  const router = useRouter();

  return (
    <div
      className={cn(
        "group flex items-center gap-3 px-4 py-3 rounded-lg border bg-card hover:bg-muted/30 transition-colors cursor-pointer",
        project.archived_at && "opacity-60",
      )}
      onClick={() => router.push(`/projects/${project.id}`)}
    >
      <FolderKanban className="h-4 w-4 shrink-0 text-muted-foreground" />

      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2">
          <span className="text-sm font-medium truncate">{project.name}</span>
          {project.is_system && (
            <Lock className="h-3 w-3 text-muted-foreground/50 shrink-0" />
          )}
        </div>
        {project.description && (
          <p className="text-xs text-muted-foreground line-clamp-1 mt-0.5">
            {project.description}
          </p>
        )}
      </div>

      <div className="flex items-center gap-3 shrink-0">
        {project.due_date && (
          <span className="text-xs text-muted-foreground hidden sm:block">
            Due {project.due_date}
          </span>
        )}
        <span className={cn("badge", STATUS_BADGE[project.status])}>
          {STATUS_LABEL[project.status]}
        </span>
        <ChevronRight className="h-3.5 w-3.5 text-muted-foreground/40 group-hover:text-muted-foreground transition-colors" />
      </div>
    </div>
  );
}

// ── page ──────────────────────────────────────────────────────────────────────

export default function ProjectsPage() {
  const [filter, setFilter] = useState<Filter>("active");
  const [createOpen, setCreateOpen] = useState(false);
  const { can } = usePermissions();

  const { data, isLoading, isError } = $api.useQuery("get", "/projects", {
    params: { query: { root_only: true, include_archived: true } },
  });

  const all = data?.items ?? [];
  const displayed = applyFilter(all, filter);

  // Split system projects out so they always appear at the top of the list
  const systemProjects = displayed.filter((p) => p.is_system);
  const userProjects = displayed.filter((p) => !p.is_system);

  const counts: Record<Filter, number> = {
    active:   applyFilter(all, "active").length,
    complete: applyFilter(all, "complete").length,
    all:      all.length,
  };

  return (
    <div className="page-content">
      {/* Header */}
      <div className="flex items-center justify-between mb-6">
        <div className="flex items-center gap-2">
          <FolderKanban className="h-5 w-5 text-muted-foreground" />
          <h1 className="text-xl font-semibold">Projects</h1>
        </div>
        {can("projects", "create") && (
          <Button size="sm" onClick={() => setCreateOpen(true)}>
            <Plus className="h-4 w-4 mr-1" />
            New project
          </Button>
        )}
      </div>

      {/* Filter tabs */}
      <div className="flex border-b mb-5">
        {FILTERS.map(({ key, label }) => (
          <button
            key={key}
            type="button"
            onClick={() => setFilter(key)}
            className={cn(
              "px-4 py-2 text-sm font-medium -mb-px border-b-2 transition-colors cursor-pointer",
              filter === key
                ? "border-primary text-foreground"
                : "border-transparent text-muted-foreground hover:text-foreground",
            )}
          >
            {label}
            {!isLoading && (
              <span className={cn(
                "ml-1.5 text-xs",
                filter === key ? "text-muted-foreground" : "text-muted-foreground/60",
              )}>
                {counts[key]}
              </span>
            )}
          </button>
        ))}
      </div>

      {/* States */}
      {isLoading && (
        <div className="flex items-center gap-2 py-8 text-sm text-muted-foreground">
          <Loader2 className="h-4 w-4 animate-spin" />
          Loading…
        </div>
      )}

      {isError && (
        <p className="py-8 text-sm text-destructive">Failed to load projects.</p>
      )}

      {!isLoading && !isError && displayed.length === 0 && (
        <div className="py-12 text-center">
          <FolderKanban className="h-8 w-8 text-muted-foreground/30 mx-auto mb-3" />
          <p className="text-sm text-muted-foreground">
            {filter === "active"
              ? "No active projects yet."
              : filter === "complete"
              ? "No completed projects."
              : "No projects yet."}
          </p>
          {filter !== "complete" && can("projects", "create") && (
            <Button
              variant="outline"
              size="sm"
              className="mt-4"
              onClick={() => setCreateOpen(true)}
            >
              <Plus className="h-4 w-4 mr-1" />
              Create one
            </Button>
          )}
        </div>
      )}

      {!isLoading && !isError && displayed.length > 0 && (
        <div className="space-y-2">
          {systemProjects.map((p) => (
            <ProjectRow key={p.id} project={p} />
          ))}
          {systemProjects.length > 0 && userProjects.length > 0 && (
            <div className="pt-1 pb-0.5">
              <p className="text-xs font-medium text-muted-foreground/60 uppercase tracking-wide px-1">
                Projects
              </p>
            </div>
          )}
          {userProjects.map((p) => (
            <ProjectRow key={p.id} project={p} />
          ))}
        </div>
      )}

      <ProjectCreateSheet open={createOpen} onClose={() => setCreateOpen(false)} />
    </div>
  );
}
