"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import { fetchWithAuth } from "@/lib/api/fetch-with-auth";
import { apiBaseUrl } from "@/lib/api/client";
import { Button } from "@/components/ui/button";
import { ArrowLeft, ChevronLeft, ChevronRight, Loader2, BarChart2 } from "lucide-react";
import { cn } from "@/lib/utils";

// ── Types ─────────────────────────────────────────────────────────────────────

interface CategoryEntry {
  category_id: string | null;
  category_name: string;
  category_color: string | null;
  category_icon: string | null;
  total_expenses: number;
  total_income: number;
  transaction_count: number;
}

interface AnalyticsResponse {
  year: number;
  month: number;
  date_from: string;
  date_to: string;
  total_expenses: number;
  total_income: number;
  transaction_count: number;
  by_category: CategoryEntry[];
}

interface BudgetAccount {
  id: string;
  name: string;
}

// ── Helpers ───────────────────────────────────────────────────────────────────

const MONTH_NAMES = [
  "January", "February", "March", "April", "May", "June",
  "July", "August", "September", "October", "November", "December",
];

function formatCurrency(amount: number): string {
  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: "USD",
    minimumFractionDigits: 0,
    maximumFractionDigits: 0,
  }).format(amount);
}

function formatCurrencyExact(amount: number): string {
  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: "USD",
    minimumFractionDigits: 2,
  }).format(amount);
}

async function fetchAnalytics(
  year: number,
  month: number,
  accountId: string | null,
): Promise<AnalyticsResponse> {
  const params = new URLSearchParams({ year: String(year), month: String(month) });
  if (accountId) params.set("account_id", accountId);
  const res = await fetchWithAuth(`${apiBaseUrl}/budget/analytics?${params.toString()}`);
  if (!res.ok) throw new Error("Failed to load analytics");
  return res.json() as Promise<AnalyticsResponse>;
}

async function fetchAccounts(): Promise<BudgetAccount[]> {
  const res = await fetchWithAuth(`${apiBaseUrl}/budget/accounts`);
  if (!res.ok) throw new Error("Failed to load accounts");
  return res.json() as Promise<BudgetAccount[]>;
}

// ── Category bar row ──────────────────────────────────────────────────────────

function CategoryBar({
  entry,
  maxExpense,
}: {
  entry: CategoryEntry;
  maxExpense: number;
}) {
  const barPct = maxExpense > 0 ? (entry.total_expenses / maxExpense) * 100 : 0;
  const color = entry.category_color ?? "var(--muted-foreground)";

  return (
    <div className="flex items-center gap-3 py-2.5">
      {/* Color dot */}
      <span
        className="w-2.5 h-2.5 rounded-full shrink-0"
        style={{ backgroundColor: color }}
      />

      {/* Name */}
      <div className="w-32 shrink-0 min-w-0">
        <span className="text-sm truncate block">
          {entry.category_icon && <span className="mr-1">{entry.category_icon}</span>}
          {entry.category_name}
        </span>
        <span className="text-xs text-muted-foreground">
          {entry.transaction_count} {entry.transaction_count === 1 ? "txn" : "txns"}
        </span>
      </div>

      {/* Bar */}
      <div className="flex-1 h-5 rounded overflow-hidden bg-muted relative">
        <div
          className="h-full rounded transition-all duration-300"
          style={{
            width: `${barPct}%`,
            backgroundColor: color,
            opacity: 0.8,
          }}
        />
      </div>

      {/* Amount */}
      <span className="text-sm font-medium tabular-nums w-20 text-right shrink-0">
        {formatCurrencyExact(entry.total_expenses)}
      </span>
    </div>
  );
}

// ── Main page ─────────────────────────────────────────────────────────────────

export default function BudgetAnalyticsPage() {
  const router = useRouter();
  const today = new Date();
  const [year, setYear] = useState(today.getFullYear());
  const [month, setMonth] = useState(today.getMonth() + 1); // 1-based
  const [selectedAccount, setSelectedAccount] = useState<string | null>(null);

  const { data: accounts } = useQuery<BudgetAccount[]>({
    queryKey: ["budget", "accounts"],
    queryFn: fetchAccounts,
  });

  const { data, isLoading, isError } = useQuery<AnalyticsResponse>({
    queryKey: ["budget", "analytics", year, month, selectedAccount],
    queryFn: () => fetchAnalytics(year, month, selectedAccount),
  });

  const handlePrevMonth = () => {
    if (month === 1) { setMonth(12); setYear((y) => y - 1); }
    else { setMonth((m) => m - 1); }
  };

  const handleNextMonth = () => {
    const isCurrentMonth = year === today.getFullYear() && month === today.getMonth() + 1;
    if (isCurrentMonth) return;
    if (month === 12) { setMonth(1); setYear((y) => y + 1); }
    else { setMonth((m) => m + 1); }
  };

  const isCurrentMonth = year === today.getFullYear() && month === today.getMonth() + 1;

  const expenseEntries = (data?.by_category ?? []).filter((e) => e.total_expenses > 0);
  const maxExpense = expenseEntries.length > 0
    ? Math.max(...expenseEntries.map((e) => e.total_expenses))
    : 0;

  return (
    <div className="max-w-2xl mx-auto py-6 px-4">

      {/* Back */}
      <button
        onClick={() => router.push("/budget")}
        className="flex items-center gap-1.5 text-sm text-muted-foreground hover:text-foreground transition-colors mb-5"
      >
        <ArrowLeft className="w-3.5 h-3.5" />
        Back to Budget
      </button>

      {/* Header */}
      <div className="flex items-center justify-between mb-5">
        <h1 className="text-lg font-semibold flex items-center gap-2">
          <BarChart2 className="w-4.5 h-4.5 text-muted-foreground" />
          Spending Analytics
        </h1>

        {/* Account selector */}
        {accounts && accounts.length > 1 && (
          <div className="flex items-center gap-1.5 flex-wrap">
            <button
              onClick={() => setSelectedAccount(null)}
              className={cn(
                "rounded-full px-3 py-1 text-xs transition-colors",
                selectedAccount === null
                  ? "bg-primary text-primary-foreground"
                  : "bg-muted text-muted-foreground hover:text-foreground"
              )}
            >
              All
            </button>
            {accounts.map((acc) => (
              <button
                key={acc.id}
                onClick={() => setSelectedAccount(acc.id)}
                className={cn(
                  "rounded-full px-3 py-1 text-xs transition-colors",
                  selectedAccount === acc.id
                    ? "bg-primary text-primary-foreground"
                    : "bg-muted text-muted-foreground hover:text-foreground"
                )}
              >
                {acc.name}
              </button>
            ))}
          </div>
        )}
      </div>

      {/* Month picker */}
      <div className="flex items-center gap-3 mb-5">
        <button
          onClick={handlePrevMonth}
          className="p-1.5 rounded-full bg-muted text-muted-foreground hover:text-foreground transition-colors"
        >
          <ChevronLeft className="w-4 h-4" />
        </button>
        <span className="text-base font-medium min-w-[9rem] text-center">
          {MONTH_NAMES[month - 1]} {year}
        </span>
        <button
          onClick={handleNextMonth}
          disabled={isCurrentMonth}
          className={cn(
            "p-1.5 rounded-full bg-muted transition-colors",
            isCurrentMonth
              ? "text-muted-foreground/40"
              : "text-muted-foreground hover:text-foreground"
          )}
        >
          <ChevronRight className="w-4 h-4" />
        </button>
      </div>

      {/* Summary cards */}
      {data && (
        <div className="grid grid-cols-2 gap-3 mb-6">
          <div className="rounded-lg border px-4 py-3">
            <p className="text-xs text-muted-foreground mb-0.5">Total expenses</p>
            <p className="text-xl font-semibold">{formatCurrency(data.total_expenses)}</p>
            <p className="text-xs text-muted-foreground mt-0.5">{data.transaction_count} transactions</p>
          </div>
          <div className="rounded-lg border px-4 py-3">
            <p className="text-xs text-muted-foreground mb-0.5">Total income</p>
            <p className="text-xl font-semibold text-green-600">{formatCurrency(data.total_income)}</p>
            <p className="text-xs text-muted-foreground mt-0.5">
              Net {data.total_income - data.total_expenses >= 0 ? "+" : ""}{formatCurrency(data.total_income - data.total_expenses)}
            </p>
          </div>
        </div>
      )}

      {/* Chart */}
      {isLoading && (
        <div className="flex items-center justify-center py-16 text-muted-foreground gap-2 text-sm">
          <Loader2 className="w-4 h-4 animate-spin" /> Loading…
        </div>
      )}

      {isError && (
        <p className="text-center text-sm text-muted-foreground py-8">Failed to load analytics.</p>
      )}

      {!isLoading && !isError && data && (
        <>
          {expenseEntries.length === 0 ? (
            <div className="flex flex-col items-center justify-center py-16 gap-3 text-center">
              <BarChart2 className="w-8 h-8 text-muted-foreground" />
              <p className="text-sm text-muted-foreground">No expenses recorded for this month.</p>
              <Button size="sm" variant="outline" onClick={() => router.push("/budget/import")}>
                Import transactions
              </Button>
            </div>
          ) : (
            <div className="rounded-lg border px-4 py-2 divide-y">
              {expenseEntries.map((entry) => (
                <CategoryBar
                  key={entry.category_id ?? "__uncategorized__"}
                  entry={entry}
                  maxExpense={maxExpense}
                />
              ))}
            </div>
          )}

          {/* Income breakdown — only shown if any income by category */}
          {data.by_category.some((e) => e.total_income > 0) && (
            <div className="mt-6">
              <h2 className="text-sm font-medium text-muted-foreground mb-3">Income by category</h2>
              <div className="rounded-lg border px-4 py-2 divide-y">
                {data.by_category
                  .filter((e) => e.total_income > 0)
                  .sort((a, b) => b.total_income - a.total_income)
                  .map((entry) => {
                    const maxIncome = Math.max(...data.by_category.map((e) => e.total_income));
                    const barPct = maxIncome > 0 ? (entry.total_income / maxIncome) * 100 : 0;
                    const color = entry.category_color ?? "var(--muted-foreground)";
                    return (
                      <div key={(entry.category_id ?? "__uncategorized__") + "_income"} className="flex items-center gap-3 py-2.5">
                        <span className="w-2.5 h-2.5 rounded-full shrink-0" style={{ backgroundColor: color }} />
                        <div className="w-32 shrink-0 min-w-0">
                          <span className="text-sm truncate block">
                            {entry.category_icon && <span className="mr-1">{entry.category_icon}</span>}
                            {entry.category_name}
                          </span>
                        </div>
                        <div className="flex-1 h-5 rounded overflow-hidden bg-muted">
                          <div
                            className="h-full rounded transition-all duration-300"
                            style={{ width: `${barPct}%`, backgroundColor: "var(--badge-success-fg)" }}
                          />
                        </div>
                        <span className="text-sm font-medium tabular-nums w-20 text-right shrink-0 text-green-600">
                          {formatCurrencyExact(entry.total_income)}
                        </span>
                      </div>
                    );
                  })}
              </div>
            </div>
          )}
        </>
      )}
    </div>
  );
}
