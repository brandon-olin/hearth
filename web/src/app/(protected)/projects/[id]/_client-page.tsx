"use client";

import { useState, useCallback, useRef } from "react";
import { useRouter } from "next/navigation";
import { useQueryClient, useQuery } from "@tanstack/react-query";
import { useSegmentId } from "@/lib/hooks/use-segment-id";
import { $api } from "@/lib/api/query";
import { fetchSubtreeProgress } from "@/lib/projects/progress";
import { TodoRow } from "@/components/todos/todo-row";
import { TodoSheet } from "@/components/todos/todo-sheet";
import { QuickAdd } from "@/components/todos/quick-add";
import { Button } from "@/components/ui/button";
import { ProjectCreateSheet } from "@/components/projects/project-create-sheet";
import { Loader2, AlertCircle, Pin, PinOff, ChevronRight, Plus, ChevronLeft, MoreHorizontal, Archive, Trash2, Pencil } from "lucide-react";
import { cn } from "@/lib/utils";
import { ProgressRing } from "@/components/ui/progress-ring";
import { useRouter as useNextRouter } from "next/navigation";
import type { components } from "@/lib/api/schema";

type Todo = components["schemas"]["TodoResponse"];
type Project = components["schemas"]["ProjectResponse"];
type ProjectStatus = Project["status"];

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

const TODO_STATUS_SECTIONS: { status: "pending" | "in_progress"; label: string }[] = [
  { status: "pending",     label: "To-do"       },
  { status: "in_progress", label: "In progress" },
];

// ── Mini progress bar (for sub-project rows) ──────────────────────────────────

function MiniProgressBar({ percent }: { percent: number }) {
  const pct = Math.min(100, Math.max(0, percent));
  return (
    <div className="h-1 w-16 rounded-full bg-muted-foreground/20 overflow-hidden shrink-0">
      <div
        className={cn(
          "h-full rounded-full transition-all",
          pct >= 100 ? "bg-emerald-500" : "bg-primary",
        )}
        style={{ width: `${pct}%` }}
      />
    </div>
  );
}

// ── Sub-project row ───────────────────────────────────────────────────────────

function SubProjectRow({ project }: { project: Project }) {
  const router = useNextRouter();

  // Each sub-project computes its own progress
  const { data: progressVal } = useQuery({
    queryKey: ["project-progress", project.id],
    queryFn: () => fetchSubtreeProgress(project.id),
    enabled: project.status !== "complete" && project.status !== "archived",
  });

  const pct =
    project.status === "complete" || project.status === "archived"
      ? 100
      : progressVal !== undefined
        ? Math.round(progressVal * 100)
        : null;

  return (
    <button
      type="button"
      onClick={() => router.push(`/projects/${project.id}`)}
      className="flex items-center gap-3 w-full px-3 py-2.5 rounded-lg border bg-card hover:bg-muted/30 transition-colors text-left group"
    >
      <div className="flex-1 min-w-0">
        <p className="text-sm font-medium truncate group-hover:text-primary transition-colors">
          {project.name}
        </p>
        {project.description && (
          <p className="text-xs text-muted-foreground truncate mt-0.5">
            {project.description}
          </p>
        )}
      </div>

      <span className={cn("badge shrink-0", STATUS_BADGE[project.status])}>
        {STATUS_LABEL[project.status]}
      </span>

      {pct !== null && <MiniProgressBar percent={pct} />}

      <ChevronRight className="h-3.5 w-3.5 text-muted-foreground shrink-0" />
    </button>
  );
}

// ── Page ──────────────────────────────────────────────────────────────────────

export default function ProjectPage() {
  const id = useSegmentId();
  const router = useRouter();
  const qc = useQueryClient();

  const [sheetOpen, setSheetOpen] = useState(false);
  const [selectedTodo, setSelectedTodo] = useState<Todo | null>(null);
  const [showDone, setShowDone] = useState(false);
  const [subProjectSheetOpen, setSubProjectSheetOpen] = useState(false);
  const [menuOpen, setMenuOpen] = useState(false);
  const [editingName, setEditingName] = useState(false);
  const [nameValue, setNameValue] = useState("");
  const [nameSaving, setNameSaving] = useState(false);
  const nameInputRef = useRef<HTMLInputElement>(null);

  // ── Fetch project ──────────────────────────────────────────────────────────
  const {
    data: project,
    isLoading: projectLoading,
    isError: projectError,
  } = $api.useQuery("get", "/projects/{project_id}", {
    params: { path: { project_id: id } },
  });

  // ── Fetch parent project (for back button) ────────────────────────────────
  const { data: parentProject } = $api.useQuery(
    "get",
    "/projects/{project_id}",
    {
      params: { path: { project_id: project?.parent_id ?? "" } },
    },
    { enabled: !!project?.parent_id },
  );

  // ── Fetch direct sub-projects ──────────────────────────────────────────────
  const { data: childrenData } = $api.useQuery("get", "/projects", {
    params: { query: { parent_id: id } },
    // always enabled — we use the result to decide whether to show the section
  });
  const children = (childrenData?.items ?? []).filter((p) => !p.archived_at);

  // ── Fetch todos for this project ───────────────────────────────────────────
  const { data: todosData, isLoading: todosLoading } = $api.useQuery(
    "get",
    "/todos",
    {
      params: { query: { project_id: id, limit: 500 } },
    },
  );

  const todos = todosData?.items ?? [];
  const activeTodos = todos.filter(
    (t) => t.status !== "done" && t.status !== "cancelled",
  );
  const doneTodos = todos.filter(
    (t) => t.status === "done" || t.status === "cancelled",
  );

  // ── Overall project progress (not shown for system projects like To-dos) ───
  const showProgress = project && !project.is_system;
  const { data: overallProgressVal, isLoading: progressLoading } = useQuery({
    queryKey: ["project-progress", id],
    queryFn: () => fetchSubtreeProgress(id),
    enabled: !!showProgress,
  });

  const overallPct =
    overallProgressVal !== undefined
      ? Math.round(overallProgressVal * 100)
      : null;

  // ── Pin / unpin toggle ─────────────────────────────────────────────────────
  const { mutateAsync: updateProject, isPending: pinToggling } =
    $api.useMutation("patch", "/projects/{project_id}");

  const { mutateAsync: archiveProject } =
    $api.useMutation("post", "/projects/{project_id}/archive");

  const { mutateAsync: deleteProject } =
    $api.useMutation("delete", "/projects/{project_id}");

  const handleArchive = useCallback(async () => {
    setMenuOpen(false);
    await archiveProject({ params: { path: { project_id: id } } });
    qc.invalidateQueries({ queryKey: ["get", "/projects"] });
    router.push(project?.parent_id ? `/projects/${project.parent_id}` : "/projects");
  }, [archiveProject, id, qc, router, project]);

  const handleDelete = useCallback(async () => {
    setMenuOpen(false);
    if (!confirm(`Delete "${project?.name}"? This cannot be undone.`)) return;
    await deleteProject({ params: { path: { project_id: id } } });
    qc.invalidateQueries({ queryKey: ["get", "/projects"] });
    router.push(project?.parent_id ? `/projects/${project.parent_id}` : "/projects");
  }, [deleteProject, id, qc, router, project]);

  const handlePinToggle = useCallback(async () => {
    if (!project) return;
    await updateProject({
      params: { path: { project_id: id } },
      body: { show_in_nav: !project.show_in_nav },
    });
    qc.invalidateQueries({ queryKey: ["get", "/projects/{project_id}"] });
    qc.invalidateQueries({ queryKey: ["get", "/projects"] });
  }, [project, id, updateProject, qc]);

  // ── Inline name editing ────────────────────────────────────────────────────
  const startEditingName = useCallback(() => {
    if (!project) return;
    setNameValue(project.name);
    setEditingName(true);
    // Focus after state update
    setTimeout(() => nameInputRef.current?.select(), 0);
  }, [project]);

  const commitNameEdit = useCallback(async () => {
    const trimmed = nameValue.trim();
    if (!trimmed || trimmed === project?.name) {
      setEditingName(false);
      return;
    }
    setNameSaving(true);
    try {
      await updateProject({
        params: { path: { project_id: id } },
        body: { name: trimmed },
      });
      qc.invalidateQueries({ queryKey: ["get", "/projects/{project_id}"] });
      qc.invalidateQueries({ queryKey: ["get", "/projects"] });
    } finally {
      setNameSaving(false);
      setEditingName(false);
    }
  }, [nameValue, project, updateProject, id, qc]);

  const cancelNameEdit = useCallback(() => {
    setEditingName(false);
    setNameValue("");
  }, []);

  // ── Todo handlers ──────────────────────────────────────────────────────────
  const handleEdit = useCallback((todo: Todo) => {
    setSelectedTodo(todo);
    setSheetOpen(true);
  }, []);

  const handleNew = useCallback(() => {
    setSelectedTodo(null);
    setSheetOpen(true);
  }, []);

  // ── Loading / error states ─────────────────────────────────────────────────
  if (projectLoading) {
    return (
      <div className="flex items-center justify-center h-full gap-2 text-muted-foreground">
        <Loader2 className="h-4 w-4 animate-spin" />
        <span className="text-sm">Loading…</span>
      </div>
    );
  }

  if (projectError || !project) {
    return (
      <div className="flex flex-col items-center justify-center h-full gap-3 text-muted-foreground">
        <AlertCircle className="h-8 w-8 opacity-40" />
        <p className="text-sm">Project not found.</p>
        <Button variant="ghost" size="sm" onClick={() => router.back()}>
          Go back
        </Button>
      </div>
    );
  }

  return (
    <>
      <div className="flex flex-col h-full min-h-full">
        {/* Header */}
        <div className="flex items-center gap-2 px-4 py-3 border-b shrink-0 bg-background">
          {/* Back button — always visible; goes to parent project or projects list */}
          <Button
            variant="ghost"
            size="sm"
            className="h-7 px-1.5 gap-1 text-xs text-muted-foreground hover:text-foreground shrink-0 -ml-1"
            onClick={() =>
              router.push(
                project.parent_id ? `/projects/${project.parent_id}` : "/projects",
              )
            }
          >
            <ChevronLeft className="h-3.5 w-3.5" />
            <span className="hidden sm:inline truncate max-w-[120px]">
              {project.parent_id ? (parentProject?.name ?? "Back") : "Projects"}
            </span>
          </Button>

          {/* Project name — click pencil or double-click to rename */}
          {editingName ? (
            <input
              ref={nameInputRef}
              value={nameValue}
              onChange={(e) => setNameValue(e.target.value)}
              onBlur={commitNameEdit}
              onKeyDown={(e) => {
                if (e.key === "Enter") { e.preventDefault(); commitNameEdit(); }
                if (e.key === "Escape") { e.preventDefault(); cancelNameEdit(); }
              }}
              disabled={nameSaving}
              className="flex-1 text-sm font-semibold bg-background border rounded px-1.5 py-0.5 outline-none focus:ring-1 focus:ring-primary min-w-0"
              autoFocus
            />
          ) : (
            <div className="flex items-center gap-1 flex-1 min-w-0 group/name">
              <h1 className="text-sm font-semibold truncate">{project.name}</h1>
              <button
                type="button"
                onClick={startEditingName}
                title="Rename project"
                className="opacity-0 group-hover/name:opacity-100 transition-opacity shrink-0 p-0.5 rounded hover:bg-muted text-muted-foreground hover:text-foreground"
              >
                <Pencil className="h-3 w-3" />
              </button>
            </div>
          )}

          {/* Pin / unpin button */}
          <Button
            variant="ghost"
            size="sm"
            className={cn(
              "h-7 px-2 gap-1.5 text-xs",
              project.show_in_nav
                ? "text-primary hover:text-primary"
                : "text-muted-foreground hover:text-foreground",
            )}
            onClick={handlePinToggle}
            disabled={pinToggling}
            title={project.show_in_nav ? "Remove from sidebar" : "Pin to sidebar"}
          >
            {pinToggling ? (
              <Loader2 className="h-3.5 w-3.5 animate-spin" />
            ) : project.show_in_nav ? (
              <PinOff className="h-3.5 w-3.5" />
            ) : (
              <Pin className="h-3.5 w-3.5" />
            )}
            {project.show_in_nav ? "Unpin" : "Pin to sidebar"}
          </Button>

          <Button
            size="sm"
            variant="ghost"
            className="h-7 w-7 p-0"
            onClick={handleNew}
          >
            <span className="text-base leading-none">+</span>
          </Button>
        </div>

        {/* Content */}
        <div className="flex-1 overflow-y-auto px-4 py-4 space-y-6">

          {/* ── Progress ring (non-system projects only) ──────────────────── */}
          {showProgress && (children.length > 0 || todos.length > 0) && (
            <div className="flex items-center gap-4 p-4 rounded-xl border bg-card">
              {progressLoading || overallPct === null ? (
                <div className="w-[72px] h-[72px] flex items-center justify-center shrink-0">
                  <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
                </div>
              ) : (
                <div className="w-[72px] h-[72px] shrink-0">
                  <ProgressRing percent={overallPct} strokeWidth={6} />
                </div>
              )}
              <div>
                <p className="text-sm font-semibold">
                  {overallPct === null
                    ? "Calculating…"
                    : overallPct >= 100
                      ? "Complete!"
                      : `${overallPct}% complete`}
                </p>
                <p className="text-xs text-muted-foreground mt-0.5">
                  {children.length > 0
                    ? `Based on ${children.length} sub-project${children.length !== 1 ? "s" : ""}`
                    : `${doneTodos.length} of ${todos.length} tasks done`}
                </p>
              </div>
            </div>
          )}

          {/* ── Sub-projects ──────────────────────────────────────────────── */}
          {(children.length > 0 || true) && (
            <div>
              <div className="flex items-center justify-between mb-2 px-2">
                <p className="text-xs font-semibold text-muted-foreground uppercase tracking-wider">
                  Sub-projects
                </p>
                <div className="flex items-center gap-0.5">
                  <Button
                    variant="ghost"
                    size="sm"
                    className="h-6 px-2 text-xs text-muted-foreground hover:text-foreground"
                    onClick={() => setSubProjectSheetOpen(true)}
                  >
                    <Plus className="h-3 w-3 mr-1" />
                    New
                  </Button>
                  {/* 3-dot project actions menu */}
                  <div className="relative">
                    <Button
                      variant="ghost"
                      size="sm"
                      className="h-6 w-6 p-0 text-muted-foreground hover:text-foreground"
                      onClick={() => setMenuOpen((v) => !v)}
                      title="Project actions"
                    >
                      <MoreHorizontal className="h-3.5 w-3.5" />
                    </Button>
                    {menuOpen && (
                      <>
                        {/* Backdrop */}
                        <div
                          className="fixed inset-0 z-10"
                          onClick={() => setMenuOpen(false)}
                        />
                        <div className="absolute right-0 top-full mt-1 z-20 bg-background border rounded-lg shadow-lg py-1 min-w-[160px]">
                          <button
                            type="button"
                            onClick={handleArchive}
                            className="flex items-center gap-2.5 w-full px-3 py-2 text-sm text-left hover:bg-muted transition-colors"
                          >
                            <Archive className="h-3.5 w-3.5 text-muted-foreground shrink-0" />
                            Archive project
                          </button>
                          {!project.is_system && (
                            <button
                              type="button"
                              onClick={handleDelete}
                              className="flex items-center gap-2.5 w-full px-3 py-2 text-sm text-left hover:bg-destructive/10 text-destructive transition-colors"
                            >
                              <Trash2 className="h-3.5 w-3.5 shrink-0" />
                              Delete project
                            </button>
                          )}
                          <div className="border-t my-1" />
                          <button
                            type="button"
                            onClick={() => setMenuOpen(false)}
                            className="flex items-center gap-2.5 w-full px-3 py-2 text-sm text-left text-muted-foreground hover:bg-muted transition-colors"
                          >
                            Cancel
                          </button>
                        </div>
                      </>
                    )}
                  </div>
                </div>
              </div>
              {children.length > 0 && (
                <div className="space-y-1.5">
                  {children.map((child) => (
                    <SubProjectRow key={child.id} project={child} />
                  ))}
                </div>
              )}
              {children.length === 0 && (
                <p className="text-sm text-muted-foreground px-2 py-1">No sub-projects yet.</p>
              )}
            </div>
          )}

          {/* ── Todos ─────────────────────────────────────────────────────── */}
          {todosLoading && (
            <div className="flex items-center gap-2 text-sm text-muted-foreground py-4">
              <Loader2 className="h-3.5 w-3.5 animate-spin" />
              Loading tasks…
            </div>
          )}

          {!todosLoading && (
            <>
              {/* Active sections */}
              {TODO_STATUS_SECTIONS.map(({ status, label }) => {
                const sectionTodos = activeTodos.filter(
                  (t) => t.status === status,
                );
                if (sectionTodos.length === 0) return null;
                return (
                  <div key={status}>
                    <p className="text-xs font-semibold text-muted-foreground uppercase tracking-wider mb-2 px-2">
                      {label}
                    </p>
                    <div className="space-y-0.5">
                      {sectionTodos.map((todo) => (
                        <TodoRow key={todo.id} todo={todo} onEdit={handleEdit} onToggled={() => qc.invalidateQueries({ queryKey: ["project-progress", id] })} />
                      ))}
                    </div>
                  </div>
                );
              })}

              {/* Empty state */}
              {activeTodos.length === 0 && children.length === 0 && (
                <div className="text-center py-10 text-muted-foreground">
                  <p className="text-sm">No tasks yet.</p>
                  <button
                    type="button"
                    onClick={handleNew}
                    className="mt-2 text-xs text-primary hover:underline"
                  >
                    Add one
                  </button>
                </div>
              )}

              {/* Quick-add */}
              <QuickAdd onOpen={handleNew} className="mt-2" />

              {/* Done / cancelled section */}
              {doneTodos.length > 0 && (
                <div>
                  <button
                    type="button"
                    onClick={() => setShowDone((v) => !v)}
                    className="flex items-center gap-1.5 text-xs font-semibold text-muted-foreground uppercase tracking-wider hover:text-foreground transition-colors px-2 mb-2 cursor-pointer"
                  >
                    <span>{showDone ? "▾" : "▸"}</span>
                    Completed ({doneTodos.length})
                  </button>
                  {showDone && (
                    <div className="space-y-0.5">
                      {doneTodos.map((todo) => (
                        <TodoRow
                          key={todo.id}
                          todo={todo}
                          onEdit={handleEdit}
                          onToggled={() => qc.invalidateQueries({ queryKey: ["project-progress", id] })}
                        />
                      ))}
                    </div>
                  )}
                </div>
              )}
            </>
          )}
        </div>
      </div>

      <TodoSheet
        open={sheetOpen}
        todo={selectedTodo}
        defaultProjectId={id}
        onClose={() => {
          setSheetOpen(false);
          setSelectedTodo(null);
          qc.invalidateQueries({ queryKey: ["get", "/todos"] });
          qc.invalidateQueries({ queryKey: ["project-progress", id] });
        }}
      />

      <ProjectCreateSheet
        open={subProjectSheetOpen}
        defaultParentId={id}
        defaultParentName={project?.name}
        onClose={() => {
          setSubProjectSheetOpen(false);
          qc.invalidateQueries({ queryKey: ["get", "/projects"] });
          qc.invalidateQueries({ queryKey: ["project-progress", id] });
        }}
      />
    </>
  );
}
