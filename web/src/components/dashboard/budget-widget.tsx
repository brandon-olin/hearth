"use client";

import { useRouter } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import { apiBaseUrl } from "@/lib/api/client";
import { fetchWithAuth } from "@/lib/api/fetch-with-auth";
import { Loader2, TrendingDown, TrendingUp } from "lucide-react";
import { cn } from "@/lib/utils";
import type { BudgetWidgetConfig } from "@/lib/dashboard/types";

// ── Types ─────────────────────────────────────────────────────────────────────

interface BudgetSummary {
  total_income: number;
  total_expenses: number;
  transaction_count: number;
}

// ── Helpers ───────────────────────────────────────────────────────────────────

function fmt(amount: number, compact = false): string {
  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: "USD",
    minimumFractionDigits: compact ? 0 : 2,
    maximumFractionDigits: compact ? 0 : 2,
  }).format(Math.abs(amount));
}

const MONTH_NAMES = [
  "January", "February", "March", "April", "May", "June",
  "July", "August", "September", "October", "November", "December",
];

// ── Widget ────────────────────────────────────────────────────────────────────

export function BudgetWidget({ config }: { config: BudgetWidgetConfig }) {
  const router = useRouter();
  const now = new Date();
  const year = now.getFullYear();
  const month = now.getMonth() + 1;
  const monthName = MONTH_NAMES[now.getMonth()];

  // Month-to-date range
  const from = `${year}-${String(month).padStart(2, "0")}-01`;
  const to = now.toISOString().slice(0, 10);

  const { data, isLoading, isError } = useQuery<BudgetSummary>({
    queryKey: ["budget", "summary", "widget", year, month],
    queryFn: async () => {
      const p = new URLSearchParams({ date_from: from, date_to: to });
      const res = await fetchWithAuth(`${apiBaseUrl}/budget/summary?${p}`);
      if (!res.ok) throw new Error("Failed to load budget summary");
      return res.json() as Promise<BudgetSummary>;
    },
    staleTime: 5 * 60 * 1000, // 5 min
  });

  const expenses = data?.total_expenses ?? 0;
  const income = data?.total_income ?? 0;
  const target = config.monthly_target;
  const hasTarget = target != null && target > 0;
  const pct = hasTarget ? Math.min((expenses / target!) * 100, 100) : 0;
  const overBudget = hasTarget && expenses > target!;
  const remaining = hasTarget ? target! - expenses : null;

  return (
    <button
      type="button"
      onClick={() => router.push("/budget")}
      className="w-full text-left group"
    >
      {/* Header */}
      <div className="flex items-center justify-between mb-3">
        <h2 className="text-sm font-semibold">Budget</h2>
        <span className="text-xs text-muted-foreground">{monthName}</span>
      </div>

      {isLoading && (
        <div className="flex items-center gap-2 text-sm text-muted-foreground py-2">
          <Loader2 className="h-3.5 w-3.5 animate-spin" />
          Loading…
        </div>
      )}

      {isError && (
        <p className="text-sm text-destructive py-2">Failed to load.</p>
      )}

      {!isLoading && !isError && (
        <div className="space-y-3">
          {/* Spent figure */}
          <div>
            <p className="text-xs text-muted-foreground mb-0.5">Spent</p>
            <p className={cn(
              "text-2xl font-bold tabular-nums",
              overBudget ? "text-red-500" : "text-foreground"
            )}>
              {fmt(expenses, true)}
            </p>
            {hasTarget && (
              <p className="text-xs text-muted-foreground mt-0.5">
                of {fmt(target!, true)} target
              </p>
            )}
          </div>

          {/* Progress bar */}
          {hasTarget && (
            <div className="space-y-1">
              <div className="h-1.5 rounded-full bg-muted overflow-hidden">
                <div
                  className={cn(
                    "h-full rounded-full transition-all",
                    overBudget ? "bg-red-500" : "bg-primary"
                  )}
                  style={{ width: `${pct}%` }}
                />
              </div>
              <p className={cn(
                "text-xs tabular-nums",
                overBudget ? "text-red-500" : "text-muted-foreground"
              )}>
                {overBudget
                  ? `${fmt(expenses - target!, true)} over budget`
                  : `${fmt(remaining!, true)} left`}
              </p>
            </div>
          )}

          {/* Income / net row */}
          {income > 0 && (
            <div className="flex items-center gap-3 pt-1 border-t">
              <div className="flex items-center gap-1 text-xs text-muted-foreground">
                <TrendingUp className="w-3 h-3 text-green-500" />
                <span className="tabular-nums text-green-600 font-medium">{fmt(income, true)}</span>
                <span>in</span>
              </div>
              <div className="flex items-center gap-1 text-xs text-muted-foreground">
                <TrendingDown className="w-3 h-3 text-red-400" />
                <span className="tabular-nums">{fmt(expenses, true)}</span>
                <span>out</span>
              </div>
            </div>
          )}
        </div>
      )}
    </button>
  );
}
