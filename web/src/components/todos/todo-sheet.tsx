"use client";

import { useEffect, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { $api } from "@/lib/api/query";
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
import { Select } from "@/components/ui/select";
import { Label } from "@/components/ui/label";
import { Loader2 } from "lucide-react";
import type { components } from "@/lib/api/schema";

type Todo = components["schemas"]["TodoResponse"];

type FormState = {
  title: string;
  description: string;
  status: "todo" | "in_progress" | "done" | "cancelled";
  priority: "low" | "medium" | "high" | "urgent" | "";
  due_date: string;
};

function blankForm(): FormState {
  return {
    title: "",
    description: "",
    status: "todo",
    priority: "medium",
    due_date: "",
  };
}

function formFromTodo(todo: Todo): FormState {
  return {
    title: todo.title,
    description: todo.description ?? "",
    status: todo.status as FormState["status"],
    priority: (todo.priority ?? "") as FormState["priority"],
    due_date: todo.due_date ?? "",
  };
}

interface TodoSheetProps {
  open: boolean;
  todo: Todo | null;
  onClose: () => void;
}

export function TodoSheet({ open, todo, onClose }: TodoSheetProps) {
  const qc = useQueryClient();
  const isEdit = todo !== null;

  const [form, setForm] = useState<FormState>(blankForm);
  const [saving, setSaving] = useState(false);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Reset form whenever the target todo changes
  useEffect(() => {
    setForm(todo ? formFromTodo(todo) : blankForm());
    setConfirmDelete(false);
    setError(null);
  }, [todo, open]);

  const { mutateAsync: createTodo } = $api.useMutation("post", "/todos");
  const { mutateAsync: updateTodo } = $api.useMutation(
    "patch",
    "/todos/{todo_id}"
  );
  const { mutateAsync: deleteTodo } = $api.useMutation(
    "delete",
    "/todos/{todo_id}"
  );

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
        priority: (form.priority || null) as
          | "low"
          | "medium"
          | "high"
          | "urgent"
          | null,
        due_date: form.due_date || null,
      };

      if (isEdit) {
        await updateTodo({ params: { path: { todo_id: todo.id } }, body });
      } else {
        await createTodo({ body: { ...body, tag_ids: [] } });
      }

      qc.invalidateQueries({ queryKey: ["get", "/todos"] });
      onClose();
    } catch {
      setError("Something went wrong. Please try again.");
    } finally {
      setSaving(false);
    }
  }

  async function handleDelete() {
    if (!todo) return;
    setSaving(true);
    try {
      await deleteTodo({ params: { path: { todo_id: todo.id } } });
      qc.invalidateQueries({ queryKey: ["get", "/todos"] });
      onClose();
    } catch {
      setError("Delete failed. Please try again.");
      setSaving(false);
    }
  }

  return (
    <Sheet open={open} onOpenChange={(o) => !o && onClose()}>
      <SheetContent side="right" showCloseButton className="flex flex-col gap-0 p-0">
        <SheetHeader className="px-6 py-5 border-b shrink-0">
          <SheetTitle>{isEdit ? "Edit to-do" : "New to-do"}</SheetTitle>
          <SheetDescription className="sr-only">
            {isEdit ? "Edit the details of this to-do." : "Create a new to-do item."}
          </SheetDescription>
        </SheetHeader>

        {/* Scrollable form body */}
        <div className="flex-1 overflow-y-auto px-6 py-5 space-y-5">
          {error && (
            <p className="text-sm text-destructive">{error}</p>
          )}

          {/* Title */}
          <div className="space-y-1.5">
            <Label htmlFor="todo-title">Title</Label>
            <Input
              id="todo-title"
              placeholder="What needs to be done?"
              value={form.title}
              onChange={(e) => set("title", e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && handleSave()}
              autoFocus={!isEdit}
            />
          </div>

          {/* Description */}
          <div className="space-y-1.5">
            <Label htmlFor="todo-desc">Description</Label>
            <Textarea
              id="todo-desc"
              placeholder="Add details…"
              value={form.description}
              onChange={(e) => set("description", e.target.value)}
            />
          </div>

          {/* Status + Priority row */}
          <div className="grid grid-cols-2 gap-4">
            <div className="space-y-1.5">
              <Label htmlFor="todo-status">Status</Label>
              <Select
                id="todo-status"
                value={form.status}
                onChange={(e) =>
                  set("status", e.target.value as FormState["status"])
                }
              >
                <option value="todo">To-do</option>
                <option value="in_progress">In progress</option>
                <option value="done">Done</option>
                <option value="cancelled">Cancelled</option>
              </Select>
            </div>

            <div className="space-y-1.5">
              <Label htmlFor="todo-priority">Priority</Label>
              <Select
                id="todo-priority"
                value={form.priority}
                onChange={(e) =>
                  set("priority", e.target.value as FormState["priority"])
                }
              >
                <option value="">None</option>
                <option value="low">Low</option>
                <option value="medium">Medium</option>
                <option value="high">High</option>
                <option value="urgent">Urgent</option>
              </Select>
            </div>
          </div>

          {/* Due date */}
          <div className="space-y-1.5">
            <Label htmlFor="todo-due">Due date</Label>
            <Input
              id="todo-due"
              type="date"
              value={form.due_date}
              onChange={(e) => set("due_date", e.target.value)}
            />
          </div>
        </div>

        {/* Footer actions */}
        <div className="px-6 py-4 border-t shrink-0 space-y-2">
          <div className="flex gap-2">
            <Button
              className="flex-1"
              onClick={handleSave}
              disabled={saving}
            >
              {saving && <Loader2 className="h-4 w-4 mr-2 animate-spin" />}
              {isEdit ? "Save changes" : "Create"}
            </Button>
            <Button variant="outline" onClick={onClose} disabled={saving}>
              Cancel
            </Button>
          </div>

          {isEdit && (
            confirmDelete ? (
              <div className="flex gap-2">
                <Button
                  variant="destructive"
                  className="flex-1"
                  onClick={handleDelete}
                  disabled={saving}
                >
                  {saving && <Loader2 className="h-4 w-4 mr-2 animate-spin" />}
                  Yes, delete
                </Button>
                <Button
                  variant="outline"
                  onClick={() => setConfirmDelete(false)}
                  disabled={saving}
                >
                  Cancel
                </Button>
              </div>
            ) : (
              <Button
                variant="ghost"
                className="w-full text-destructive hover:text-destructive hover:bg-destructive/10"
                onClick={() => setConfirmDelete(true)}
                disabled={saving}
              >
                Delete
              </Button>
            )
          )}
        </div>
      </SheetContent>
    </Sheet>
  );
}
