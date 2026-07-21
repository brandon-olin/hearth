"use client";

/**
 * proposal-002 — the household approval queue.
 *
 * What an agent asked to do, waiting on a person. Routing is all-admins: every
 * owner/admin sees the same queue and the first decision wins, so the page has
 * to be honest about a proposal someone else just decided rather than offering a
 * button that will 409. Two things make that work — the SSE stream invalidates
 * this query the moment any admin decides (so the row updates live), and a
 * decision that loses the race is surfaced on the row it lost on.
 *
 * A member who is not an approver still gets this page: the API returns only the
 * proposals they submitted themselves, which is how they find out what happened
 * to their own request.
 */
import { useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { Loader2, ShieldQuestion } from "lucide-react";

import { $api } from "@/lib/api/query";
import { useAuth } from "@/lib/auth/context";
import { cn } from "@/lib/utils";
import { ProposalRow } from "@/components/proposals/proposal-row";
import { isApprover } from "@/lib/proposals/format";

const FILTERS = [
  { key: "pending", label: "Waiting" },
  { key: "all", label: "All" },
] as const;

type FilterKey = (typeof FILTERS)[number]["key"];

export default function ProposalsPage() {
  const { user } = useAuth();
  const qc = useQueryClient();
  const canDecide = isApprover(user?.role);

  const [filter, setFilter] = useState<FilterKey>("pending");
  const [busyId, setBusyId] = useState<string | null>(null);
  const [errors, setErrors] = useState<Record<string, string>>({});

  const query = { limit: 100, ...(filter === "pending" ? { status: "pending" } : {}) };
  const { data, isLoading, isError } = $api.useQuery("get", "/proposals", {
    params: { query },
  });

  const approve = $api.useMutation("post", "/proposals/{proposal_id}/approve");
  const reject = $api.useMutation("post", "/proposals/{proposal_id}/reject");

  function refresh() {
    // Both filters, plus the dashboard widget's own query.
    qc.invalidateQueries({
      predicate: (q) => typeof q.queryKey[1] === "string" && q.queryKey[1] === "/proposals",
    });
  }

  async function decide(id: string, run: () => Promise<unknown>) {
    setBusyId(id);
    setErrors((e) => ({ ...e, [id]: "" }));
    try {
      await run();
    } catch (err) {
      // The common case is losing the first-to-decide race. The API's message
      // says so in words; surface it rather than a generic failure.
      const detail =
        (err as { detail?: string })?.detail ??
        (err instanceof Error ? err.message : "Could not save that decision.");
      setErrors((e) => ({ ...e, [id]: detail }));
    } finally {
      setBusyId(null);
      refresh();
    }
  }

  const items = data?.items ?? [];

  return (
    <div className="mx-auto w-full max-w-3xl px-4 py-6 sm:px-6">
      <header className="mb-4">
        <h1 className="text-xl font-semibold">Approvals</h1>
        <p className="mt-1 text-sm text-muted-foreground">
          {canDecide
            ? "Requests from agents and devices waiting on someone in the household. The first decision wins."
            : "Requests you have asked for that are waiting on a household admin."}
        </p>
      </header>

      <div className="mb-2 flex items-center gap-1">
        {FILTERS.map((f) => (
          <button
            key={f.key}
            type="button"
            onClick={() => setFilter(f.key)}
            className={cn(
              "rounded-md px-2.5 py-1 text-xs font-medium transition-colors",
              filter === f.key
                ? "bg-muted text-foreground"
                : "text-muted-foreground hover:text-foreground"
            )}
          >
            {f.label}
          </button>
        ))}
      </div>

      {isLoading && (
        <div className="flex items-center gap-2 py-6 text-sm text-muted-foreground">
          <Loader2 className="h-4 w-4 animate-spin" />
          Loading…
        </div>
      )}

      {isError && (
        <p className="py-6 text-sm text-destructive">Failed to load the approval queue.</p>
      )}

      {!isLoading && !isError && items.length === 0 && (
        <div className="flex flex-col items-center gap-2 rounded-lg border border-dashed py-12 text-center">
          <ShieldQuestion className="h-6 w-6 text-muted-foreground/30" />
          <p className="text-sm text-muted-foreground">
            {filter === "pending" ? "Nothing waiting on you." : "No requests yet."}
          </p>
        </div>
      )}

      {items.length > 0 && (
        <div className="rounded-lg border px-4">
          {items.map((p) => (
            <ProposalRow
              key={p.id}
              proposal={p}
              canDecide={canDecide}
              busy={busyId === p.id}
              error={errors[p.id] || null}
              onApprove={(id) =>
                decide(id, () =>
                  approve.mutateAsync({ params: { path: { proposal_id: id } } })
                )
              }
              onReject={(id, reason) =>
                decide(id, () =>
                  reject.mutateAsync({
                    params: { path: { proposal_id: id } },
                    body: { reason: reason || null },
                  })
                )
              }
            />
          ))}
        </div>
      )}
    </div>
  );
}
