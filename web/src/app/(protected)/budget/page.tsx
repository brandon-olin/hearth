"use client";

import { useState, useRef, useEffect, useCallback } from "react";
import { useRouter } from "next/navigation";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { apiBaseUrl } from "@/lib/api/client";
import { fetchWithAuth } from "@/lib/api/fetch-with-auth";
import { Button } from "@/components/ui/button";
import {
  Upload, Download, Loader2, ChevronLeft, ChevronRight,
  Wallet, Trash2, Tag, Sparkles, MoreHorizontal, Settings2, ChevronDown,
  PieChart as PieChartIcon, List, Wand2, ArrowLeftRight,
} from "lucide-react";
import { cn } from "@/lib/utils";

// ── Types ─────────────────────────────────────────────────────────────────────

interface BudgetAccount { id: string; name: string; account_type: string; currency: string; }
interface BudgetCategory { id: string; name: string; color: string | null; icon: string | null; keywords: string[] | null; }
interface BudgetTransaction {
  id: string; account_id: string; category_id: string | null;
  date: string; amount: number; currency: string;
  description: string; merchant_name: string | null;
  is_transfer: boolean;
}
interface TransactionListResponse { items: BudgetTransaction[]; total: number; limit: number; offset: number; }
interface CategoryEntry {
  category_id: string | null; category_name: string;
  category_color: string | null; category_icon: string | null;
  total_expenses: number; total_income: number; transaction_count: number;
}
interface AnalyticsResponse {
  year: number; month: number; date_from: string; date_to: string;
  total_expenses: number; total_income: number; transaction_count: number;
  by_category: CategoryEntry[];
}
interface BudgetSummary {
  total_income: number; total_expenses: number;
  transaction_count: number; date_from: string | null; date_to: string | null;
}

type SummaryPreset = "month" | "30d" | "60d" | "90d" | "custom";
const TXN_PAGE_SIZE = 25;
const MONTH_NAMES = ["January","February","March","April","May","June","July","August","September","October","November","December"];

// ── Date helpers ──────────────────────────────────────────────────────────────

function toISO(d: Date) { return d.toISOString().slice(0, 10); }

function presetRange(
  preset: SummaryPreset, year: number, month: number, customFrom: string, customTo: string
): { from: string; to: string } | null {
  if (preset === "month") return null;
  const today = new Date();
  const to = toISO(today);
  if (preset === "30d") { const d = new Date(today); d.setDate(d.getDate() - 30); return { from: toISO(d), to }; }
  if (preset === "60d") { const d = new Date(today); d.setDate(d.getDate() - 60); return { from: toISO(d), to }; }
  if (preset === "90d") { const d = new Date(today); d.setDate(d.getDate() - 90); return { from: toISO(d), to }; }
  return { from: customFrom, to: customTo };
}

// ── API helpers ───────────────────────────────────────────────────────────────

async function get<T>(path: string): Promise<T> {
  const res = await fetchWithAuth(`${apiBaseUrl}${path}`);
  if (!res.ok) throw new Error(`Failed: ${path}`);
  return res.json() as Promise<T>;
}
async function mutate<T>(method: string, path: string, body?: unknown): Promise<T> {
  const res = await fetchWithAuth(`${apiBaseUrl}${path}`, {
    method, headers: { "Content-Type": "application/json" },
    body: body !== undefined ? JSON.stringify(body) : undefined,
  });
  if (!res.ok) {
    const text = await res.text().catch(() => res.statusText);
    throw new Error(`${res.status} ${method} ${path}: ${text}`);
  }
  return res.json() as Promise<T>;
}

const fetchAccounts = () => get<BudgetAccount[]>("/budget/accounts");
const fetchCategories = () => get<BudgetCategory[]>("/budget/categories");
const fetchAnalytics = (year: number, month: number, accountId: string | null) => {
  const p = new URLSearchParams({ year: String(year), month: String(month) });
  if (accountId) p.set("account_id", accountId);
  return get<AnalyticsResponse>(`/budget/analytics?${p}`);
};
const fetchSummary = (accountId: string | null, from: string, to: string) => {
  const p = new URLSearchParams({ date_from: from, date_to: to });
  if (accountId) p.set("account_id", accountId);
  return get<BudgetSummary>(`/budget/summary?${p}`);
};
const fetchTransactions = (accountId: string | null, offset: number) => {
  const p = new URLSearchParams({ limit: String(TXN_PAGE_SIZE), offset: String(offset) });
  if (accountId) p.set("account_id", accountId);
  return get<TransactionListResponse>(`/budget/transactions?${p}`);
};

// ── Formatting ────────────────────────────────────────────────────────────────

function fmt(amount: number, currency = "USD", compact = false): string {
  return new Intl.NumberFormat("en-US", {
    style: "currency", currency,
    minimumFractionDigits: compact ? 0 : 2,
    maximumFractionDigits: compact ? 0 : 2,
  }).format(Math.abs(amount));
}
function fmtDate(s: string) {
  return new Date(s + "T00:00:00").toLocaleDateString("en-US", { month: "short", day: "numeric" });
}

// ── Account dropdown ──────────────────────────────────────────────────────────

function AccountDropdown({
  accounts, value, onChange,
}: { accounts: BudgetAccount[] | undefined; value: string | null; onChange: (v: string | null) => void }) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  const selected = accounts?.find((a) => a.id === value);

  useEffect(() => {
    if (!open) return;
    const h = (e: MouseEvent) => { if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false); };
    document.addEventListener("mousedown", h);
    return () => document.removeEventListener("mousedown", h);
  }, [open]);

  if (!accounts || accounts.length === 0) return null;
  if (accounts.length === 1) return (
    <span className="text-sm text-muted-foreground">{accounts[0].name}</span>
  );

  return (
    <div ref={ref} className="relative">
      <button
        onClick={() => setOpen((v) => !v)}
        className="flex items-center gap-1.5 h-8 pl-2.5 pr-2 rounded-md border bg-background text-sm hover:bg-muted transition-colors text-foreground"
      >
        <span className="max-w-[140px] truncate">{selected?.name ?? "All accounts"}</span>
        <ChevronDown className="w-3.5 h-3.5 text-muted-foreground shrink-0" />
      </button>
      {open && (
        <>
          <div className="fixed inset-0 z-10" onClick={() => setOpen(false)} />
          <div className="absolute left-0 top-full mt-1 z-20 bg-background border rounded-lg shadow-lg py-1 min-w-[160px]">
            <button onClick={() => { onChange(null); setOpen(false); }}
              className={cn("w-full text-left px-3 py-2 text-sm hover:bg-muted transition-colors", !value && "bg-muted font-medium")}>
              All accounts
            </button>
            {accounts.map((acc) => (
              <button key={acc.id} onClick={() => { onChange(acc.id); setOpen(false); }}
                className={cn("w-full text-left px-3 py-2 text-sm hover:bg-muted transition-colors", value === acc.id && "bg-muted font-medium")}>
                {acc.name}
              </button>
            ))}
          </div>
        </>
      )}
    </div>
  );
}

// ── SVG pie chart ─────────────────────────────────────────────────────────────

interface PieSlice extends CategoryEntry { startAngle: number; endAngle: number; midAngle: number; pct: number; }

function arcPath(cx: number, cy: number, R: number, ri: number, start: number, end: number): string {
  // Full circle workaround (SVG can't describe a complete arc in one <path>)
  if (end - start >= 2 * Math.PI - 0.0001) {
    return [
      `M ${cx} ${cy - R}`,
      `A ${R} ${R} 0 1 1 ${cx - 0.001} ${cy - R}`,
      `L ${cx - 0.001} ${cy - ri}`,
      `A ${ri} ${ri} 0 1 0 ${cx} ${cy - ri}`,
      "Z",
    ].join(" ");
  }
  const large = end - start > Math.PI ? 1 : 0;
  const x1 = cx + R * Math.cos(start),  y1 = cy + R * Math.sin(start);
  const x2 = cx + R * Math.cos(end),    y2 = cy + R * Math.sin(end);
  const ix1 = cx + ri * Math.cos(end),  iy1 = cy + ri * Math.sin(end);
  const ix2 = cx + ri * Math.cos(start), iy2 = cy + ri * Math.sin(start);
  return `M ${x1} ${y1} A ${R} ${R} 0 ${large} 1 ${x2} ${y2} L ${ix1} ${iy1} A ${ri} ${ri} 0 ${large} 0 ${ix2} ${iy2} Z`;
}

function PieChart({ entries, totalExpenses, currency, onCategoryClick }: {
  entries: CategoryEntry[]; totalExpenses: number; currency: string;
  onCategoryClick: (categoryId: string | null) => void;
}) {
  const [hovered, setHovered] = useState<PieSlice | null>(null);
  const [tip, setTip] = useState<{ x: number; y: number } | null>(null);
  const containerRef = useRef<HTMLDivElement>(null);

  const SIZE = 220, cx = SIZE / 2, cy = SIZE / 2, R = 90, ri = 52;

  const slices: PieSlice[] = [];
  let angle = -Math.PI / 2;
  for (const e of entries) {
    const sweep = totalExpenses > 0 ? (e.total_expenses / totalExpenses) * 2 * Math.PI : 0;
    slices.push({ ...e, startAngle: angle, endAngle: angle + sweep, midAngle: angle + sweep / 2, pct: totalExpenses > 0 ? (e.total_expenses / totalExpenses) * 100 : 0 });
    angle += sweep;
  }

  const handleMouseMove = (e: React.MouseEvent, slice: PieSlice) => {
    if (!containerRef.current) return;
    const rect = containerRef.current.getBoundingClientRect();
    setHovered(slice);
    setTip({ x: e.clientX - rect.left, y: e.clientY - rect.top });
  };

  const centerLabel = hovered?.category_name.slice(0, 14) ?? "Total spent";
  const centerAmount = hovered ? fmt(hovered.total_expenses, currency) : fmt(totalExpenses, currency, true);

  return (
    <div ref={containerRef} className="relative flex flex-col items-center">
      <svg
        viewBox={`0 0 ${SIZE} ${SIZE}`}
        className="w-full max-w-[220px]"
        onMouseLeave={() => { setHovered(null); setTip(null); }}
      >
        {slices.map((s) => (
          <path
            key={s.category_id ?? "__none__"}
            d={arcPath(cx, cy, R, ri, s.startAngle, s.endAngle)}
            fill={s.category_color ?? "#94a3b8"}
            className="cursor-pointer transition-opacity"
            style={{ opacity: hovered && hovered.category_id !== s.category_id ? 0.55 : 1 }}
            onMouseMove={(e) => handleMouseMove(e, s)}
            onClick={() => onCategoryClick(s.category_id)}
          />
        ))}
        {/* Center label */}
        <text x={cx} y={cy - 9} textAnchor="middle" fontSize="8.5" fill="currentColor" opacity="0.5"
          style={{ fontFamily: "inherit" }}>
          {centerLabel}
        </text>
        <text x={cx} y={cy + 9} textAnchor="middle" fontSize="14" fontWeight="600" fill="currentColor"
          style={{ fontFamily: "inherit" }}>
          {centerAmount}
        </text>
        {hovered && (
          <text x={cx} y={cy + 24} textAnchor="middle" fontSize="9" fill="currentColor" opacity="0.5"
            style={{ fontFamily: "inherit" }}>
            {hovered.pct.toFixed(1)}%
          </text>
        )}
      </svg>

      {/* Floating tooltip */}
      {hovered && tip && (
        <div
          className="absolute pointer-events-none z-50 rounded-lg border bg-background shadow-lg px-3 py-2 text-xs"
          style={{ left: tip.x + 14, top: Math.max(4, tip.y - 64) }}
        >
          <div className="flex items-center gap-1.5 mb-0.5">
            <span className="w-2 h-2 rounded-full shrink-0"
              style={{ backgroundColor: hovered.category_color ?? "#94a3b8" }} />
            <span className="font-medium">{hovered.category_name}</span>
          </div>
          <div className="text-muted-foreground">
            {fmt(hovered.total_expenses, currency)} · {hovered.pct.toFixed(1)}%
          </div>
          <div className="text-muted-foreground">
            {hovered.transaction_count} {hovered.transaction_count === 1 ? "transaction" : "transactions"}
          </div>
        </div>
      )}
    </div>
  );
}

// ── Condensed category bar ────────────────────────────────────────────────────

function CategoryBarCondensed({ entry, maxExpense, currency, onClick }: {
  entry: CategoryEntry; maxExpense: number; currency: string;
  onClick: () => void;
}) {
  const pct = maxExpense > 0 ? (entry.total_expenses / maxExpense) * 100 : 0;
  const color = entry.category_color ?? "#94a3b8";
  return (
    <button
      onClick={onClick}
      className="flex items-center gap-2.5 py-1.5 w-full text-left -mx-4 px-4 hover:bg-muted/50 transition-colors rounded"
    >
      <span className="w-2 h-2 rounded-full shrink-0" style={{ backgroundColor: color }} />
      <span className="text-xs w-28 truncate shrink-0 text-foreground">
        {entry.category_icon && <span className="mr-1">{entry.category_icon}</span>}
        {entry.category_name}
      </span>
      <div className="flex-1 h-1.5 rounded-full bg-muted overflow-hidden">
        <div className="h-full rounded-full" style={{ width: `${pct}%`, backgroundColor: color, opacity: 0.75 }} />
      </div>
      <span className="text-xs tabular-nums text-muted-foreground shrink-0 w-16 text-right">
        {fmt(entry.total_expenses, currency)}
      </span>
    </button>
  );
}

// ── Category picker ───────────────────────────────────────────────────────────

function CategoryPicker({ txn, categories, onAssigned, onTransferToggled }: {
  txn: BudgetTransaction; categories: BudgetCategory[];
  onAssigned: (txnId: string, catId: string | null) => void;
  onTransferToggled: (txnId: string, isTransfer: boolean) => void;
}) {
  const qc = useQueryClient();
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
      // Flip upward if the trigger sits in the lower 45% of the viewport
      const rect = triggerRef.current.getBoundingClientRect();
      setDropUp(rect.bottom > window.innerHeight * 0.55);
    }
    setOpen((v) => !v);
  };

  useEffect(() => {
    if (!open) return;
    setSearch("");
    const h = (e: MouseEvent) => { if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false); };
    document.addEventListener("mousedown", h);
    return () => document.removeEventListener("mousedown", h);
  }, [open]);

  // Dismiss the apply-prompt after showing a result
  useEffect(() => {
    if (!applyResult) return;
    const t = setTimeout(() => setApplyResult(null), 3000);
    return () => clearTimeout(t);
  }, [applyResult]);

  const toggleTransfer = async (isTransfer: boolean) => {
    setSaving(true);
    try {
      // When marking as transfer, also clear any category assignment
      const body: Record<string, unknown> = { is_transfer: isTransfer };
      if (isTransfer && txn.category_id) body.category_id = null;
      await mutate("PATCH", `/budget/transactions/${txn.id}`, body);
      if (isTransfer && txn.category_id) onAssigned(txn.id, null);
      onTransferToggled(txn.id, isTransfer);
    } finally { setSaving(false); setOpen(false); }
  };

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
    } finally { setSaving(false); setOpen(false); }
  };

  const applyToSimilar = async () => {
    if (!applyPrompt) return;
    setApplying(true);
    try {
      const p = new URLSearchParams({ transaction_id: txn.id, category_id: applyPrompt.catId });
      const res = await mutate<{ updated: number; keyword_added: boolean }>(
        "POST", `/budget/apply-to-similar?${p}`
      );
      setApplyResult(
        res.updated > 0
          ? `Applied to ${res.updated} more transaction${res.updated === 1 ? "" : "s"}`
          : "No other matches found"
      );
      // Refresh everything — categories changed, analytics shifted, transaction list updated
      void qc.invalidateQueries({ queryKey: ["budget", "analytics"] });
      void qc.invalidateQueries({ queryKey: ["budget", "summary"] });
      void qc.invalidateQueries({ queryKey: ["budget", "transactions"] });
    } finally {
      setApplying(false);
      setApplyPrompt(null);
    }
  };

  // Transfer transactions show a separate badge — no category picker
  if (txn.is_transfer) {
    return (
      <div ref={ref} className="relative shrink-0">
        <button
          ref={triggerRef}
          onClick={handleToggle}
          className="flex items-center gap-1 rounded-full px-2 py-0.5 text-xs bg-sky-100 text-sky-700 dark:bg-sky-900/40 dark:text-sky-400 transition-colors hover:bg-sky-200 dark:hover:bg-sky-900/60"
        >
          {saving ? <Loader2 className="w-3 h-3 animate-spin" /> : <ArrowLeftRight className="w-3 h-3" />}
          Transfer
        </button>
        {open && (
          <div className={cn(
            "absolute right-0 z-50 w-44 rounded-lg border bg-background shadow-lg text-sm py-1",
            dropUp ? "bottom-full mb-1" : "top-full mt-1"
          )}>
            <button
              onClick={() => void toggleTransfer(false)}
              className="w-full text-left px-3 py-1.5 hover:bg-muted transition-colors text-muted-foreground"
            >
              Unmark as transfer
            </button>
          </div>
        )}
      </div>
    );
  }

  return (
    <div ref={ref} className="relative shrink-0">
      <button
        ref={triggerRef}
        onClick={handleToggle}
        className={cn("flex items-center gap-1 rounded-full px-2 py-0.5 text-xs transition-colors",
          assigned ? "text-white" : "bg-muted text-muted-foreground hover:text-foreground")}
        style={assigned?.color ? { backgroundColor: assigned.color } : undefined}>
        {saving ? <Loader2 className="w-3 h-3 animate-spin" />
          : assigned ? <>{assigned.icon && <span>{assigned.icon}</span>} {assigned.name}</>
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
              <button key={cat.id} onClick={() => void pick(cat.id)}
                className={cn("w-full text-left flex items-center gap-2 px-3 py-1.5 hover:bg-muted transition-colors", txn.category_id === cat.id && "bg-muted")}>
                <span className="w-2.5 h-2.5 rounded-full shrink-0" style={{ backgroundColor: cat.color ?? "#94a3b8" }} />
                {cat.icon && <span className="text-xs">{cat.icon}</span>}
                {cat.name}
              </button>
            ))}
            {filteredCats.length === 0 && search && (
              <p className="px-3 py-2 text-muted-foreground text-xs">No matches</p>
            )}
            {categories.length === 0 && <p className="px-3 py-2 text-muted-foreground text-xs">No categories yet</p>}
          </div>
          {txn.category_id && (
            <><div className="border-t" />
              <button onClick={() => void pick(null)} className="w-full text-left px-3 py-1.5 text-muted-foreground hover:bg-muted">Remove category</button>
            </>
          )}
          <div className="border-t" />
          <button
            onClick={() => void toggleTransfer(true)}
            className="w-full text-left flex items-center gap-2 px-3 py-1.5 text-muted-foreground hover:bg-muted transition-colors"
          >
            <ArrowLeftRight className="w-3.5 h-3.5 shrink-0" />
            Mark as transfer
          </button>
        </div>
      )}
    </div>
  );
}

// ── Actions menu ──────────────────────────────────────────────────────────────

function ActionsMenu({
  onImport, onExport, onCategories, onAutoCategorize, onDeleteAll, exporting, autoCategorizing,
}: {
  onImport: () => void; onExport: () => void; onCategories: () => void;
  onAutoCategorize: () => void; onDeleteAll: () => void;
  exporting: boolean; autoCategorizing: boolean;
}) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const h = (e: MouseEvent) => { if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false); };
    document.addEventListener("mousedown", h);
    return () => document.removeEventListener("mousedown", h);
  }, [open]);

  const item = (label: string, icon: React.ReactNode, action: () => void, danger = false, disabled = false) => (
    <button type="button" onClick={() => { if (!disabled) { action(); setOpen(false); } }} disabled={disabled}
      className={cn("flex items-center gap-2.5 w-full px-3 py-2 text-sm text-left transition-colors",
        danger ? "text-destructive hover:bg-destructive/10" : "hover:bg-muted",
        disabled && "opacity-40 cursor-not-allowed")}>
      {icon}{label}
    </button>
  );

  return (
    <div ref={ref} className="relative">
      <Button variant="ghost" size="sm" className="h-8 w-8 p-0" onClick={() => setOpen((v) => !v)}>
        <MoreHorizontal className="w-4 h-4" />
      </Button>
      {open && (
        <>
          <div className="fixed inset-0 z-10" onClick={() => setOpen(false)} />
          <div className="absolute right-0 top-full mt-1 z-20 bg-background border rounded-lg shadow-lg py-1 min-w-[200px]">
            {item("Import transactions", <Upload className="w-3.5 h-3.5 shrink-0 text-muted-foreground" />, onImport)}
            {item(exporting ? "Exporting…" : "Export CSV",
              exporting ? <Loader2 className="w-3.5 h-3.5 shrink-0 animate-spin text-muted-foreground" /> : <Download className="w-3.5 h-3.5 shrink-0 text-muted-foreground" />,
              onExport, false, exporting)}
            {item("Manage categories", <Settings2 className="w-3.5 h-3.5 shrink-0 text-muted-foreground" />, onCategories)}
            {item(autoCategorizing ? "Categorizing…" : "Auto-categorize",
              autoCategorizing ? <Loader2 className="w-3.5 h-3.5 shrink-0 animate-spin text-muted-foreground" /> : <Wand2 className="w-3.5 h-3.5 shrink-0 text-muted-foreground" />,
              onAutoCategorize, false, autoCategorizing)}
            <div className="border-t my-1" />
            {item("Delete all transactions", <Trash2 className="w-3.5 h-3.5 shrink-0" />, onDeleteAll, true)}
          </div>
        </>
      )}
    </div>
  );
}

// ── Main page ─────────────────────────────────────────────────────────────────

export default function BudgetPage() {
  const router = useRouter();
  const qc = useQueryClient();

  // Account filter
  const [selectedAccount, setSelectedAccount] = useState<string | null>(null);

  // Analytics month picker
  const today = new Date();
  const [anaYear, setAnaYear] = useState(today.getFullYear());
  const [anaMonth, setAnaMonth] = useState(today.getMonth() + 1);

  // Summary date preset
  const [preset, setPreset] = useState<SummaryPreset>("month");
  const [customFrom, setCustomFrom] = useState(() => {
    const d = new Date(today); d.setDate(1); return toISO(d);
  });
  const [customTo, setCustomTo] = useState(() => toISO(today));

  // Transactions
  const [txnOffset, setTxnOffset] = useState(0);
  const [catOverrides, setCatOverrides] = useState<Record<string, string | null>>({});
  const [transferOverrides, setTransferOverrides] = useState<Record<string, boolean>>({});

  // Analytics view toggle ("pie" | "list")
  const [chartView, setChartView] = useState<"pie" | "list">("pie");

  // Actions state
  const [exporting, setExporting] = useState(false);
  const [autoCategorizing, setAutoCategorizing] = useState(false);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [deleting, setDeleting] = useState(false);

  // ── Queries ──────────────────────────────────────────────────────────────────

  const { data: accounts, isLoading: accountsLoading } = useQuery({ queryKey: ["budget", "accounts"], queryFn: fetchAccounts });
  const { data: categories = [] } = useQuery({ queryKey: ["budget", "categories"], queryFn: fetchCategories });

  const { data: analytics, isLoading: anaLoading } = useQuery({
    queryKey: ["budget", "analytics", anaYear, anaMonth, selectedAccount],
    queryFn: () => fetchAnalytics(anaYear, anaMonth, selectedAccount),
    enabled: !!accounts && accounts.length > 0,
  });

  // Compute summary date range (null = use analytics data)
  const summaryRange = presetRange(preset, anaYear, anaMonth, customFrom, customTo);

  // For "month" preset: compute dates from the selected analytics month
  const monthRange = (() => {
    const isCurrentMonth = anaYear === today.getFullYear() && anaMonth === today.getMonth() + 1;
    const from = toISO(new Date(anaYear, anaMonth - 1, 1));
    const to = isCurrentMonth ? toISO(today) : toISO(new Date(anaYear, anaMonth, 0));
    return { from, to };
  })();

  const effectiveRange = summaryRange ?? monthRange;

  const { data: summary, isLoading: summaryLoading } = useQuery({
    queryKey: ["budget", "summary", selectedAccount, effectiveRange.from, effectiveRange.to, preset],
    queryFn: () => fetchSummary(selectedAccount, effectiveRange.from, effectiveRange.to),
    // When in "month" mode, we can derive from analytics — but fetch anyway for accuracy
    enabled: !!accounts && accounts.length > 0,
  });

  const { data: txnData, isLoading: txnsLoading } = useQuery({
    queryKey: ["budget", "transactions", selectedAccount, txnOffset],
    queryFn: () => fetchTransactions(selectedAccount, txnOffset),
    enabled: !!accounts && accounts.length > 0,
  });

  useEffect(() => { setCatOverrides({}); setTransferOverrides({}); }, [txnData]);

  // ── Month navigation ──────────────────────────────────────────────────────────

  const isCurrentMonth = anaYear === today.getFullYear() && anaMonth === today.getMonth() + 1;

  const prevMonth = () => {
    if (anaMonth === 1) { setAnaMonth(12); setAnaYear((y) => y - 1); }
    else setAnaMonth((m) => m - 1);
    // Switch to "month" preset when navigating
    if (preset !== "month") setPreset("month");
  };

  const nextMonth = () => {
    if (isCurrentMonth) return;
    if (anaMonth === 12) { setAnaMonth(1); setAnaYear((y) => y + 1); }
    else setAnaMonth((m) => m + 1);
    if (preset !== "month") setPreset("month");
  };

  // ── Actions ───────────────────────────────────────────────────────────────────

  const handleExport = async () => {
    setExporting(true);
    try {
      const p = new URLSearchParams();
      if (selectedAccount) p.set("account_id", selectedAccount);
      const res = await fetchWithAuth(`${apiBaseUrl}/budget/transactions/export?${p}`);
      if (!res.ok) throw new Error("Export failed");
      const blob = await res.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      const match = res.headers.get("Content-Disposition")?.match(/filename="([^"]+)"/);
      a.download = match?.[1] ?? "hearth-budget.csv";
      document.body.appendChild(a); a.click(); document.body.removeChild(a);
      URL.revokeObjectURL(url);
    } finally { setExporting(false); }
  };

  const handleAutoCategorize = async () => {
    setAutoCategorizing(true);
    try {
      const p = new URLSearchParams();
      if (selectedAccount) p.set("account_id", selectedAccount);
      await mutate("POST", `/budget/auto-categorize${p.toString() ? `?${p}` : ""}`);
      await qc.invalidateQueries({ queryKey: ["budget"] });
    } finally { setAutoCategorizing(false); }
  };

  const handleDeleteAll = async () => {
    setDeleting(true);
    try {
      const p = selectedAccount ? `?account_id=${selectedAccount}` : "";
      await mutate("DELETE", `/budget/transactions${p}`);
      await qc.invalidateQueries({ queryKey: ["budget"] });
      setTxnOffset(0);
    } finally { setDeleting(false); setConfirmDelete(false); }
  };

  const handleCategoryAssigned = useCallback((txnId: string, catId: string | null) => {
    setCatOverrides((prev) => ({ ...prev, [txnId]: catId }));
    void qc.invalidateQueries({ queryKey: ["budget", "analytics"] });
    void qc.invalidateQueries({ queryKey: ["budget", "summary"] });
  }, [qc]);

  const handleTransferToggled = useCallback((txnId: string, isTransfer: boolean) => {
    setTransferOverrides((prev) => ({ ...prev, [txnId]: isTransfer }));
    // Transfer flag changes what's included in aggregates, so refresh both
    void qc.invalidateQueries({ queryKey: ["budget", "analytics"] });
    void qc.invalidateQueries({ queryKey: ["budget", "summary"] });
  }, [qc]);

  const handleCategoryClick = useCallback((categoryId: string | null) => {
    router.push(categoryId ? `/budget/categories/${categoryId}` : "/budget/categories/uncategorized");
  }, [router]);

  // ── Derived ───────────────────────────────────────────────────────────────────

  const transactions = txnData?.items ?? [];
  const txnTotal = txnData?.total ?? 0;
  const txnPages = Math.ceil(txnTotal / TXN_PAGE_SIZE);
  const txnPage = Math.floor(txnOffset / TXN_PAGE_SIZE) + 1;
  const currency = transactions[0]?.currency ?? "USD";

  const expenseEntries = (analytics?.by_category ?? [])
    .filter((e) => e.total_expenses > 0)
    .sort((a, b) => b.total_expenses - a.total_expenses);
  const maxExpense = expenseEntries.length > 0 ? Math.max(...expenseEntries.map((e) => e.total_expenses)) : 0;
  const totalExpenses = analytics?.total_expenses ?? 0;

  const hasAccounts = accounts && accounts.length > 0;

  const summaryExpenses = preset === "month" ? (analytics?.total_expenses ?? 0) : (summary?.total_expenses ?? 0);
  const summaryIncome = preset === "month" ? (analytics?.total_income ?? 0) : (summary?.total_income ?? 0);
  const summaryNet = summaryIncome - summaryExpenses;
  const summaryLoaded = preset === "month" ? !anaLoading : !summaryLoading;

  // ── Empty state ───────────────────────────────────────────────────────────────

  if (!accountsLoading && !hasAccounts) {
    return (
      <div className="flex flex-col items-center justify-center min-h-[60vh] gap-4 text-center px-4">
        <div className="rounded-full bg-muted p-4"><Upload className="w-8 h-8 text-muted-foreground" /></div>
        <div>
          <h1 className="text-xl font-semibold mb-1">Budget</h1>
          <p className="text-muted-foreground text-sm max-w-sm">Import your bank statements to get started.</p>
        </div>
        <Button onClick={() => router.push("/budget/import")}>Import transactions</Button>
      </div>
    );
  }

  // ── Layout ────────────────────────────────────────────────────────────────────

  return (
    <div className="max-w-2xl mx-auto pt-6 pb-48 px-4 space-y-5">

      {/* ── Header row ── */}
      <div className="flex items-center justify-between">
        <h1 className="text-lg font-semibold">Budget</h1>
        <ActionsMenu
          onImport={() => router.push("/budget/import")}
          onExport={() => void handleExport()}
          onCategories={() => router.push("/budget/categories")}
          onAutoCategorize={() => void handleAutoCategorize()}
          onDeleteAll={() => setConfirmDelete(true)}
          exporting={exporting}
          autoCategorizing={autoCategorizing}
        />
      </div>

      {/* ── Account + month row ── */}
      <div className="flex items-center justify-between gap-3">
        <AccountDropdown accounts={accounts} value={selectedAccount} onChange={(v) => { setSelectedAccount(v); setTxnOffset(0); }} />
        <div className="flex items-center gap-2">
          <button onClick={prevMonth} className="p-1 rounded-full bg-muted text-muted-foreground hover:text-foreground transition-colors">
            <ChevronLeft className="w-4 h-4" />
          </button>
          <span className="text-sm font-medium min-w-[9rem] text-center">
            {MONTH_NAMES[anaMonth - 1]} {anaYear}
          </span>
          <button onClick={nextMonth} disabled={isCurrentMonth}
            className={cn("p-1 rounded-full bg-muted transition-colors", isCurrentMonth ? "text-muted-foreground/30" : "text-muted-foreground hover:text-foreground")}>
            <ChevronRight className="w-4 h-4" />
          </button>
        </div>
      </div>

      {/* ── Summary presets + cards ── */}
      <section>
        {/* Preset pills */}
        <div className="flex items-center gap-1.5 mb-3 flex-wrap">
          {(["month", "30d", "60d", "90d", "custom"] as SummaryPreset[]).map((p) => (
            <button key={p} onClick={() => setPreset(p)}
              className={cn("rounded-full px-3 py-0.5 text-xs font-medium transition-colors",
                preset === p ? "bg-primary text-primary-foreground" : "bg-muted text-muted-foreground hover:text-foreground")}>
              {p === "month" ? (isCurrentMonth ? "Month to date" : MONTH_NAMES[anaMonth - 1])
                : p === "custom" ? "Custom" : p}
            </button>
          ))}
          {preset === "custom" && (
            <div className="flex items-center gap-1.5 ml-1">
              <input type="date" value={customFrom} onChange={(e) => setCustomFrom(e.target.value)}
                className="h-6 rounded border bg-background px-2 text-xs text-foreground" />
              <span className="text-xs text-muted-foreground">to</span>
              <input type="date" value={customTo} onChange={(e) => setCustomTo(e.target.value)}
                className="h-6 rounded border bg-background px-2 text-xs text-foreground" />
            </div>
          )}
        </div>

        {/* Summary cards */}
        <div className="grid grid-cols-3 gap-3">
          {(["Spent", "Income", "Net"] as const).map((label) => {
            const amount = label === "Spent" ? summaryExpenses : label === "Income" ? summaryIncome : summaryNet;
            const color = label === "Spent" ? "text-red-500" : label === "Income" ? "text-green-600"
              : summaryNet >= 0 ? "text-green-600" : "text-red-500";
            const sign = label === "Net" ? (summaryNet >= 0 ? "+" : "−") : "";
            return (
              <div key={label} className="rounded-lg border px-4 py-3">
                <p className="text-xs text-muted-foreground mb-1">{label}</p>
                {!summaryLoaded
                  ? <div className="h-5 w-20 bg-muted animate-pulse rounded" />
                  : <p className={cn("text-lg font-semibold", color)}>{sign}{fmt(Math.abs(amount), currency, true)}</p>}
              </div>
            );
          })}
        </div>
      </section>

      {/* ── Spending breakdown ── */}
      <section>
        {/* Header row: title + view toggle */}
        <div className="flex items-center justify-between mb-3">
          <p className="text-xs font-semibold text-muted-foreground uppercase tracking-wider">
            Spending breakdown · {MONTH_NAMES[anaMonth - 1]} {anaYear}
          </p>
          {!anaLoading && expenseEntries.length > 0 && (
            <div className="flex items-center gap-0.5 rounded-md bg-muted p-0.5">
              <button
                onClick={() => setChartView("pie")}
                className={cn(
                  "flex items-center justify-center w-6 h-6 rounded transition-colors",
                  chartView === "pie"
                    ? "bg-background shadow-sm text-foreground"
                    : "text-muted-foreground hover:text-foreground"
                )}
                title="Pie chart"
              >
                <PieChartIcon className="w-3.5 h-3.5" />
              </button>
              <button
                onClick={() => setChartView("list")}
                className={cn(
                  "flex items-center justify-center w-6 h-6 rounded transition-colors",
                  chartView === "list"
                    ? "bg-background shadow-sm text-foreground"
                    : "text-muted-foreground hover:text-foreground"
                )}
                title="List view"
              >
                <List className="w-3.5 h-3.5" />
              </button>
            </div>
          )}
        </div>

        {anaLoading ? (
          <div className="flex items-center justify-center py-12 text-muted-foreground gap-2 text-sm">
            <Loader2 className="w-4 h-4 animate-spin" /> Loading…
          </div>
        ) : expenseEntries.length === 0 ? (
          <p className="text-sm text-muted-foreground text-center py-8">
            No expenses for {MONTH_NAMES[anaMonth - 1]}.
          </p>
        ) : chartView === "pie" ? (
          /* ── Pie chart view ── */
          <div className="rounded-lg border p-4">
            <PieChart
              entries={expenseEntries}
              totalExpenses={totalExpenses}
              currency={currency}
              onCategoryClick={handleCategoryClick}
            />
          </div>
        ) : (
          /* ── List view ── */
          <div className="rounded-lg border px-4 py-2 divide-y">
            {expenseEntries.map((entry) => (
              <CategoryBarCondensed
                key={entry.category_id ?? "__none__"}
                entry={entry}
                maxExpense={maxExpense}
                currency={currency}
                onClick={() => handleCategoryClick(entry.category_id)}
              />
            ))}
          </div>
        )}
      </section>

      {/* ── Delete confirmation modal ── */}
      {confirmDelete && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 backdrop-blur-[2px]">
          <div className="bg-background rounded-xl border shadow-xl px-6 py-5 max-w-sm w-full mx-4">
            <h2 className="text-base font-semibold mb-1.5">Delete all transactions?</h2>
            <p className="text-sm text-muted-foreground mb-5">
              This will permanently delete all {selectedAccount ? "transactions for this account" : "budget transactions"}. This cannot be undone.
            </p>
            <div className="flex justify-end gap-2">
              <Button size="sm" variant="ghost" onClick={() => setConfirmDelete(false)} disabled={deleting}>
                Cancel
              </Button>
              <Button size="sm" variant="destructive" onClick={() => void handleDeleteAll()} disabled={deleting}>
                {deleting && <Loader2 className="w-3 h-3 animate-spin mr-1" />}
                Delete all
              </Button>
            </div>
          </div>
        </div>
      )}

      {/* ── Recent transactions ── */}
      <section>
        <div className="flex items-center justify-between mb-3">
          <p className="text-xs font-semibold text-muted-foreground uppercase tracking-wider">Recent transactions</p>
          {txnTotal > 0 && <span className="text-xs text-muted-foreground">{txnTotal} total</span>}
        </div>

        {txnsLoading ? (
          <div className="flex items-center justify-center py-10 text-muted-foreground gap-2 text-sm">
            <Loader2 className="w-4 h-4 animate-spin" /> Loading…
          </div>
        ) : transactions.length === 0 ? (
          <div className="flex flex-col items-center justify-center py-10 gap-3 text-center">
            <Wallet className="w-7 h-7 text-muted-foreground" />
            <p className="text-sm text-muted-foreground">No transactions yet.</p>
            <Button size="sm" variant="outline" onClick={() => router.push("/budget/import")}>Import transactions</Button>
          </div>
        ) : (
          <div className="rounded-lg border">
            {transactions.map((txn, i) => {
              const effectiveCatId = txn.id in catOverrides ? catOverrides[txn.id] : txn.category_id;
              const effectiveIsTransfer = txn.id in transferOverrides ? transferOverrides[txn.id] : txn.is_transfer;
              const txnWithOverride = { ...txn, category_id: effectiveCatId, is_transfer: effectiveIsTransfer };
              const isExpense = txn.amount < 0;
              const label = txn.merchant_name || txn.description;
              const sublabel = txn.merchant_name ? txn.description : null;
              return (
                <div key={txn.id} className={cn(
                  "flex items-center gap-3 px-4 py-3 text-sm",
                  i > 0 && "border-t",
                  i === 0 && "rounded-t-lg",
                  i === transactions.length - 1 && "rounded-b-lg",
                  effectiveIsTransfer && "opacity-60",
                )}>
                  <span className="text-muted-foreground text-xs w-12 shrink-0 tabular-nums">{fmtDate(txn.date)}</span>
                  <div className="flex-1 min-w-0">
                    <p className="truncate font-medium">{label}</p>
                    {sublabel && <p className="text-xs text-muted-foreground truncate">{sublabel}</p>}
                  </div>
                  <CategoryPicker
                    txn={txnWithOverride}
                    categories={categories}
                    onAssigned={handleCategoryAssigned}
                    onTransferToggled={handleTransferToggled}
                  />
                  <span className={cn("shrink-0 tabular-nums font-medium w-24 text-right", isExpense ? "text-foreground" : "text-green-600")}>
                    {isExpense ? "−" : "+"}{fmt(txn.amount, txn.currency)}
                  </span>
                </div>
              );
            })}
          </div>
        )}

        {txnPages > 1 && (
          <div className="flex items-center justify-between mt-3 text-sm text-muted-foreground">
            <span>{txnOffset + 1}–{Math.min(txnOffset + TXN_PAGE_SIZE, txnTotal)} of {txnTotal}</span>
            <div className="flex items-center gap-1">
              <Button size="icon-sm" variant="ghost" disabled={txnOffset === 0} onClick={() => setTxnOffset(Math.max(0, txnOffset - TXN_PAGE_SIZE))}>
                <ChevronLeft className="w-4 h-4" />
              </Button>
              <span className="px-2 tabular-nums">{txnPage} / {txnPages}</span>
              <Button size="icon-sm" variant="ghost" disabled={txnOffset + TXN_PAGE_SIZE >= txnTotal} onClick={() => setTxnOffset(txnOffset + TXN_PAGE_SIZE)}>
                <ChevronRight className="w-4 h-4" />
              </Button>
            </div>
          </div>
        )}
      </section>
    </div>
  );
}
