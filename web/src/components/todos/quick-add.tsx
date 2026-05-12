"use client";

import { useRef, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { $api } from "@/lib/api/query";
import { cn } from "@/lib/utils";
import { Plus, Loader2 } from "lucide-react";

interface QuickAddProps {
  /** When set, the created todo belongs to this project */
  projectId?: string;
  /** Called after a todo is successfully created */
  onCreated?: (id: string) => void;
  className?: string;
}

export function QuickAdd({ projectId, onCreated, className }: QuickAddProps) {
  const qc = useQueryClient();
  const inputRef = useRef<HTMLInputElement>(null);
  const [value, setValue] = useState("");
  const [saving, setSaving] = useState(false);
  const [focused, setFocused] = useState(false);

  const { mutateAsync: createTodo } = $api.useMutation("post", "/todos");

  async function handleSubmit() {
    const title = value.trim();
    if (!title || saving) return;

    setSaving(true);
    try {
      const todo = await createTodo({
        body: {
          title,
          status: "pending",
          ...(projectId ? { project_id: projectId } : {}),
        },
      });
      setValue("");
      qc.invalidateQueries({ queryKey: ["get", "/todos"] });
      onCreated?.(todo.id);
    } catch {
      // Leave the text in place so the user can retry
    } finally {
      setSaving(false);
      inputRef.current?.focus();
    }
  }

  function handleKeyDown(e: React.KeyboardEvent<HTMLInputElement>) {
    if (e.key === "Enter") {
      e.preventDefault();
      handleSubmit();
    }
    if (e.key === "Escape") {
      setValue("");
      inputRef.current?.blur();
    }
  }

  return (
    <div
      className={cn(
        "flex items-center gap-2 px-2 py-2 rounded-md border transition-colors",
        focused
          ? "border-border bg-background"
          : "border-dashed border-border/50 hover:border-border/80 bg-transparent",
        className
      )}
    >
      {saving ? (
        <Loader2 className="h-4 w-4 shrink-0 animate-spin text-muted-foreground" />
      ) : (
        <Plus
          className={cn(
            "h-4 w-4 shrink-0 transition-colors",
            focused ? "text-muted-foreground" : "text-muted-foreground/50"
          )}
        />
      )}
      <input
        ref={inputRef}
        type="text"
        placeholder="Add a task…"
        value={value}
        onChange={(e) => setValue(e.target.value)}
        onKeyDown={handleKeyDown}
        onFocus={() => setFocused(true)}
        onBlur={() => setFocused(false)}
        disabled={saving}
        className="flex-1 min-w-0 text-sm bg-transparent outline-none placeholder:text-muted-foreground/40 disabled:cursor-wait"
      />
      {value.trim() && !saving && (
        <span className="text-xs text-muted-foreground/50 shrink-0 select-none">↵</span>
      )}
    </div>
  );
}
