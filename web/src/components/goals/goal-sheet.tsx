"use client";

import { useEffect, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { $api } from "@/lib/api/query";
import { useAuth } from "@/lib/auth/context";
import { usePermissions } from "@/lib/hooks/use-permissions";
import {
  Sheet,
  SheetContent,
  SheetHeader,
  SheetTitle,
  SheetDescription,
} from "@/components/ui/sheet";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { Label } from "@/components/ui/label";
import { Loader2 } from "lucide-react";
import { VisibilityPicker, type Visibility } from "@/components/visibility-picker";
import type { components } from "@/lib/api/schema";

type Goal = components["schemas"]["GoalResponse"];

type FormState = {
  title: string;
  description: string;
  status: "active" | "completed" | "paused" | "archived";
  priority: "low" | "medium" | "high" | "";
  target_value: string;
  current_value: string;
  unit: string;
  due_date: string;
};

function blankForm(): FormState {
  return {
    title: "",
    description: "",
    status: "active",
    priority: "",
    target_value: "",
    current_value: "",
    unit: "",
    due_date: "",
  };
}

function formFromGoal(goal: Goal): FormState {
  return {
    title: goal.title,
    description: goal.description ?? "",
    status: goal.status as FormState["status"],
    priority: (goal.priority ?? "") as FormState["priority"],
    target_value: goal.target_value ?? "",
    current_value: goal.current_value ?? "",
    unit: goal.unit ?? "",
    due_date: goal.due_date ?? "",
  };
}

interface GoalSheetProps {
  open: boolean;
  goal: Goal | null;
  onClose: () => void;
}

export function GoalSheet({ open, goal, onClose }: GoalSheetProps) {
  const qc = useQueryClient();
  const isEdit = goal !== null;
  const { user } = useAuth();
  const { can } = usePermissions();
  const isOwnItem = !goal || goal.created_by_user_id === (user as { id?: string } | null)?.id;
  const canManageThis = isOwnItem || can("goals", "manage_others");
  const [form, setForm] = useState<FormState>(blankForm());
  const [visibility, setVisibility] = useState<Visibility>("personal");
  const [sharedWith, setSharedWith] = useState<string[]>([]);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (open) {
      setForm(goal ? formFromGoal(goal) : blankForm());
      setVisibility((goal?.visibility as Visibility) ?? "personal");
      setSharedWith(goal?.shared_with_user_ids ?? []);
      setError(null);
    }
  }, [open, goal]);

  const { mutateAsync: createGoal } = $api.useMutation("post", "/goals");
  const { mutateAsync: updateGoal } = $api.useMutation("patch", "/goals/{goal_id}");
  const { mutateAsync: deleteGoal } = $api.useMutation("delete", "/goals/{goal_id}");

  function set<K extends keyof FormState>(key: K, value: FormState[K]) {
    setForm((prev) => ({ ...prev, [key]: value }));
  }

  async function handleSave() {
    if (!form.title.trim()) {
      setError("Title is required.");
      return;
    }
    setSaving(true);
    setError(null);
    try {
      const body = {
        title: form.title.trim(),
        description: form.description.trim() || null,
        status: form.status,
        priority: (form.priority || null) as "low" | "medium" | "high" | null,
        target_value: form.target_value.trim() || null,
        current_value: form.current_value.trim() || null,
        unit: form.unit.trim() || null,
        due_date: form.due_date || null,
        visibility,
        shared_with_user_ids: sharedWith,
      };
      if (isEdit) {
        await updateGoal({ params: { path: { goal_id: goal.id } }, body });
      } else {
        await createGoal({ body });
      }
      qc.invalidateQueries({ queryKey: ["get", "/goals"] });
      onClose();
    } catch {
      setError("Something went wrong. Please try again.");
    } finally {
      setSaving(false);
    }
  }

  async function handleDelete() {
    if (!goal) return;
    setSaving(true);
    try {
      await deleteGoal({ params: { path: { goal_id: goal.id } } });
      qc.invalidateQueries({ queryKey: ["get", "/goals"] });
      onClose();
    } finally {
      setSaving(false);
    }
  }

  const showProgress =
    form.target_value !== "" && form.current_value !== "";
  const progressPct = showProgress
    ? Math.min(
        100,
        Math.round(
          (Number(form.current_value) / Math.max(1, Number(form.target_value))) * 100
        )
      )
    : null;

  return (
    <Sheet open={open} onOpenChange={(o) => !o && onClose()}>
      <SheetContent className="w-full sm:max-w-md overflow-y-auto flex flex-col gap-0 p-0">
        <SheetHeader className="px-6 py-4 border-b">
          <SheetTitle>{isEdit ? "Edit goal" : "New goal"}</SheetTitle>
          <SheetDescription className="sr-only">
            {isEdit ? "Update this goal" : "Create a new goal"}
          </SheetDescription>
        </SheetHeader>

        <div className="flex-1 overflow-y-auto px-6 py-5 space-y-5">
          {/* Title */}
          <div className="space-y-1.5">
            <Label htmlFor="goal-title">Title</Label>
            <Input
              id="goal-title"
              value={form.title}
              onChange={(e) => set("title", e.target.value)}
              placeholder="Learn to cook Thai food"
              autoFocus
            />
          </div>

          {/* Description */}
          <div className="space-y-1.5">
            <Label htmlFor="goal-desc">Description</Label>
            <Textarea
              id="goal-desc"
              value={form.description}
              onChange={(e) => set("description", e.target.value)}
              placeholder="Any notes about this goal…"
              rows={3}
            />
          </div>

          {/* Status + Priority row */}
          <div className="grid grid-cols-2 gap-3">
            <div className="space-y-1.5">
              <Label htmlFor="goal-status">Status</Label>
              <select
                id="goal-status"
                value={form.status}
                onChange={(e) => set("status", e.target.value as FormState["status"])}
                className="flex h-9 w-full rounded-md border border-input bg-transparent px-3 py-1 text-sm shadow-sm focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
              >
                <option value="active">Active</option>
                <option value="paused">Paused</option>
                <option value="completed">Completed</option>
                <option value="archived">Archived</option>
              </select>
            </div>

            <div className="space-y-1.5">
              <Label htmlFor="goal-priority">Priority</Label>
              <select
                id="goal-priority"
                value={form.priority}
                onChange={(e) => set("priority", e.target.value as FormState["priority"])}
                className="flex h-9 w-full rounded-md border border-input bg-transparent px-3 py-1 text-sm shadow-sm focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
              >
                <option value="">None</option>
                <option value="low">Low</option>
                <option value="medium">Medium</option>
                <option value="high">High</option>
              </select>
            </div>
          </div>

          {/* Progress tracking */}
          <div className="space-y-2">
            <Label>Progress tracking (optional)</Label>
            <div className="grid grid-cols-3 gap-2">
              <div className="space-y-1">
                <p className="text-xs text-muted-foreground">Current</p>
                <Input
                  type="number"
                  min="0"
                  value={form.current_value}
                  onChange={(e) => set("current_value", e.target.value)}
                  placeholder="0"
                />
              </div>
              <div className="space-y-1">
                <p className="text-xs text-muted-foreground">Target</p>
                <Input
                  type="number"
                  min="0"
                  value={form.target_value}
                  onChange={(e) => set("target_value", e.target.value)}
                  placeholder="100"
                />
              </div>
              <div className="space-y-1">
                <p className="text-xs text-muted-foreground">Unit</p>
                <Input
                  value={form.unit}
                  onChange={(e) => set("unit", e.target.value)}
                  placeholder="books"
                />
              </div>
            </div>
            {progressPct !== null && (
              <div className="space-y-1 pt-1">
                <div className="flex justify-between text-xs text-muted-foreground">
                  <span>{progressPct}% complete</span>
                  <span>
                    {form.current_value} / {form.target_value}
                    {form.unit ? ` ${form.unit}` : ""}
                  </span>
                </div>
                <div className="h-1.5 w-full rounded-full bg-muted overflow-hidden">
                  <div
                    className="h-full bg-primary rounded-full transition-all"
                    style={{ width: `${progressPct}%` }}
                  />
                </div>
              </div>
            )}
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

          {/* Due date */}
          <div className="space-y-1.5">
            <Label htmlFor="goal-due">Due date</Label>
            <Input
              id="goal-due"
              type="date"
              value={form.due_date}
              onChange={(e) => set("due_date", e.target.value)}
            />
          </div>
        </div>

        {/* Footer */}
        <div className="px-6 py-4 border-t flex items-center gap-2">
          {error && (
            <p className="flex-1 text-sm text-destructive">{error}</p>
          )}
          {!error && <span className="flex-1" />}

          {isEdit && canManageThis && (
            <Button
              variant="ghost"
              size="sm"
              className="text-destructive hover:text-destructive"
              onClick={handleDelete}
              disabled={saving}
            >
              Delete
            </Button>
          )}
          <Button variant="outline" size="sm" onClick={onClose} disabled={saving}>
            Cancel
          </Button>
          {isEdit && !canManageThis ? (
            <span className="text-xs text-muted-foreground">View only</span>
          ) : (
            <Button size="sm" onClick={handleSave} disabled={saving}>
              {saving && <Loader2 className="h-3.5 w-3.5 mr-1.5 animate-spin" />}
              {isEdit ? "Save" : "Create"}
            </Button>
          )}
        </div>
      </SheetContent>
    </Sheet>
  );
}
