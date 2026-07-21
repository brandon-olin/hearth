"use client";

/**
 * proposal-002 — the approval queue on the dashboard.
 *
 * Deliberately count-first: the number is the decision-relevant fact ("is
 * anything waiting on me?"), and the rows below it are the preview that tells
 * you whether it is worth clicking through now. Deciding happens on /proposals,
 * where there is room for a reason field.
 *
 * Shows nothing but a quiet all-clear when the queue is empty, rather than
 * disappearing — a widget that vanishes reads as broken.
 */
import { useRouter } from "next/navigation";
import { ArrowRight, Loader2, ShieldQuestion } from "lucide-react";

import { $api } from "@/lib/api/query";
import { useAuth } from "@/lib/auth/context";
import {
  SOURCE_LABEL,
  expiresIn,
  isApprover,
  proposerLine,
} from "@/lib/proposals/format";

const PREVIEW_ROWS = 3;

export function ProposalsWidget() {
  const router = useRouter();
  const { user } = useAuth();
  const canDecide = isApprover(user?.role);

  const { data, isLoading, isError } = $api.useQuery("get", "/proposals", {
    params: { query: { status: "pending", limit: 20 } },
  });

  if (isLoading) {
    return (
      <div className="flex items-center gap-2 py-2 text-sm text-muted-foreground">
        <Loader2 className="h-3.5 w-3.5 animate-spin" />
        Loading…
      </div>
    );
  }

  if (isError) {
    return <p className="py-2 text-sm text-destructive">Failed to load approvals.</p>;
  }

  const items = data?.items ?? [];
  const total = data?.total ?? 0;

  if (total === 0) {
    return (
      <div className="flex flex-col items-center justify-center gap-2 py-6 text-center">
        <ShieldQuestion className="h-6 w-6 text-muted-foreground/30" />
        <p className="text-xs text-muted-foreground">Nothing waiting for approval.</p>
      </div>
    );
  }

  return (
    <button
      type="button"
      onClick={() => router.push("/proposals")}
      className="group w-full text-left"
    >
      <div className="mb-2 flex items-center justify-between gap-2">
        <div className="flex items-baseline gap-2">
          <span className="text-2xl font-semibold tabular-nums">{total}</span>
          <span className="text-sm text-muted-foreground">
            {total === 1 ? "request waiting" : "requests waiting"}
            {canDecide ? "" : " on an admin"}
          </span>
        </div>
        <ArrowRight className="h-3.5 w-3.5 shrink-0 text-muted-foreground/40 transition-colors group-hover:text-muted-foreground" />
      </div>

      <ul className="space-y-1.5">
        {items.slice(0, PREVIEW_ROWS).map((p) => (
          <li key={p.id} className="min-w-0">
            <p className="truncate text-sm">{p.summary}</p>
            <p className="truncate text-xs text-muted-foreground">
              {proposerLine(p)}
              {" · "}
              {SOURCE_LABEL[p.source] ?? p.source}
              {p.expires_at ? ` · ${expiresIn(p.expires_at)}` : ""}
            </p>
          </li>
        ))}
      </ul>

      {total > PREVIEW_ROWS && (
        <p className="mt-2 text-xs text-muted-foreground">
          +{total - PREVIEW_ROWS} more in the queue
        </p>
      )}
    </button>
  );
}
