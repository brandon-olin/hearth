"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { useQueryClient } from "@tanstack/react-query";
import { $api } from "@/lib/api/query";
import { Button } from "@/components/ui/button";
import {
  Sheet,
  SheetContent,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet";
import { Loader2 } from "lucide-react";
import { VisibilityPicker, type Visibility } from "@/components/visibility-picker";
import { Label } from "@/components/ui/label";
import type { components } from "@/lib/api/schema";

type ProjectStatus = components["schemas"]["ProjectResponse"]["status"];

const STATUS_OPTIONS: ProjectStatus[] = [
  "backlog", "active", "on_deck", "in_progress", "complete", "archived",
];

const STATUS_LABEL: Record<ProjectStatus, string> = {
  backlog:     "Backlog",
  active:      "Active",
  on_deck:     "On deck",
  in_progress: "In progress",
  complete:    "Complete",
  archived:    "Archived",
};

interface ProjectCreateSheetProps {
  open: boolean;
  onClose: () => void;
  /**
   * When set, the new project is created as a child of this project.
   * The parent picker is hidden and the value is fixed.
   */
  defaultParentId?: string;
  /** Display name for the parent, shown as read-only context when defaultParentId is set. */
  defaultParentName?: string;
}

export function ProjectCreateSheet({
  open,
  onClose,
  defaultParentId,
  defaultParentName,
}: ProjectCreateSheetProps) {
  const qc = useQueryClient();
  const router = useRouter();

  const [name, setName]               = useState("");
  const [description, setDescription] = useState("");
  const [status, setStatus]           = useState<ProjectStatus>("active");
  const [dueDate, setDueDate]         = useState("");
  const [parentId, setParentId]       = useState<string>(defaultParentId ?? "");
  const [visibility, setVisibility]   = useState<Visibility>("household");
  const [sharedWith, setSharedWith]   = useState<string[]>([]);

  // Only fetch the parent picker list when no defaultParentId is provided
  const { data: projectsData } = $api.useQuery("get", "/projects", {
    params: { query: { root_only: true } },
    enabled: !defaultParentId,
  });

  const { mutateAsync: createProject, isPending } = $api.useMutation("post", "/projects");

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!name.trim()) return;
    const result = await createProject({
      body: {
        name: name.trim(),
        description: description.trim() || null,
        status,
        due_date: dueDate || null,
        parent_id: parentId || null,
        show_in_nav: false,
        sort_order: 0,
        visibility,
        shared_with_user_ids: sharedWith,
      },
    });
    qc.invalidateQueries({ queryKey: ["get", "/projects"] });
    handleClose();
    router.push(`/projects/${result.id}`);
  }

  function handleClose() {
    setName("");
    setDescription("");
    setStatus("active");
    setDueDate("");
    setParentId(defaultParentId ?? "");
    setVisibility("household");
    setSharedWith([]);
    onClose();
  }

  const parentOptions = (projectsData?.items ?? []).filter((p) => !p.is_system);

  const fieldClass =
    "w-full rounded-md border bg-background px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-ring";

  return (
    <Sheet open={open} onOpenChange={(o) => !o && handleClose()}>
      <SheetContent side="right" className="w-full sm:max-w-md overflow-y-auto">
        <SheetHeader>
          <SheetTitle>
            {defaultParentId ? `New sub-project` : "New project"}
          </SheetTitle>
        </SheetHeader>

        <form onSubmit={handleSubmit} className="px-4 pb-4 space-y-4">
          {/* Parent context — read-only when defaultParentId is set */}
          {defaultParentId && defaultParentName && (
            <div className="space-y-1.5">
              <label className="text-sm font-medium text-muted-foreground">Parent project</label>
              <div className="rounded-md border bg-muted/40 px-3 py-2 text-sm text-muted-foreground">
                {defaultParentName}
              </div>
            </div>
          )}

          {/* Parent picker — only shown when creating a top-level project */}
          {!defaultParentId && parentOptions.length > 0 && (
            <div className="space-y-1.5">
              <label className="text-sm font-medium text-muted-foreground">
                Parent project
                <span className="ml-1 font-normal">(optional)</span>
              </label>
              <select
                value={parentId}
                onChange={(e) => setParentId(e.target.value)}
                className={fieldClass}
              >
                <option value="">— None (top-level) —</option>
                {parentOptions.map((p) => (
                  <option key={p.id} value={p.id}>{p.name}</option>
                ))}
              </select>
            </div>
          )}

          {/* Name */}
          <div className="space-y-1.5">
            <label className="text-sm font-medium">Name</label>
            <input
              autoFocus
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="Project name"
              className={fieldClass}
              required
            />
          </div>

          {/* Description */}
          <div className="space-y-1.5">
            <label className="text-sm font-medium text-muted-foreground">
              Description
              <span className="ml-1 font-normal">(optional)</span>
            </label>
            <textarea
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              placeholder="A short summary…"
              rows={2}
              className={`${fieldClass} resize-none`}
            />
          </div>

          {/* Status + Due date */}
          <div className="grid grid-cols-2 gap-3">
            <div className="space-y-1.5">
              <label className="text-sm font-medium">Status</label>
              <select
                value={status}
                onChange={(e) => setStatus(e.target.value as ProjectStatus)}
                className={fieldClass}
              >
                {STATUS_OPTIONS.filter((s) => s !== "archived").map((s) => (
                  <option key={s} value={s}>{STATUS_LABEL[s]}</option>
                ))}
              </select>
            </div>
            <div className="space-y-1.5">
              <label className="text-sm font-medium text-muted-foreground">
                Due date
                <span className="ml-1 font-normal">(optional)</span>
              </label>
              <input
                type="date"
                value={dueDate}
                onChange={(e) => setDueDate(e.target.value)}
                className={fieldClass}
              />
            </div>
          </div>

          {/* Visibility */}
          <div className="space-y-1.5">
            <Label>Visibility</Label>
            <VisibilityPicker
              value={visibility}
              sharedWith={sharedWith}
              onChange={(v, sw) => { setVisibility(v); setSharedWith(sw); }}
            />
          </div>

          <div className="flex justify-end gap-2 pt-2">
            <Button type="button" variant="outline" onClick={handleClose} disabled={isPending}>
              Cancel
            </Button>
            <Button type="submit" disabled={!name.trim() || isPending}>
              {isPending && <Loader2 className="h-4 w-4 mr-1.5 animate-spin" />}
              Create
            </Button>
          </div>
        </form>
      </SheetContent>
    </Sheet>
  );
}
