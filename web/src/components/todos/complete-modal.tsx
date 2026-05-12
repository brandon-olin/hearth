"use client";

import { Button } from "@/components/ui/button";
import { X } from "lucide-react";

interface CompleteModalProps {
  incompleteCount: number;
  onCompleteAll: () => void;
  onCompleteOnly: () => void;
  onCancel: () => void;
}

export function CompleteModal({
  incompleteCount,
  onCompleteAll,
  onCompleteOnly,
  onCancel,
}: CompleteModalProps) {
  return (
    <div className="fixed inset-0 z-[60] flex items-center justify-center">
      {/* Backdrop */}
      <div
        className="fixed inset-0 bg-black/40"
        onClick={onCancel}
        aria-hidden
      />

      {/* Card */}
      <div className="relative z-[60] bg-background border rounded-lg shadow-xl p-5 max-w-xs w-full mx-4">
        <button
          type="button"
          onClick={onCancel}
          className="absolute top-3 left-3 rounded-md p-1 text-muted-foreground hover:text-foreground hover:bg-muted transition-colors"
          aria-label="Cancel"
        >
          <X className="h-4 w-4" />
        </button>

        <div className="mt-5 mb-4">
          <p className="text-sm font-semibold">Mark complete?</p>
          <p className="text-sm text-muted-foreground mt-1">
            {incompleteCount === 1
              ? "1 subtask is still open."
              : `${incompleteCount} subtasks are still open.`}
          </p>
        </div>

        <div className="flex flex-col gap-2">
          <Button size="sm" className="w-full" onClick={onCompleteAll}>
            Complete all
          </Button>
          <Button
            size="sm"
            variant="outline"
            className="w-full"
            onClick={onCompleteOnly}
          >
            Complete anyway
          </Button>
        </div>
      </div>
    </div>
  );
}
