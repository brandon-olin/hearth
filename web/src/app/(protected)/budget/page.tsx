"use client";

import { useState, useRef, useEffect, useCallback } from "react";
import { useRouter } from "next/navigation";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { apiBaseUrl } from "@/lib/api/client";
import { fetchWithAuth } from "@/lib/api/fetch-with-auth";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  Upload,
  Download,
  Loader2,
  ChevronLeft,
  ChevronRight,
  Wallet,
  Pencil,
  Trash2,
  Check,
  X,
  Tag,
  Sparkles,
} from "lucide-react";
import { cn } from "@/lib/utils";

// ── Types ─────────────────────────────────────────────────────────────────────

interface BudgetAccount {
  id: string;
  name: string;
  account_type: string;
  scope: string;
  currency: string;
}

interface BudgetCategory {
  id: string;
  name: string;
  color: string | null;
  icon: string | null;
  keywords: string[] | null;
}

interface BudgetTransaction {
  id: string;
  account_id: string;
  category_id: string | null;
  date: string;
  amount: number;
  currency: string;
  description: string;
  merchant_name: string | null;
  scope: string;
  import_source: string | null;
}

interface TransactionListResponse {
  items: BudgetTransaction[];
  total: number;
  limit: number;
  offset: number;
}

interface BudgetSummary {
  total_income: number;
  total_expenses: number;
  transaction_count: number;
  date_from: string | null;
  date_to: string | null;
}

// ── Date range helpers ────────────────────────────────────────────────────────

type DateRangePreset = "mtd" | "30d" | "60d" | "90d" | "custom";

function toISODate(d: Date): string {
  return d.toISOString().slice(0, 10);
}

function presetToDates(preset: DateRangePreset, customFrom: string, customTo: string): { from: string; to: string } {
  const today = new Date();
  const to = toISODate(today);
  if (preset === "mtd") {
    const from = toISODate(new Date(today.getFullYear(), today.getMonth(), 1));
    return { from, to };
  }
  if (preset === "30d") {
    const d = new Date(today); d.setDate(d.getDate() - 30);
    return { from: toISODate(d), to };
  }
  if (preset === "60d") {
    const d = new Date(today); d.setDate(d.getDate() - 60);
    return { from: toISODate(d), to };
  }
  if (preset === "90d") {
    const d = new Date(today); d.setDate(d.getDate() - 90);
    return { from: toISODate(d), to };
  }
  // custom
  return { from: customFrom, to: customTo };
}

// ── API helpers ───────────────────────────────────────────────────────────────

async function fetchSummary(
  accountId: string | null,
  dateFrom: string,
  dateTo: string
): Promise<BudgetSummary> {
  const params = new URLSearchParams({ date_from: dateFrom, date_to: dateTo });
  if (accountId) params.set("account_id", accountId);
  const res = await fetchWithAuth(`${apiBaseUrl}/budget/summary?${params.toString()}`);
  if (!res.ok) throw new Error("Failed to load summary");
  return res.json() as Promise<BudgetSummary>;
}

async function fetchAccounts(): Promise<BudgetAccount[]> {
  const res = await fetchWithAuth(`${apiBaseUrl}/budget/accounts`);
  if (!res.ok) throw new Error("Failed to load accounts");
  return res.json() as Promise<BudgetAccount[]>;
}

async function fetchCategories(): Promise<BudgetCategory[]> {
  const res = await fetchWithAuth(`${apiBaseUrl}/budget/categories`);
  if (!res.ok) throw new Error("Failed to load categories");
  return res.json() as Promise<BudgetCategory[]>;
}

async function fetchTransactions(
  accountId: string | null,
  offset: number,
  limit: number
): Promise<TransactionListResponse> {
  const params = new URLSearchParams({ limit: String(limit), offset: String(offset) });
  if (accountId) params.set("account_id", accountId);
  const res = await fetchWithAuth(`${apiBaseUrl}/budget/transactions?${params.toString()}`);
  if (!res.ok) throw new Error("Failed to load transactions");
  return res.json() as Promise<TransactionListResponse>;
}

async function renameAccount(id: string, name: string): Promise<BudgetAccount> {
  const res = await fetchWithAuth(`${apiBaseUrl}/budget/accounts/${id}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ name }),
  });
  if (!res.ok) throw new Error("Failed to rename account");
  return res.json() as Promise<BudgetAccount>;
}

async function deleteAllTransactions(accountId: string | null): Promise<{ deleted: number }> {
  const params = accountId ? `?account_id=${accountId}` : "";
  const res = await fetchWithAuth(`${apiBaseUrl}/budget/transactions${params}`, {
    method: "DELETE",
  });
  if (!res.ok) throw new Error("Failed to delete transactions");
  return res.json() as Promise<{ deleted: number }>;
}

async function assignCategory(txnId: string, categoryId: string | null): Promise<void> {
  const res = await fetchWithAuth(`${apiBaseUrl}/budget/transactions/${txnId}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ category_id: categoryId }),
  });
  if (!res.ok) throw new Error("Failed to update category");
}

async function runAutoCategorize(accountId: string | null): Promise<{ updated: number }> {
  const params = accountId ? `?account_id=${accountId}` : "";
  const res = await fetchWithAuth(`${apiBaseUrl}/budget/auto-categorize${params}`, {
    method: "POST",
  });
  if (!res.ok) throw new Error("Auto-categorize failed");
  return res.json() as Promise<{ updated: number }>;
}

// ── Formatting ────────────────────────────────────────────────────────────────

function formatAmount(amount: number, currency: string): string {
  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency,
    minimumFractionDigits: 2,
  }).format(Math.abs(amount));
}

function formatDate(dateStr: string): string {
  const d = new Date(dateStr + "T00:00:00");
  return d.toLocaleDateString("en-US", { month: "short", day: "numeric" });
}

const PAGE_SIZE = 50;

// ── Account tab with inline rename ────────────────────────────────────────────

function AccountTab({
  account,
  selected,
  onSelect,
  onRenamed,
}: {
  account: BudgetAccount;
  selected: boolean;
  onSelect: () => void;
  onRenamed: () => void;
}) {
  const [editing, setEditing] = useState(false);
  const [value, setValue] = useState(account.name);
  const [saving, setSaving] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (editing) inputRef.current?.focus();
  }, [editing]);

  const handleSave = async () => {
    const trimmed = value.trim();
    if (!trimmed || trimmed === account.name) { setValue(account.name); setEditing(false); return; }
    setSaving(true);
    try {
      await renameAccount(account.id, trimmed);
      onRenamed();
      setEditing(false);
    } catch { setValue(account.name); }
    finally { setSaving(false); }
  };

  if (editing) {
    return (
      <div className="flex items-center gap-1 shrink-0">
        <Input
          ref={inputRef}
          value={value}
          onChange={(e) => setValue(e.target.value)}
          onKeyDown={(e) => { if (e.key === "Enter") void handleSave(); if (e.key === "Escape") { setValue(account.name); setEditing(false); } }}
          className="h-7 text-sm w-36 px-2"
        />
        <button onClick={() => void handleSave()} disabled={saving} className="p-1 text-green-600 hover:text-green-700">
          {saving ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Check className="w-3.5 h-3.5" />}
        </button>
        <button onClick={() => { setValue(account.name); setEditing(false); }} className="p-1 text-muted-foreground hover:text-foreground">
          <X className="w-3.5 h-3.5" />
        </button>
      </div>
    );
  }

  return (
    <div className="flex items-center gap-1 shrink-0 group">
      <button
        onClick={onSelect}
        className={cn(
          "rounded-full px-3 py-1 text-sm transition-colors",
          selected ? "bg-primary text-primary-foreground" : "bg-muted text-muted-foreground hover:text-foreground"
        )}
      >
        {account.name}
      </button>
      <button
        onClick={() => setEditing(true)}
        className="opacity-0 group-hover:opacity-100 p-1 text-muted-foreground hover:text-foreground transition-opacity"
      >
        <Pencil className="w-3 h-3" />
      </button>
    </div>
  );
}

// ── Category picker (inline dropdown) ────────────────────────────────────────

function CategoryPicker({
  txn,
  categories,
  onAssigned,
}: {
  txn: BudgetTransaction;
  categories: BudgetCategory[];
  onAssigned: (txnId: string, catId: string | null) => void;
}) {
  const [open, setOpen] = useState(false);
  const [saving, setSaving] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  const assigned = categories.find((c) => c.id === txn.category_id);

  // Close on outside click
  useEffect(() => {
    if (!open) return;
    const handler = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, [open]);

  const handlePick = async (catId: string | null) => {
    setSaving(true);
    try {
      await assignCategory(txn.id, catId);
      onAssigned(txn.id, catId);
    } finally {
      setSaving(false);
      setOpen(false);
    }
  };

  return (
    <div ref={ref} className="relative shrink-0">
      <button
        onClick={() => setOpen((v) => !v)}
        className={cn(
          "flex items-center gap-1 rounded-full px-2 py-0.5 text-xs transition-colors",
          assigned
            ? "text-white"
            : "bg-muted text-muted-foreground hover:text-foreground"
        )}
        style={assigned?.color ? { backgroundColor: assigned.color } : undefined}
      >
        {saving ? (
          <Loader2 className="w-3 h-3 animate-spin" />
        ) : assigned ? (
          <>{assigned.icon && <span>{assigned.icon}</span>} {assigned.name}</>
        ) : (
          <><Tag className="w-3 h-3" /> Categorize</>
        )}
      </button>

      {open && (
        <div className="absolute right-0 top-full mt-1 z-50 w-48 rounded-lg border bg-background shadow-lg py-1 text-sm">
          {categories.map((cat) => (
            <button
              key={cat.id}
              onClick={() => void handlePick(cat.id)}
              className={cn(
                "w-full text-left flex items-center gap-2 px-3 py-1.5 hover:bg-muted transition-colors",
                txn.category_id === cat.id && "bg-muted"
              )}
            >
              <span
                className="w-2.5 h-2.5 rounded-full shrink-0"
                style={{ backgroundColor: cat.color ?? "#94a3b8" }}
              />
              {cat.icon && <span className="text-xs">{cat.icon}</span>}
              {cat.name}
            </button>
          ))}
          {txn.category_id && (
            <>
              <div className="border-t my-1" />
              <button
                onClick={() => void handlePick(null)}
                className="w-full text-left px-3 py-1.5 text-muted-foreground hover:bg-muted transition-colors"
              >
                Remove category
              </button>
            </>
          )}
          {categories.length === 0 && (
            <p className="px-3 py-2 text-muted-foreground text-xs">No categories yet</p>
          )}
        </div>
      )}
    </div>
  );
}

// ── Main page ─────────────────────────────────────────────────────────────────

export default function BudgetPage() {
  const router = useRouter();
  const qc = useQueryClient();
  const [selectedAccount, setSelectedAccount] = useState<string | null>(null);
  const [offset, setOffset] = useState(0);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [autoCategorizing, setAutoCategorizing] = useState(false);
  const [autoCategorizeMsg, setAutoCategorizeMsg] = useState<string | null>(null);
  const [exporting, setExporting] = useState(false);

  // Date range for summary bar
  const [datePreset, setDatePreset] = useState<DateRangePreset>("mtd");
  const [customFrom, setCustomFrom] = useState(() => {
    const d = new Date(); d.setDate(1);
    return toISODate(d);
  });
  const [customTo, setCustomTo] = useState(() => toISODate(new Date()));
  const { from: summaryFrom, to: summaryTo } = presetToDates(datePreset, customFrom, customTo);

  // Local category_id overrides so UI updates instantly without refetch
  const [categoryOverrides, setCategoryOverrides] = useState<Record<string, string | null>>({});

  const { data: accounts, isLoading: accountsLoading } = useQuery<BudgetAccount[]>({
    queryKey: ["budget", "accounts"],
    queryFn: fetchAccounts,
  });

  const { data: categories = [] } = useQuery<BudgetCategory[]>({
    queryKey: ["budget", "categories"],
    queryFn: fetchCategories,
  });

  const { data: txnData, isLoading: txnsLoading } = useQuery<TransactionListResponse>({
    queryKey: ["budget", "transactions", selectedAccount, offset],
    queryFn: () => fetchTransactions(selectedAccount, offset, PAGE_SIZE),
  });

  const { data: summary, isLoading: summaryLoading } = useQuery<BudgetSummary>({
    queryKey: ["budget", "summary", selectedAccount, summaryFrom, summaryTo],
    queryFn: () => fetchSummary(selectedAccount, summaryFrom, summaryTo),
  });

  // Reset overrides when data refreshes
  useEffect(() => { setCategoryOverrides({}); }, [txnData]);

  const transactions = txnData?.items ?? [];
  const total = txnData?.total ?? 0;
  const pageCount = Math.ceil(total / PAGE_SIZE);
  const currentPage = Math.floor(offset / PAGE_SIZE) + 1;

  const currency = transactions[0]?.currency ?? "USD";

  const hasAccounts = accounts && accounts.length > 0;
  const isEmpty = !txnsLoading && transactions.length === 0;

  const handleDeleteAll = async () => {
    setDeleting(true);
    try {
      await deleteAllTransactions(selectedAccount);
      await qc.invalidateQueries({ queryKey: ["budget", "transactions"] });
      await qc.invalidateQueries({ queryKey: ["budget", "summary"] });
      setOffset(0);
    } finally { setDeleting(false); setConfirmDelete(false); }
  };

  const handleAutoCategorize = async () => {
    setAutoCategorizing(true);
    setAutoCategorizeMsg(null);
    try {
      const result = await runAutoCategorize(selectedAccount);
      await qc.invalidateQueries({ queryKey: ["budget", "transactions"] });
      setAutoCategorizeMsg(
        result.updated > 0
          ? `${result.updated} transaction${result.updated !== 1 ? "s" : ""} categorized`
          : "No matches found"
      );
      setTimeout(() => setAutoCategorizeMsg(null), 3000);
    } finally { setAutoCategorizing(false); }
  };

  const handleCategoryAssigned = useCallback((txnId: string, catId: string | null) => {
    setCategoryOverrides((prev) => ({ ...prev, [txnId]: catId }));
  }, []);

  const handleExport = async () => {
    setExporting(true);
    try {
      const params = new URLSearchParams();
      if (selectedAccount) params.set("account_id", selectedAccount);
      const res = await fetchWithAuth(`${apiBaseUrl}/budget/transactions/export?${params.toString()}`);
      if (!res.ok) throw new Error("Export failed");
      const blob = await res.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      const disposition = res.headers.get("Content-Disposition");
      const match = disposition?.match(/filename="([^"]+)"/);
      a.download = match?.[1] ?? "hearth-budget.csv";
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      URL.revokeObjectURL(url);
    } finally {
      setExporting(false);
    }
  };

  // ── Empty state ─────────────────────────────────────────────────────────────

  if (!accountsLoading && !hasAccounts) {
    return (
      <div className="flex flex-col items-center justify-center min-h-[60vh] gap-4 text-center px-4">
        <div className="rounded-full bg-muted p-4">
          <Upload className="w-8 h-8 text-muted-foreground" />
        </div>
        <div>
          <h1 className="text-xl font-semibold mb-1">Budget</h1>
          <p className="text-muted-foreground text-sm max-w-sm">
            Import your bank statements to get started.
          </p>
        </div>
        <Button onClick={() => router.push("/budget/import")}>Import transactions</Button>
      </div>
    );
  }

  // ── Main layout ─────────────────────────────────────────────────────────────

  return (
    <div className="max-w-3xl mx-auto py-6 px-4">

      {/* Header */}
      <div className="flex items-center justify-between mb-4">
        <h1 className="text-lg font-semibold">Budget</h1>
        <div className="flex items-center gap-2">
          <button
            onClick={() => router.push("/budget/categories")}
            className="text-xs text-muted-foreground hover:text-foreground transition-colors"
          >
            Manage categories
          </button>

          {/* Auto-categorize */}
          <Button
            size="sm"
            variant="ghost"
            onClick={() => void handleAutoCategorize()}
            disabled={autoCategorizing || categories.length === 0}
            className="text-muted-foreground"
          >
            {autoCategorizing
              ? <Loader2 className="w-3.5 h-3.5 animate-spin mr-1.5" />
              : <Sparkles className="w-3.5 h-3.5 mr-1.5" />}
            {autoCategorizeMsg ?? "Auto-categorize"}
          </Button>

          {/* Delete all */}
          {confirmDelete ? (
            <div className="flex items-center gap-2 text-sm">
              <span className="text-muted-foreground text-xs">
                Delete {selectedAccount ? "account" : "all"} transactions?
              </span>
              <Button size="sm" variant="destructive" onClick={() => void handleDeleteAll()} disabled={deleting}>
                {deleting && <Loader2 className="w-3 h-3 animate-spin mr-1" />}Delete
              </Button>
              <Button size="sm" variant="ghost" onClick={() => setConfirmDelete(false)} disabled={deleting}>Cancel</Button>
            </div>
          ) : (
            <Button size="sm" variant="ghost" onClick={() => setConfirmDelete(true)} className="text-muted-foreground hover:text-destructive">
              <Trash2 className="w-3.5 h-3.5 mr-1.5" />Delete all
            </Button>
          )}

          <Button
            size="sm"
            variant="ghost"
            onClick={() => void handleExport()}
            disabled={exporting}
            className="text-muted-foreground"
          >
            {exporting
              ? <Loader2 className="w-3.5 h-3.5 animate-spin mr-1.5" />
              : <Download className="w-3.5 h-3.5 mr-1.5" />}
            Export CSV
          </Button>

          <Button size="sm" onClick={() => router.push("/budget/import")}>
            <Upload className="w-3.5 h-3.5 mr-1.5" />Import
          </Button>
        </div>
      </div>

      {/* Account tabs */}
      {!accountsLoading && (
        <div className="flex items-center gap-1.5 mb-5 overflow-x-auto pb-1">
          <button
            onClick={() => { setSelectedAccount(null); setOffset(0); setConfirmDelete(false); }}
            className={cn(
              "shrink-0 rounded-full px-3 py-1 text-sm transition-colors",
              selectedAccount === null ? "bg-primary text-primary-foreground" : "bg-muted text-muted-foreground hover:text-foreground"
            )}
          >
            All accounts
          </button>
          {accounts?.map((acc) => (
            <AccountTab
              key={acc.id}
              account={acc}
              selected={selectedAccount === acc.id}
              onSelect={() => { setSelectedAccount(acc.id); setOffset(0); setConfirmDelete(false); }}
              onRenamed={() => void qc.invalidateQueries({ queryKey: ["budget", "accounts"] })}
            />
          ))}
        </div>
      )}

      {/* Date range selector + summary bar */}
      <div className="mb-5">
        {/* Preset buttons */}
        <div className="flex items-center gap-1.5 mb-3 flex-wrap">
          {(["mtd", "30d", "60d", "90d", "custom"] as DateRangePreset[]).map((p) => (
            <button
              key={p}
              onClick={() => setDatePreset(p)}
              className={cn(
                "rounded-full px-3 py-0.5 text-xs font-medium transition-colors",
                datePreset === p
                  ? "bg-primary text-primary-foreground"
                  : "bg-muted text-muted-foreground hover:text-foreground"
              )}
            >
              {p === "mtd" ? "Month to date" : p === "custom" ? "Custom" : p}
            </button>
          ))}
          {datePreset === "custom" && (
            <div className="flex items-center gap-1.5 ml-1">
              <input
                type="date"
                value={customFrom}
                onChange={(e) => setCustomFrom(e.target.value)}
                className="h-6 rounded border bg-background px-2 text-xs text-foreground"
              />
              <span className="text-xs text-muted-foreground">to</span>
              <input
                type="date"
                value={customTo}
                onChange={(e) => setCustomTo(e.target.value)}
                className="h-6 rounded border bg-background px-2 text-xs text-foreground"
              />
            </div>
          )}
        </div>

        {/* Totals */}
        <div className="grid grid-cols-2 gap-3">
          <div className="rounded-lg border px-4 py-3">
            <p className="text-xs text-muted-foreground mb-0.5">Expenses</p>
            {summaryLoading
              ? <div className="h-5 w-20 bg-muted animate-pulse rounded" />
              : <p className="text-base font-semibold text-red-500">{formatAmount(summary?.total_expenses ?? 0, currency)}</p>
            }
          </div>
          <div className="rounded-lg border px-4 py-3">
            <p className="text-xs text-muted-foreground mb-0.5">Income</p>
            {summaryLoading
              ? <div className="h-5 w-20 bg-muted animate-pulse rounded" />
              : <p className="text-base font-semibold text-green-600">{formatAmount(summary?.total_income ?? 0, currency)}</p>
            }
          </div>
        </div>
      </div>

      {/* Transaction list */}
      {txnsLoading ? (
        <div className="flex items-center justify-center py-16 text-muted-foreground gap-2 text-sm">
          <Loader2 className="w-4 h-4 animate-spin" /> Loading transactions…
        </div>
      ) : isEmpty ? (
        <div className="flex flex-col items-center justify-center py-16 gap-3 text-center">
          <Wallet className="w-8 h-8 text-muted-foreground" />
          <p className="text-sm text-muted-foreground">No transactions yet for this account.</p>
          <Button size="sm" variant="outline" onClick={() => router.push("/budget/import")}>
            Import transactions
          </Button>
        </div>
      ) : (
        <div className="rounded-lg border overflow-hidden">
          {transactions.map((txn, i) => {
            const effectiveCatId = txn.id in categoryOverrides
              ? categoryOverrides[txn.id]
              : txn.category_id;
            const txnWithOverride = { ...txn, category_id: effectiveCatId };
            const isExpense = txn.amount < 0;
            const label = txn.merchant_name || txn.description;
            const sublabel = txn.merchant_name ? txn.description : null;

            return (
              <div
                key={txn.id}
                className={cn("flex items-center gap-3 px-4 py-3 text-sm", i > 0 && "border-t")}
              >
                <span className="text-muted-foreground text-xs w-12 shrink-0 tabular-nums">
                  {formatDate(txn.date)}
                </span>
                <div className="flex-1 min-w-0">
                  <p className="truncate font-medium">{label}</p>
                  {sublabel && <p className="text-xs text-muted-foreground truncate">{sublabel}</p>}
                </div>
                <CategoryPicker
                  txn={txnWithOverride}
                  categories={categories}
                  onAssigned={handleCategoryAssigned}
                />
                <span className={cn(
                  "shrink-0 tabular-nums font-medium w-24 text-right",
                  isExpense ? "text-foreground" : "text-green-600"
                )}>
                  {isExpense ? "−" : "+"}{formatAmount(txn.amount, txn.currency)}
                </span>
              </div>
            );
          })}
        </div>
      )}

      {/* Pagination */}
      {pageCount > 1 && (
        <div className="flex items-center justify-between mt-4 text-sm text-muted-foreground">
          <span>{offset + 1}–{Math.min(offset + PAGE_SIZE, total)} of {total}</span>
          <div className="flex items-center gap-1">
            <Button size="icon-sm" variant="ghost" disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - PAGE_SIZE))}>
              <ChevronLeft className="w-4 h-4" />
            </Button>
            <span className="px-2 tabular-nums">{currentPage} / {pageCount}</span>
            <Button size="icon-sm" variant="ghost" disabled={offset + PAGE_SIZE >= total} onClick={() => setOffset(offset + PAGE_SIZE)}>
              <ChevronRight className="w-4 h-4" />
            </Button>
          </div>
        </div>
      )}
    </div>
  );
}
