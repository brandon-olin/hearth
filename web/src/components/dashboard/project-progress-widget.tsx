"use client";

import { useRouter } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import { $api } from "@/lib/api/query";
import { fetchSubtreeProgress } from "@/lib/projects/progress";
import { cn } from "@/lib/utils";
import { FolderKanban, ArrowRight, Loader2 } from "lucide-react";
import { ProgressRing } from "@/components/ui/progress-ring";
import type { ProjectProgressConfig } from "@/lib/dashboard/types";
import type { components } from "@/lib/api/schema";

type Project = components["schemas"]["ProjectResponse"];
type ProjectStatus = Project["status"];

const STATUS_BADGE: Record<ProjectStatus, string> = {
  backlog: "badge-neutral",
  active: "badge-primary",
  on_deck: "badge-warning",
  in_progress: "badge-progress",
  complete: "badge-success",
  archived: "badge-neutral",
};

const STATUS_LABEL: Record<ProjectStatus, string> = {
  backlog: "Backlog",
  active: "Active",
  on_deck: "On deck",
  in_progress: "In progress",
  complete: "Complete",
  archived: "Archived",
};

export function ProjectProgressWidget({ config }: { config: ProjectProgressConfig }) {
  const router = useRouter();

  const { data, isLoading, isError } = $api.useQuery("get", "/projects", {
    params: { query: { root_only: false, include_archived: false } },
  });

  const project = (data?.items ?? []).find((p) => p.id === config.project_id);

  // Compute progress using the same recursive logic as the project detail page
  const isComplete = project?.status === "complete" || project?.status === "archived";
  const { data: progressVal, isLoading: progressLoading } = useQuery({
    queryKey: ["project-progress", config.project_id],
    queryFn: () => fetchSubtreeProgress(config.project_id),
    enabled: !!project && !isComplete,
  });

  const pct = isComplete
    ? 100
    : progressVal !== undefined
    ? Math.round(progressVal * 100)
    : null;

  if (isLoading) {
    return (
      <div className="flex items-center gap-2 text-sm text-muted-foreground py-2">
        <Loader2 className="h-3.5 w-3.5 animate-spin" />
        Loading…
      </div>
    );
  }

  if (isError || !project) {
    return (
      <div className="flex flex-col items-center justify-center py-6 text-center gap-2">
        <FolderKanban className="h-6 w-6 text-muted-foreground/30" />
        <p className="text-xs text-muted-foreground">Project not found.</p>
      </div>
    );
  }

  return (
    <button
      type="button"
      onClick={() => router.push(`/projects/${project.id}`)}
      className="w-full text-left group"
    >
      {/* Top row: name + badge + arrow */}
      <div className="flex items-center gap-2 mb-5">
        <FolderKanban className="h-3.5 w-3.5 shrink-0 text-muted-foreground" />
        <span className="text-sm font-medium truncate flex-1">{project.name}</span>
        <span className={cn("badge shrink-0", STATUS_BADGE[project.status])}>
          {STATUS_LABEL[project.status]}
        </span>
        <ArrowRight className="h-3.5 w-3.5 shrink-0 text-muted-foreground/40 group-hover:text-muted-foreground transition-colors" />
      </div>

      {/* Progress ring — 2/3 width, centered */}
      {progressLoading && !isComplete ? (
        <div className="w-1/3 aspect-square mx-auto flex items-center justify-center">
          <Loader2 className="h-5 w-5 animate-spin text-muted-foreground/40" />
        </div>
      ) : pct !== null ? (
        <div className="w-1/3 aspect-square mx-auto">
          <ProgressRing percent={pct} />
        </div>
      ) : null}

      {/* Due date below ring */}
      {project.due_date && project.status !== "complete" && (
        <p className="text-[10px] text-muted-foreground/70 text-center mt-2">
          Due {project.due_date}
        </p>
      )}

      {/* Description */}
      {project.description && (
        <p className="text-xs text-muted-foreground line-clamp-1 mt-1 text-center">
          {project.description}
        </p>
      )}
    </button>
  );
}
