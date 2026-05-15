"use client";

import { useRef, useState, useEffect } from "react";
import { $api } from "@/lib/api/query";
import { cn } from "@/lib/utils";
import { useAuth } from "@/lib/auth/context";
import { Globe, Lock, Users } from "lucide-react";
import type { components } from "@/lib/api/schema";

type MemberResponse = components["schemas"]["MemberResponse"];

export type Visibility = "household" | "personal" | "members";

interface VisibilityPickerProps {
  value: Visibility;
  sharedWith: string[]; // user_ids
  onChange: (visibility: Visibility, sharedWith: string[]) => void;
}

const OPTIONS: { value: Visibility; label: string; Icon: React.ElementType }[] =
  [
    { value: "household", label: "Everyone", Icon: Globe },
    { value: "personal", label: "Me", Icon: Lock },
    { value: "members", label: "Users", Icon: Users },
  ];

export function VisibilityPicker({
  value,
  sharedWith,
  onChange,
}: VisibilityPickerProps) {
  const { user } = useAuth();
  const [membersOpen, setMembersOpen] = useState(false);
  const containerRef = useRef<HTMLDivElement>(null);

  // Close member list on outside click
  useEffect(() => {
    function handleOutside(e: MouseEvent) {
      if (containerRef.current && !containerRef.current.contains(e.target as Node)) {
        setMembersOpen(false);
      }
    }
    document.addEventListener("mousedown", handleOutside);
    return () => document.removeEventListener("mousedown", handleOutside);
  }, []);

  // Fetch members only once the dropdown has been opened
  const { data: members } = $api.useQuery(
    "get",
    "/households/members",
    {},
    { enabled: value === "members" },
  );

  function handleOption(opt: Visibility) {
    if (opt === "members") {
      if (value === "members") {
        // Already selected — toggle the dropdown open/closed
        setMembersOpen((prev) => !prev);
      } else {
        onChange(opt, sharedWith);
        setMembersOpen(true);
      }
    } else {
      if (value !== opt) onChange(opt, sharedWith);
      setMembersOpen(false);
    }
  }

  function toggleMember(userId: string) {
    const next = sharedWith.includes(userId)
      ? sharedWith.filter((id) => id !== userId)
      : [...sharedWith, userId];
    onChange("members", next);
  }

  // Other household members (exclude self — creator always has access).
  const others: MemberResponse[] = (members ?? []).filter(
    (m) => m.user_id !== user?.id,
  );

  return (
    <div className="space-y-2" ref={containerRef}>
      {/* Pill row */}
      <div className="flex gap-1.5">
        {OPTIONS.map(({ value: opt, label, Icon }) => (
          <button
            key={opt}
            type="button"
            onClick={() => handleOption(opt)}
            className={cn(
              "inline-flex items-center gap-1.5 rounded-full border px-3 py-1 text-xs font-medium transition-colors",
              value === opt
                ? "border-primary bg-primary text-primary-foreground"
                : "border-border bg-background text-muted-foreground hover:border-primary/50 hover:text-foreground",
            )}
          >
            <Icon className="h-3 w-3" />
            {label}
          </button>
        ))}
      </div>

      {/* Member checkboxes — collapsible dropdown, shown only when "members" is active and open */}
      {value === "members" && membersOpen && (
        <div className="mt-1 space-y-1 rounded-md border border-border bg-muted/30 p-2">
          {others.length === 0 ? (
            <p className="text-xs text-muted-foreground px-1">
              No other household members yet.
            </p>
          ) : (
            others.map((m) => {
              const checked = sharedWith.includes(m.user_id);
              return (
                <label
                  key={m.user_id}
                  className="flex cursor-pointer items-center gap-2 rounded px-1 py-0.5 text-sm hover:bg-muted/60"
                >
                  <input
                    type="checkbox"
                    className="checkbox-themed"
                    checked={checked}
                    onChange={() => toggleMember(m.user_id)}
                  />
                  <span className="flex-1 truncate">
                    {m.display_name ?? m.email}
                  </span>
                </label>
              );
            })
          )}
        </div>
      )}
    </div>
  );
}
