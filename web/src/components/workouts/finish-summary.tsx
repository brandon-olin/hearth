"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { useQueryClient } from "@tanstack/react-query";
import { CheckCircle2, ClipboardList, Loader2 } from "lucide-react";
import { $api } from "@/lib/api/query";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { formatDuration, formatVolume } from "@/lib/workouts/session-logging";
import { useSaveAsTemplatePrompt } from "@/lib/workouts/use-template-prompt";
import type { components } from "@/lib/api/schema";

type Summary = components["schemas"]["WorkoutSessionSummary"];

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div className="border rounded-lg bg-card px-4 py-3">
      <p className="text-lg font-semibold tabular-nums">{value}</p>
      <p className="text-xs text-muted-foreground">{label}</p>
    </div>
  );
}

/**
 * The post-workout screen: what was done, then the offer to keep it.
 *
 * The save-as-template PROMPT only appears when the session did NOT start from a
 * template (you already have that template) and the member hasn't turned it off.
 * The save-as-template ACTION stays available as a secondary button either way —
 * turning off the prompt silences the interruption, it doesn't remove the
 * capability.
 */
export function FinishSummary({
  sessionId,
  summary,
  onDone,
  onError,
}: {
  sessionId: string;
  summary: Summary;
  onDone: () => void;
  onError: (message: string) => void;
}) {
  const router = useRouter();
  const qc = useQueryClient();
  const { enabled: promptEnabled, setEnabled } = useSaveAsTemplatePrompt();

  const saveAsTemplate = $api.useMutation(
    "post",
    "/workouts/sessions/{session_id}/save-as-template",
  );

  const shouldPrompt = !summary.from_template && promptEnabled;
  const [promptOpen, setPromptOpen] = useState(shouldPrompt);
  const [dontAsk, setDontAsk] = useState(false);
  const [naming, setNaming] = useState(false);
  const [name, setName] = useState(summary.name ?? "");
  const [saved, setSaved] = useState(false);

  async function handleSave(templateName: string) {
    try {
      const template = await saveAsTemplate.mutateAsync({
        params: { path: { session_id: sessionId } },
        body: { name: templateName.trim() || null },
      });
      qc.invalidateQueries({ queryKey: ["get", "/workouts/templates"] });
      setSaved(true);
      setPromptOpen(false);
      setNaming(false);
      router.push(`/workouts/templates/${template.id}`);
    } catch {
      onError("Couldn't save this workout as a template.");
    }
  }

  async function handleSkip() {
    setPromptOpen(false);
    if (dontAsk) {
      try {
        await setEnabled(false);
      } catch {
        onError("Couldn't save that preference.");
      }
    }
  }

  return (
    <div className="page-content pb-12">
      <div className="flex items-center gap-2 mb-6">
        <CheckCircle2 className="h-5 w-5 text-primary shrink-0" />
        <h1 className="text-xl font-semibold truncate">
          {summary.name ?? "Workout"} complete
        </h1>
      </div>

      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 mb-6">
        <Stat label="Duration" value={formatDuration(summary.duration_seconds)} />
        <Stat
          label="Volume (working sets)"
          value={formatVolume(summary.working_volume, summary.volume_unit)}
        />
        <Stat
          label="Exercises completed"
          value={`${summary.exercises_completed}/${summary.exercise_count}`}
        />
        <Stat label="Working sets" value={String(summary.working_sets_completed)} />
      </div>

      {summary.warmup_sets_completed > 0 && (
        <p className="text-xs text-muted-foreground mb-6">
          {summary.warmup_sets_completed} warmup{" "}
          {summary.warmup_sets_completed === 1 ? "set" : "sets"} logged — excluded from volume.
        </p>
      )}

      {promptOpen && (
        <div className="border rounded-lg bg-card p-4 space-y-3 mb-6">
          <p className="text-sm font-medium">Save this as a template?</p>
          <p className="text-xs text-muted-foreground">
            You built this workout as you went. Saving it as a template lets you
            start it again in one tap — and shares it with your household.
          </p>
          <label className="flex items-center gap-2 text-xs text-muted-foreground">
            <input
              type="checkbox"
              className="checkbox-themed"
              checked={dontAsk}
              onChange={(e) => setDontAsk(e.target.checked)}
            />
            Don&apos;t ask me again
          </label>
          <div className="flex items-center gap-2">
            <Button
              size="sm"
              onClick={() => handleSave(name)}
              disabled={saveAsTemplate.isPending}
            >
              {saveAsTemplate.isPending
                ? <Loader2 className="h-4 w-4 mr-1 animate-spin" />
                : <ClipboardList className="h-4 w-4 mr-1" />}
              Save template
            </Button>
            <Button size="sm" variant="ghost" onClick={handleSkip}>
              Skip
            </Button>
          </div>
        </div>
      )}

      {naming && (
        <div className="border rounded-lg bg-card p-4 space-y-3 mb-6">
          <div className="space-y-1.5">
            <Label htmlFor="template-name" className="text-xs">Template name</Label>
            <Input
              id="template-name"
              autoFocus
              value={name}
              onChange={(e) => setName(e.target.value)}
              onKeyDown={(e) => { if (e.key === "Enter") handleSave(name); }}
              placeholder="e.g. Push Day"
            />
          </div>
          <div className="flex items-center gap-2">
            <Button size="sm" onClick={() => handleSave(name)} disabled={saveAsTemplate.isPending}>
              {saveAsTemplate.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : "Save template"}
            </Button>
            <Button size="sm" variant="ghost" onClick={() => setNaming(false)}>Cancel</Button>
          </div>
        </div>
      )}

      <div className="flex items-center gap-2">
        <Button onClick={onDone}>Done</Button>
        {!saved && !naming && (
          <Button variant="outline" onClick={() => { setPromptOpen(false); setNaming(true); }}>
            <ClipboardList className="h-4 w-4 mr-1" /> Save as template
          </Button>
        )}
      </div>
    </div>
  );
}
