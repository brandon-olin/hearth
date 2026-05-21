"use client";

import { useState, useEffect, useCallback, useRef } from "react";
import { useParams, useRouter } from "next/navigation";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { apiBaseUrl } from "@/lib/api/client";
import { fetchWithAuth } from "@/lib/api/fetch-with-auth";
import { Button } from "@/components/ui/button";
import { ChevronLeft, ChevronRight, Loader2, Tag, CheckCircle2 } from "lucide-react";
import { cn } from "@/lib/utils";

// ── Types ─────────────────────────────────────────────────────────────────────

interface BudgetCategory {
  id: string;
  name: string;
  color: string | null;
  icon: string | null;
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
}

interface TransactionListResponse {
  items: BudgetTransaction[];
  total: number;
  limit: number;
  offset: number;
}

const PAGE_SIZE = 25;

// ── API helpers ───────────────────────────────────────────────────────────────

async function get<T>(path: string): Promise<T> {
  const res = await fetchWithAuth(`${apiBaseUrl}${path}`);
  if (!res.ok) throw new Error(`Failed: ${path}`);
  return res.json() as Promise<T>;
}

async function mutate<T>(method: string, path: string, body?: unknown): Promise<T> {
  const res = await fetchWithAuth(`${apiBaseUrl}${path}`, {
    method,
    headers: { "Content-Type": "application/json" },
    body: body !== undefined ? JSON.stringify(body) : undefined,
  });
  if (!res.ok) throw new Error(`Failed: ${method} ${path}`);
  return res.json() as Promise<T>;
}

// ── Formatting ────────────────────────────────────────────────────────────────

function fmt(amount: number, currency = "USD"): string {
  return new Intl.NumberFormat("en-US", {
    style: "currency", currency,
    minimumFractionDigits: 2, maximumFractionDigits: 2,
  }).format(Math.abs(amount));
}

function fmtDate(s: string) {
  return new Date(s + "T00:00:00").toLocaleDateString("en-US", { month: "short", day: "numeric" });
}

// ── Category picker ───────────────────────────────────────────────────────────

function CategoryPicker({
  txn, categories, onAssigned, onApplied,
}: {
  txn: BudgetTransaction;
  categories: BudgetCategory[];
  onAssigned: (txnId: string, catId: string | null) => void;
  /** Called after apply-to-similar completes so the page can refresh its list */
  onApplied?: () => void;
}) {
  const [open, setOpen] = useState(false);
  const [dropUp, setDropUp] = useState(false);
  const [saving, setSaving] = useState(false);
  const [search, setSearch] = useState("");
  const [applyPrompt, setApplyPrompt] = useState<{ catId: string; merchant: string } | null>(null);
  const [applying, setApplying] = useState(false);
  const [applyResult, setApplyResult] = useState<string | null>(null);
  const ref = useRef<HTMLDivElement>(null);
  const triggerRef = useRef<HTMLButtonElement>(null);
  const assigned = categories.find((c) => c.id === txn.category_id);
  const filteredCats = search.trim()
    ? categories.filter((c) => c.name.toLowerCase().includes(search.toLowerCase()))
    : categories;

  const handleToggle = () => {
    if (!open && triggerRef.current) {
      const rect = triggerRef.current.getBoundingClientRect();
      setDropUp(rect.bottom > window.innerHeight * 0.55);
    }
    setOpen((v) => !v);
  };

  useEffect(() => {
    if (!open) return;
    setSearch("");
    const h = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", h);
    return () => document.removeEventListener("mousedown", h);
  }, [open]);

  useEffect(() => {
    if (!applyResult) return;
    const t = setTimeout(() => setApplyResult(null), 3000);
    return () => clearTimeout(t);
  }, [applyResult]);

  const pick = async (catId: string | null) => {
    setSaving(true);
    try {
      await mutate("PATCH", `/budget/transactions/${txn.id}`, { category_id: catId });
      onAssigned(txn.id, catId);
      // Offer to propagate to similar transactions — fall back to description if no merchant name
      const matchText = txn.merchant_name || txn.description;
      if (catId && matchText) {
        setApplyPrompt({ catId, merchant: matchText });
      } else {
        setApplyPrompt(null);
      }
    } finally {
      setSaving(false);
      setOpen(false);
    }
  };

  const applyToSimilar = async () => {
    if (!applyPrompt) return;
    setApplying(true);
    try {
      const p = new URLSearchParams({ category_id: applyPrompt.catId });
      const res = await mutate<{ updated: number; keyword_added: boolean }>(
        "POST", `/budget/transactions/${txn.id}/apply-to-similar?${p}`
      );
      setApplyResult(
        res.updated > 0
          ? `Applied to ${res.updated} more transaction${res.updated === 1 ? "" : "s"}`
          : "No other matches found"
      );
      // Notify the parent page to refresh — transactions moved, analytics shifted
      onApplied?.();
    } finally {
      setApplying(false);
      setApplyPrompt(null);
    }
  };

  return (
    <div ref={ref} className="relative shrink-0">
      <button
        ref={triggerRef}
        onClick={handleToggle}
        className={cn(
          "flex items-center gap-1 rounded-full px-2 py-0.5 text-xs transition-colors",
          assigned ? "text-white" : "bg-muted text-muted-foreground hover:text-foreground"
        )}
        style={assigned?.color ? { backgroundColor: assigned.color } : undefined}
      >
        {saving
          ? <Loader2 className="w-3 h-3 animate-spin" />
          : assigned
            ? <>{assigned.icon && <span>{assigned.icon}</span>} {assigned.name}</>
            : <><Tag className="w-3 h-3" /> Categorize</>}
      </button>

      {/* "Apply to all similar?" prompt */}
      {(applyPrompt || applyResult) && (
        <div className={cn(
          "absolute right-0 z-50 whitespace-nowrap rounded-lg border bg-background shadow-lg px-3 py-2 text-xs flex items-center gap-2",
          dropUp ? "bottom-full mb-1" : "top-full mt-1"
        )}>
          {applyResult ? (
            <span className="text-muted-foreground">{applyResult}</span>
          ) : (
            <>
              <span className="text-muted-foreground truncate max-w-[140px]">
                Apply to all &ldquo;{applyPrompt!.merchant}&rdquo;?
              </span>
              <button
                onClick={() => void applyToSimilar()}
                disabled={applying}
                className="font-medium text-primary hover:underline disabled:opacity-50"
              >
                {applying ? <Loader2 className="w-3 h-3 animate-spin" /> : "Yes"}
              </button>
              <button
                onClick={() => setApplyPrompt(null)}
                className="text-muted-foreground hover:text-foreground"
              >
                ✕
              </button>
            </>
          )}
        </div>
      )}

      {open && (
        <div className={cn(
          "absolute right-0 z-50 w-52 rounded-lg border bg-background shadow-lg text-sm",
          dropUp ? "bottom-full mb-1" : "top-full mt-1"
        )}>
          {categories.length > 5 && (
            <div className="px-2 pt-2 pb-1 border-b">
              <input
                type="text"
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                placeholder="Search…"
                // eslint-disable-next-line jsx-a11y/no-autofocus
                autoFocus
                className="w-full h-7 px-2 text-xs rounded border bg-background focus:outline-none focus:ring-1 focus:ring-ring"
              />
            </div>
          )}
          <div className="max-h-52 overflow-y-auto py-1">
            {filteredCats.map((cat) => (
              <button
                key={cat.id}
                onClick={() => void pick(cat.id)}
                className={cn(
                  "w-full text-left flex items-center gap-2 px-3 py-1.5 hover:bg-muted transition-colors",
                  txn.category_id === cat.id && "bg-muted"
                )}
              >
                <span className="w-2.5 h-2.5 rounded-full shrink-0" style={{ backgroundColor: cat.color ?? "#94a3b8" }} />
                {cat.icon && <span className="text-xs">{cat.icon}</span>}
                {cat.name}
              </button>
            ))}
            {filteredCats.length === 0 && search && (
              <p className="px-3 py-2 text-muted-foreground text-xs">No matches</p>
            )}
            {categories.length === 0 && (
              <p className="px-3 py-2 text-muted-foreground text-xs">No categories yet</p>
            )}
          </div>
          {txn.category_id && (
            <>
              <div className="border-t" />
              <button
                onClick={() => void pick(null)}
                className="w-full text-left px-3 py-1.5 text-muted-foreground hover:bg-muted"
              >
                Remove category
              </button>
            </>
          )}
        </div>
      )}
    </div>
  );
}

// ── Page ──────────────────────────────────────────────────────────────────────

export default function CategoryDetailPage() {
  const params = useParams();
  const router = useRouter();
  const qc = useQueryClient();
  const id = params.id as string;
  const isUncategorized = id === "uncategorized";

  const [offset, setOffset] = useState(0);
  const [catOverrides, setCatOverrides] = useState<Record<string, string | null>>({});
  // For uncategorized view: track transactions assigned away so they fade out
  const [assignedAway, setAssignedAway] = useState<Set<string>>(new Set());

  // Fetch this category's info (skip for the special "uncategorized" slug)
  const { data: category, isLoading: catLoading } = useQuery<BudgetCategory>({
    queryKey: ["budget", "categories", id],
    queryFn: () => get(`/budget/categories/${id}`),
    enabled: !isUncategorized,
    retry: false,
  });

  // All categories for the picker
  const { data: allCategories = [] } = useQuery<BudgetCategory[]>({
    queryKey: ["budget", "categories"],
    queryFn: () => get("/budget/categories"),
  });

  // Transactions filtered by this category
  const { data: txnData, isLoading: txnsLoading } = useQuery<TransactionListResponse>({
    queryKey: ["budget", "category-txns", id, offset],
    queryFn: () => {
      const p = new URLSearchParams({ limit: String(PAGE_SIZE), offset: String(offset) });
      if (isUncategorized) {
        p.set("uncategorized", "true");
      } else {
        p.set("category_id", id);
      }
      return get(`/budget/transactions?${p}`);
    },
  });

  useEffect(() => { setCatOverrides({}); }, [txnData]);

  const handleAssigned = useCallback((txnId: string, catId: string | null) => {
    setCatOverrides((prev) => ({ ...prev, [txnId]: catId }));
    // In the uncategorized view, removing a transaction from this bucket should visually remove it
    if (isUncategorized && catId !== null) {
      setAssignedAway((prev) => new Set([...prev, txnId]));
    }
    // In a category view, if category is removed the txn should also disappear
    if (!isUncategorized && catId === null) {
      setAssignedAway((prev) => new Set([...prev, txnId]));
    }
    // Invalidate budget page charts so they reflect the new categorization
    void qc.invalidateQueries({ queryKey: ["budget", "analytics"] });
    void qc.invalidateQueries({ queryKey: ["budget", "summary"] });
  }, [isUncategorized, qc]);

  // Called after apply-to-similar: bulk of transactions were re-categorized,
  // so flush local overrides and re-fetch the list from the server.
  const handleApplied = useCallback(() => {
    setAssignedAway(new Set());
    setCatOverrides({});
    void qc.invalidateQueries({ queryKey: ["budget", "category-txns", id] });
    void qc.invalidateQueries({ queryKey: ["budget", "analytics"] });
    void qc.invalidateQueries({ queryKey: ["budget", "summary"] });
  }, [id, qc]);

  const transactions = (txnData?.items ?? []).filter((t) => !assignedAway.has(t.id));
  const txnTotal = txnData?.total ?? 0;
  const visibleTotal = txnTotal - assignedAway.size;
  const txnPages = Math.ceil(txnTotal / PAGE_SIZE);
  const txnPage = Math.floor(offset / PAGE_SIZE) + 1;

  const headerColor = isUncategorized ? "#94a3b8" : (category?.color ?? "#94a3b8");
  const headerName = isUncategorized ? "Uncategorized" : (category?.name ?? "…");
  const headerIcon = isUncategorized ? null : (category?.icon ?? null);

  // Loading state for category info (not for uncategorized)
  if (!isUncategorized && catLoading) {
    return (
      <div className="flex items-center justify-center min-h-[60vh]">
        <Loader2 className="w-5 h-5 animate-spin text-muted-foreground" />
      </div>
    );
  }

  return (
    <div className="max-w-2xl mx-auto pt-6 pb-40 px-4">

      {/* ── Header ── */}
      <div className="flex items-center gap-3 mb-6">
        <Button size="icon-sm" variant="ghost" onClick={() => router.push("/budget/categories")}>
          <ChevronLeft className="w-4 h-4" />
        </Button>
        <div
          className="w-8 h-8 rounded-full flex items-center justify-center shrink-0 text-sm"
          style={{ backgroundColor: headerColor }}
        >
          {headerIcon ?? ""}
        </div>
        <div>
          <h1 className="text-lg font-semibold">{headerName}</h1>
          {!txnsLoading && txnData && (
            <p className="text-xs text-muted-foreground">
              {visibleTotal} transaction{visibleTotal !== 1 ? "s" : ""}
              {isUncategorized && visibleTotal > 0 && " · click a row to assign a category"}
            </p>
          )}
        </div>
      </div>

      {/* ── Transactions ── */}
      {txnsLoading ? (
        <div className="flex items-center justify-center py-12 text-muted-foreground gap-2 text-sm">
          <Loader2 className="w-4 h-4 animate-spin" /> Loading…
        </div>
      ) : transactions.length === 0 ? (
        <div className="flex flex-col items-center gap-3 py-16 text-center text-muted-foreground">
          <CheckCircle2 className="w-8 h-8" />
          <p className="text-sm font-medium">
            {isUncategorized ? "All caught up — no uncategorized transactions." : "No transactions in this category."}
          </p>
        </div>
      ) : (
        <div className="rounded-lg border">
          {transactions.map((txn, i) => {
            const effectiveCatId = txn.id in catOverrides ? catOverrides[txn.id] : txn.category_id;
            const txnWithOverride = { ...txn, category_id: effectiveCatId };
            const isExpense = txn.amount < 0;
            const label = txn.merchant_name || txn.description;
            const sublabel = txn.merchant_name ? txn.description : null;
            return (
              <div
                key={txn.id}
                className={cn(
                  "flex items-center gap-3 px-4 py-3 text-sm",
                  i > 0 && "border-t",
                  i === 0 && "rounded-t-lg",
                  i === transactions.length - 1 && "rounded-b-lg",
                )}
              >
                <span className="text-muted-foreground text-xs w-12 shrink-0 tabular-nums">
                  {fmtDate(txn.date)}
                </span>
                <div className="flex-1 min-w-0">
                  <p className="truncate font-medium">{label}</p>
                  {sublabel && <p className="text-xs text-muted-foreground truncate">{sublabel}</p>}
                </div>
                <CategoryPicker
                  txn={txnWithOverride}
                  categories={allCategories}
                  onAssigned={handleAssigned}
                  onApplied={handleApplied}
                />
                <span className={cn(
                  "shrink-0 tabular-nums font-medium w-24 text-right",
                  isExpense ? "text-foreground" : "text-green-600"
                )}>
                  {isExpense ? "−" : "+"}{fmt(txn.amount, txn.currency)}
                </span>
              </div>
            );
          })}
        </div>
      )}

      {/* ── Pagination ── */}
      {txnPages > 1 && (
        <div className="flex items-center justify-between mt-3 text-sm text-muted-foreground">
          <span>{offset + 1}–{Math.min(offset + PAGE_SIZE, txnTotal)} of {txnTotal}</span>
          <div className="flex items-center gap-1">
            <Button
              size="icon-sm" variant="ghost"
              disabled={offset === 0}
              onClick={() => setOffset(Math.max(0, offset - PAGE_SIZE))}
            >
              <ChevronLeft className="w-4 h-4" />
            </Button>
            <span className="px-2 tabular-nums">{txnPage} / {txnPages}</span>
            <Button
              size="icon-sm" variant="ghost"
              disabled={offset + PAGE_SIZE >= txnTotal}
              onClick={() => setOffset(offset + PAGE_SIZE)}
            >
              <ChevronRight className="w-4 h-4" />
            </Button>
          </div>
        </div>
      )}
    </div>
  );
}
