"use client";

import { useState, useRef, useEffect, useCallback } from "react";
import { useRouter } from "next/navigation";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { apiBaseUrl } from "@/lib/api/client";
import { fetchWithAuth } from "@/lib/api/fetch-with-auth";
import { Button } from "@/components/ui/button";
import {
  Upload,
  Download,
  Loader2,
  ChevronLeft,
  ChevronRight,
  Wallet,
  Trash2,
  Tag,
  Sparkles,
  MoreHorizontal,
  Settings2,
  ChevronDown,
  PieChart as PieChartIcon,
  Wand2,
  ArrowLeftRight,
  Repeat,
  Search,
  X,
  TrendingUp,
  SlidersHorizontal,
  Check,
  CalendarClock,
} from "lucide-react";
import { cn } from "@/lib/utils";

// ── Types ─────────────────────────────────────────────────────────────────────

interface BudgetAccount {
  id: string;
  name: string;
  account_type: string;
  currency: string;
  // budget-017: manually-maintained balance
  current_balance: number | null;
  balance_updated_at: string | null;
  // Teller bank sync — null when not linked
  teller_enrollment_id: string | null;
  teller_account_id: string | null;
  teller_institution_name: string | null;
  teller_last_synced_at: string | null;
}

interface TellerConfig {
  enabled: boolean;
  app_id: string | null;
  environment: string;
}

// Minimal type shim for the Teller Connect widget loaded via CDN script.
declare global {
  interface Window {
    TellerConnect?: {
      setup(opts: {
        applicationId: string;
        environment?: string;
        products?: string[];
        onSuccess: (enrollment: {
          accessToken: string;
          enrollment: { id: string; institution: { name: string } };
        }) => void;
        onExit?: () => void;
        onFailure?: (f: { type: string; message?: string }) => void;
      }): { open: () => void };
    };
  }
}
interface BudgetCategory {
  id: string;
  name: string;
  color: string | null;
  icon: string | null;
  keywords: string[] | null;
}
interface RecurringRule {
  frequency: "weekly" | "monthly" | "bi_weekly" | "semi_monthly";
  interval: number;
  end_date: string | null;
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
  notes: string | null;
  is_transfer: boolean;
  recurring: RecurringRule | null;
  recurring_template_id: string | null;
}
interface TransactionListResponse {
  items: BudgetTransaction[];
  total: number;
  limit: number;
  offset: number;
}
interface CategoryEntry {
  category_id: string | null;
  category_name: string;
  category_color: string | null;
  category_icon: string | null;
  total_expenses: number;
  total_income: number;
  transaction_count: number;
  budgeted: number | null;
  remaining: number | null;
  is_over_budget: boolean;
  rollover_amount: number; // carry-forward from previous month (0 if rollover disabled)
}
interface AnalyticsResponse {
  year: number;
  month: number;
  date_from: string;
  date_to: string;
  total_expenses: number;
  total_income: number;
  transaction_count: number;
  total_budgeted: number;
  total_targets: number; // sum of ALL category targets; drives Ready to assign
  by_category: CategoryEntry[];
}
interface BudgetSummary {
  total_income: number;
  total_expenses: number;
  transaction_count: number;
  date_from: string | null;
  date_to: string | null;
}

interface BudgetProfile {
  id: string;
  name: string;
  budgeting_style: "zero_based" | "profit_tracking";
  currency: string;
  sort_order: number;
}

interface ProfitAnalyticsResponse {
  year: number;
  month: number;
  date_from: string;
  date_to: string;
  total_revenue: number;
  total_expenses: number;
  net_profit: number;
  transaction_count: number;
  by_category: CategoryEntry[];
  mrr_actual: number;
  arr_projected: number;
  mrr_prev_month: number;
  mrr_growth_pct: number | null;
}

interface GroupedCategory {
  id: string | null; // null = implicit"Other"bucket
  name: string;
  sort_order: number;
  categories: Array<{ id: string }>;
}
interface TrendMonth {
  year: number;
  month: number;
  total_income: number;
  total_expenses: number;
  total_budgeted: number;
  net: number;
}

type SummaryPreset = "mtd" | "last_month" | "ytd" | "custom";
const TXN_PAGE_SIZE = 25;
const MONTH_NAMES = [
  "January",
  "February",
  "March",
  "April",
  "May",
  "June",
  "July",
  "August",
  "September",
  "October",
  "November",
  "December",
];
const PROFILE_STORAGE_KEY = "hearth-budget-profile-id";
const PRESET_STORAGE_KEY = "hearth-budget-preset";

// ── Date helpers ──────────────────────────────────────────────────────────────

function toISO(d: Date) {
  return d.toISOString().slice(0, 10);
}

function presetRange(
  preset: SummaryPreset,
  customFrom: string,
  customTo: string,
): { from: string; to: string } {
  const today = new Date();
  if (preset === "mtd") {
    return {
      from: toISO(new Date(today.getFullYear(), today.getMonth(), 1)),
      to: toISO(today),
    };
  }
  if (preset === "last_month") {
    const first = new Date(today.getFullYear(), today.getMonth() - 1, 1);
    const last = new Date(today.getFullYear(), today.getMonth(), 0);
    return { from: toISO(first), to: toISO(last) };
  }
  if (preset === "ytd") {
    return { from: `${today.getFullYear()}-01-01`, to: toISO(today) };
  }
  // custom
  return { from: customFrom, to: customTo };
}

// ── API helpers ───────────────────────────────────────────────────────────────

async function get<T>(path: string): Promise<T> {
  const res = await fetchWithAuth(`${apiBaseUrl}${path}`);
  if (!res.ok) throw new Error(`Failed: ${path}`);
  return res.json() as Promise<T>;
}
async function mutate<T>(
  method: string,
  path: string,
  body?: unknown,
): Promise<T> {
  const res = await fetchWithAuth(`${apiBaseUrl}${path}`, {
    method,
    headers: { "Content-Type": "application/json" },
    body: body !== undefined ? JSON.stringify(body) : undefined,
  });
  if (!res.ok) {
    const text = await res.text().catch(() => res.statusText);
    throw new Error(`${res.status} ${method} ${path}: ${text}`);
  }
  return res.json() as Promise<T>;
}
async function del(path: string): Promise<void> {
  const res = await fetchWithAuth(`${apiBaseUrl}${path}`, { method: "DELETE" });
  if (!res.ok) {
    const text = await res.text().catch(() => res.statusText);
    throw new Error(`${res.status} DELETE ${path}: ${text}`);
  }
}

const fetchAccounts = () => get<BudgetAccount[]>("/budget/accounts");
const fetchTellerConfig = () => get<TellerConfig>("/budget/teller/config");
const fetchProfiles = () => get<BudgetProfile[]>("/budget/profiles");
const fetchGroupedCategories = (profileId: string | null) => {
  const p = new URLSearchParams();
  if (profileId) p.set("profile_id", profileId);
  return get<GroupedCategory[]>(
    `/budget/categories/grouped${p.toString() ? `?${p}` : ""}`,
  );
};
// ── Income forecast types + fetch (budget-020) ────────────────────────────────
interface IncomeForecastSource {
  template_id: string;
  description: string;
  amount: number;
  category_id: string | null;
  category_name: string | null;
  expected_date: string;
}
interface IncomeForecast {
  year: number;
  month: number;
  projected_income: number;
  actual_income: number;
  sources: IncomeForecastSource[];
  total_targets: number;
  left_to_allocate: number;
  is_future_month: boolean;
}
const fetchIncomeForecast = (
  year: number,
  month: number,
  profileId: string | null,
) => {
  const p = new URLSearchParams({ year: String(year), month: String(month) });
  if (profileId) p.set("profile_id", profileId);
  return get<IncomeForecast>(`/budget/income-forecast?${p}`);
};

const fetchTrends = (profileId: string | null, accountId: string | null) => {
  const p = new URLSearchParams({ months: "6" });
  if (profileId) p.set("profile_id", profileId);
  if (accountId) p.set("account_id", accountId);
  return get<{ months: TrendMonth[] }>(`/budget/trends?${p}`);
};
const fetchCategories = (profileId: string | null) => {
  const p = new URLSearchParams();
  if (profileId) p.set("profile_id", profileId);
  return get<BudgetCategory[]>(
    `/budget/categories${p.toString() ? `?${p}` : ""}`,
  );
};
const fetchAnalytics = (
  year: number,
  month: number,
  accountId: string | null,
  profileId: string | null,
  dateFrom?: string,
  dateTo?: string,
) => {
  const p = new URLSearchParams();
  if (dateFrom && dateTo) {
    // Arbitrary date range — skip year/month so backend uses date_from/date_to
    p.set("date_from", dateFrom);
    p.set("date_to", dateTo);
  } else {
    p.set("year", String(year));
    p.set("month", String(month));
  }
  if (accountId) p.set("account_id", accountId);
  if (profileId) p.set("profile_id", profileId);
  return get<AnalyticsResponse>(`/budget/analytics?${p}`);
};
const fetchProfitAnalytics = (
  profileId: string,
  year: number,
  month: number,
) => {
  const p = new URLSearchParams({
    profile_id: profileId,
    year: String(year),
    month: String(month),
  });
  return get<ProfitAnalyticsResponse>(`/budget/analytics/profit?${p}`);
};
const fetchSummary = (
  accountId: string | null,
  from: string,
  to: string,
  profileId: string | null,
) => {
  const p = new URLSearchParams({ date_from: from, date_to: to });
  if (accountId) p.set("account_id", accountId);
  if (profileId) p.set("profile_id", profileId);
  return get<BudgetSummary>(`/budget/summary?${p}`);
};
type TxnFilter =
  | { kind: "uncategorized" }
  | { kind: "category"; id: string; name: string }
  | null;

const fetchTransactions = (
  accountId: string | null,
  offset: number,
  profileId: string | null,
  search: string,
  txnFilter: TxnFilter,
  dateFrom?: string,
  dateTo?: string,
) => {
  const p = new URLSearchParams({
    limit: String(TXN_PAGE_SIZE),
    offset: String(offset),
  });
  if (accountId) p.set("account_id", accountId);
  if (profileId) p.set("profile_id", profileId);
  if (search.trim()) p.set("search", search.trim());
  if (txnFilter?.kind === "uncategorized") p.set("txn_type", "uncategorized");
  if (txnFilter?.kind === "category") p.set("category_id", txnFilter.id);
  if (dateFrom) p.set("date_from", dateFrom);
  if (dateTo) p.set("date_to", dateTo);
  return get<TransactionListResponse>(`/budget/transactions?${p}`);
};

// ── Formatting ────────────────────────────────────────────────────────────────

function fmt(amount: number, currency = "USD", compact = false): string {
  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency,
    minimumFractionDigits: compact ? 0 : 2,
    maximumFractionDigits: compact ? 0 : 2,
  }).format(Math.abs(amount));
}
function fmtDate(s: string) {
  return new Date(s + "T00:00:00").toLocaleDateString("en-US", {
    month: "short",
    day: "numeric",
  });
}

// ── Account dropdown ──────────────────────────────────────────────────────────

function AccountDropdown({
  accounts,
  value,
  onChange,
}: {
  accounts: BudgetAccount[] | undefined;
  value: string | null;
  onChange: (v: string | null) => void;
}) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  const selected = accounts?.find((a) => a.id === value);

  useEffect(() => {
    if (!open) return;
    const h = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node))
        setOpen(false);
    };
    document.addEventListener("mousedown", h);
    return () => document.removeEventListener("mousedown", h);
  }, [open]);

  if (!accounts || accounts.length === 0) return null;
  if (accounts.length === 1)
    return (
      <span className="text-sm text-muted-foreground">{accounts[0].name}</span>
    );

  return (
    <div ref={ref} className="relative">
      <button
        onClick={() => setOpen((v) => !v)}
        className="flex items-center gap-1.5 h-8 pl-2.5 pr-2 rounded-md border bg-background text-sm hover:bg-muted transition-colors text-foreground"
      >
        <span className="max-w-[140px] truncate">
          {selected?.name ?? "All accounts"}
        </span>
        <ChevronDown className="w-3.5 h-3.5 text-muted-foreground shrink-0" />
      </button>
      {open && (
        <>
          <div className="fixed inset-0 z-10" onClick={() => setOpen(false)} />
          <div className="absolute left-0 top-full mt-1 z-20 bg-background border rounded-lg shadow-lg py-1 min-w-[160px]">
            <button
              onClick={() => {
                onChange(null);
                setOpen(false);
              }}
              className={cn(
                "w-full text-left px-3 py-2 text-sm hover:bg-muted transition-colors",
                !value && "bg-muted font-medium",
              )}
            >
              All accounts
            </button>
            {accounts.map((acc) => (
              <button
                key={acc.id}
                onClick={() => {
                  onChange(acc.id);
                  setOpen(false);
                }}
                className={cn(
                  "w-full text-left px-3 py-2 text-sm hover:bg-muted transition-colors flex items-center justify-between gap-2",
                  value === acc.id && "bg-muted font-medium",
                )}
              >
                <span>{acc.name}</span>
                {acc.current_balance != null && (
                  <span className="text-xs text-muted-foreground tabular-nums shrink-0">
                    {acc.current_balance < 0 ? "−" : ""}
                    {Math.abs(acc.current_balance).toLocaleString("en-US", {
                      style: "currency",
                      currency: acc.currency,
                    })}
                  </span>
                )}
              </button>
            ))}
          </div>
        </>
      )}
    </div>
  );
}

// ── Account balance chip (budget-017) ─────────────────────────────────────────

function AccountBalanceChip({
  account,
  onUpdated,
}: {
  account: BudgetAccount;
  onUpdated: () => void;
}) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState("");
  const [saving, setSaving] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);

  function startEdit() {
    setDraft(
      account.current_balance != null ? String(account.current_balance) : "",
    );
    setEditing(true);
    setTimeout(() => inputRef.current?.select(), 0);
  }

  async function save() {
    const raw = draft.trim().replace(/[$,]/g, "");
    const num = raw === "" ? null : parseFloat(raw);
    if (raw !== "" && isNaN(num!)) {
      setEditing(false);
      return;
    }
    setSaving(true);
    try {
      await fetchWithAuth(`${apiBaseUrl}/budget/accounts/${account.id}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ current_balance: num }),
      });
      onUpdated();
    } finally {
      setSaving(false);
      setEditing(false);
    }
  }

  function handleKey(e: React.KeyboardEvent) {
    if (e.key === "Enter") void save();
    if (e.key === "Escape") setEditing(false);
  }

  const fmtBalance = (v: number) =>
    (v < 0 ? "−" : "") +
    Math.abs(v).toLocaleString("en-US", {
      style: "currency",
      currency: account.currency,
    });

  const updatedLabel = account.balance_updated_at
    ? new Date(account.balance_updated_at).toLocaleDateString("en-US", {
        month: "short",
        day: "numeric",
      })
    : null;

  if (editing) {
    return (
      <div className="flex items-center gap-1.5">
        <span className="text-xs text-muted-foreground">Balance:</span>
        <input
          ref={inputRef}
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={handleKey}
          onBlur={() => void save()}
          placeholder="0.00"
          className="w-24 h-6 text-xs border rounded px-1.5 bg-background focus:outline-none focus:ring-1 focus:ring-ring tabular-nums"
        />
        {saving && (
          <Loader2 className="w-3 h-3 animate-spin text-muted-foreground" />
        )}
      </div>
    );
  }

  return (
    <button
      onClick={startEdit}
      title="Click to update balance"
      className="flex items-center gap-1.5 text-xs text-muted-foreground hover:text-foreground transition-colors group"
    >
      <Wallet className="w-3.5 h-3.5 shrink-0" />
      {account.current_balance != null ? (
        <>
          <span className="tabular-nums font-medium text-foreground">
            {fmtBalance(account.current_balance)}
          </span>
          {updatedLabel && (
            <span className="text-muted-foreground/60">· {updatedLabel}</span>
          )}
        </>
      ) : (
        <span className="group-hover:underline">Set balance</span>
      )}
    </button>
  );
}

// ── Teller sync chip ─────────────────────────────────────────────────────────

function TellerSyncChip({
  account,
  onSynced,
}: {
  account: BudgetAccount;
  onSynced: () => void;
}) {
  const [syncing, setSyncing] = useState(false);
  const [unlinking, setUnlinking] = useState(false);
  const [resetting, setResetting] = useState(false);
  const [menuOpen, setMenuOpen] = useState(false);
  const [syncError, setSyncError] = useState<string | null>(null);
  const [syncResult, setSyncResult] = useState<string | null>(null);

  if (!account.teller_account_id) return null;

  const syncedLabel = account.teller_last_synced_at
    ? (() => {
        const diff =
          Date.now() - new Date(account.teller_last_synced_at).getTime();
        const mins = Math.floor(diff / 60_000);
        if (mins < 1) return "just now";
        if (mins < 60) return `${mins}m ago`;
        const hrs = Math.floor(mins / 60);
        if (hrs < 24) return `${hrs}h ago`;
        return `${Math.floor(hrs / 24)}d ago`;
      })()
    : "never synced";

  async function handleSync() {
    setSyncing(true);
    setMenuOpen(false);
    try {
      await fetchWithAuth(
        `${apiBaseUrl}/budget/accounts/${account.id}/teller/sync`,
        {
          method: "POST",
        },
      );
      onSynced();
    } finally {
      setSyncing(false);
    }
  }

  async function handleUnlink() {
    setUnlinking(true);
    setMenuOpen(false);
    try {
      await fetchWithAuth(
        `${apiBaseUrl}/budget/accounts/${account.id}/teller`,
        {
          method: "DELETE",
        },
      );
      onSynced();
    } finally {
      setUnlinking(false);
    }
  }

  async function handleResetAndSync() {
    setResetting(true);
    setMenuOpen(false);
    setSyncError(null);
    setSyncResult(null);
    try {
      // Clear the cursor so the next sync re-fetches available history
      const resetRes = await fetchWithAuth(
        `${apiBaseUrl}/budget/accounts/${account.id}/teller/reset-cursor`,
        { method: "POST" },
      );
      if (!resetRes.ok) {
        const text = await resetRes.text().catch(() => resetRes.statusText);
        setSyncError(`Reset failed: ${text}`);
        return;
      }
      // Trigger a full sync
      const syncRes = await fetchWithAuth(
        `${apiBaseUrl}/budget/accounts/${account.id}/teller/sync`,
        { method: "POST" },
      );
      if (!syncRes.ok) {
        const text = await syncRes.text().catch(() => syncRes.statusText);
        setSyncError(`Sync failed: ${text}`);
        return;
      }
      const data = (await syncRes.json()) as {
        inserted: number;
        skipped: number;
      };
      setSyncResult(
        data.inserted > 0
          ? `Imported ${data.inserted} transaction${data.inserted === 1 ? "" : "s"}`
          : "Up to date — no new transactions",
      );
      onSynced();
    } catch (e) {
      setSyncError(e instanceof Error ? e.message : "Sync failed");
    } finally {
      setResetting(false);
    }
  }

  return (
    <div className="relative flex items-center gap-1.5">
      <button
        onClick={() => void handleSync()}
        disabled={syncing}
        title={`Last synced: ${syncedLabel}`}
        className="flex items-center gap-1.5 text-xs text-muted-foreground hover:text-foreground transition-colors group"
      >
        {syncing ? (
          <Loader2 className="w-3.5 h-3.5 animate-spin shrink-0" />
        ) : (
          <ArrowLeftRight className="w-3.5 h-3.5 shrink-0" />
        )}
        <span className="font-medium text-foreground">
          {account.teller_institution_name ?? "Bank"}
        </span>
        <span className="text-muted-foreground/60">· {syncedLabel}</span>
      </button>
      {/* Overflow menu for unlink */}
      <div className="relative">
        <button
          onClick={() => setMenuOpen((v) => !v)}
          className="p-0.5 rounded text-muted-foreground/40 hover:text-muted-foreground transition-colors"
          title="Bank sync options"
        >
          <MoreHorizontal className="w-3.5 h-3.5" />
        </button>
        {menuOpen && (
          <>
            <div
              className="fixed inset-0 z-10"
              onClick={() => setMenuOpen(false)}
            />
            <div className="absolute left-0 top-full mt-1 z-20 bg-background border rounded-lg shadow-lg py-1 min-w-[180px]">
              <button
                onClick={() => void handleResetAndSync()}
                disabled={resetting || syncing}
                className="flex items-center gap-2 w-full px-3 py-2 text-xs text-foreground hover:bg-muted text-left transition-colors"
              >
                {resetting ? (
                  <Loader2 className="w-3 h-3 animate-spin" />
                ) : (
                  <ArrowLeftRight className="w-3 h-3" />
                )}
                Re-sync full history
              </button>
              <div className="my-1 border-t" />
              <button
                onClick={() => void handleUnlink()}
                disabled={unlinking}
                className="flex items-center gap-2 w-full px-3 py-2 text-xs text-destructive hover:bg-destructive/10 text-left transition-colors"
              >
                {unlinking ? (
                  <Loader2 className="w-3 h-3 animate-spin" />
                ) : (
                  <X className="w-3 h-3" />
                )}
                Disconnect bank
              </button>
            </div>
          </>
        )}
      </div>
      {/* Sync result / error toast */}
      {(syncResult || syncError) && (
        <span
          className={`text-xs ${syncError ? "text-destructive" : "text-muted-foreground"}`}
        >
          {syncError ?? syncResult}
        </span>
      )}
    </div>
  );
}

// ── Profile switcher ──────────────────────────────────────────────────────────

function ProfileSwitcher({
  profiles,
  value,
  onChange,
}: {
  profiles: BudgetProfile[] | undefined;
  value: string | null;
  onChange: (v: string) => void;
}) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  const selected = profiles?.find((p) => p.id === value) ?? profiles?.[0];

  useEffect(() => {
    if (!open) return;
    const h = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node))
        setOpen(false);
    };
    document.addEventListener("mousedown", h);
    return () => document.removeEventListener("mousedown", h);
  }, [open]);

  if (!profiles || profiles.length <= 1) return null;

  return (
    <div ref={ref} className="relative">
      <button
        onClick={() => setOpen((v) => !v)}
        className="flex items-center gap-1.5 h-7 pl-2.5 pr-2 rounded-full border bg-background text-xs font-medium hover:bg-muted transition-colors text-foreground"
      >
        <span className="max-w-[120px] truncate">
          {selected?.name ?? "Select profile"}
        </span>
        {selected?.budgeting_style === "profit_tracking" && (
          <span className="text-[10px] text-muted-foreground/70 bg-muted rounded px-1">
            P&L
          </span>
        )}
        <ChevronDown className="w-3 h-3 text-muted-foreground shrink-0" />
      </button>
      {open && (
        <>
          <div className="fixed inset-0 z-10" onClick={() => setOpen(false)} />
          <div className="absolute left-0 top-full mt-1 z-20 bg-background border rounded-lg shadow-lg py-1 min-w-[160px]">
            {profiles.map((profile) => (
              <button
                key={profile.id}
                onClick={() => {
                  onChange(profile.id);
                  setOpen(false);
                }}
                className={cn(
                  "w-full text-left px-3 py-2 text-sm hover:bg-muted transition-colors flex items-center justify-between gap-3",
                  value === profile.id && "bg-muted font-medium",
                )}
              >
                <span className="truncate">{profile.name}</span>
                {profile.budgeting_style === "profit_tracking" && (
                  <span className="text-[10px] text-muted-foreground/70 bg-muted rounded px-1 shrink-0">
                    P&L
                  </span>
                )}
              </button>
            ))}
          </div>
        </>
      )}
    </div>
  );
}

// ── SVG pie chart ─────────────────────────────────────────────────────────────

interface PieSlice extends CategoryEntry {
  startAngle: number;
  endAngle: number;
  midAngle: number;
  pct: number;
}

function arcPath(
  cx: number,
  cy: number,
  R: number,
  ri: number,
  start: number,
  end: number,
): string {
  // Full circle workaround (SVG can't describe a complete arc in one <path>)
  if (end - start >= 2 * Math.PI - 0.0001) {
    return [
      `M ${cx} ${cy - R}`,
      `A ${R} ${R} 0 1 1 ${cx - 0.001} ${cy - R}`,
      `L ${cx - 0.001} ${cy - ri}`,
      `A ${ri} ${ri} 0 1 0 ${cx} ${cy - ri}`,
      "Z",
    ].join("");
  }
  const large = end - start > Math.PI ? 1 : 0;
  const x1 = cx + R * Math.cos(start),
    y1 = cy + R * Math.sin(start);
  const x2 = cx + R * Math.cos(end),
    y2 = cy + R * Math.sin(end);
  const ix1 = cx + ri * Math.cos(end),
    iy1 = cy + ri * Math.sin(end);
  const ix2 = cx + ri * Math.cos(start),
    iy2 = cy + ri * Math.sin(start);
  return `M ${x1} ${y1} A ${R} ${R} 0 ${large} 1 ${x2} ${y2} L ${ix1} ${iy1} A ${ri} ${ri} 0 ${large} 0 ${ix2} ${iy2} Z`;
}

function PieChart({
  entries,
  totalExpenses,
  currency,
  onCategoryClick,
}: {
  entries: CategoryEntry[];
  totalExpenses: number;
  currency: string;
  onCategoryClick: (categoryId: string | null) => void;
}) {
  const [hovered, setHovered] = useState<PieSlice | null>(null);
  const [tip, setTip] = useState<{ x: number; y: number } | null>(null);
  const containerRef = useRef<HTMLDivElement>(null);

  const SIZE = 220,
    cx = SIZE / 2,
    cy = SIZE / 2,
    R = 90,
    ri = 52;

  const slices: PieSlice[] = [];
  let angle = -Math.PI / 2;
  for (const e of entries) {
    const sweep =
      totalExpenses > 0 ? (e.total_expenses / totalExpenses) * 2 * Math.PI : 0;
    slices.push({
      ...e,
      startAngle: angle,
      endAngle: angle + sweep,
      midAngle: angle + sweep / 2,
      pct: totalExpenses > 0 ? (e.total_expenses / totalExpenses) * 100 : 0,
    });
    angle += sweep;
  }

  const handleMouseMove = (e: React.MouseEvent, slice: PieSlice) => {
    if (!containerRef.current) return;
    const rect = containerRef.current.getBoundingClientRect();
    setHovered(slice);
    setTip({ x: e.clientX - rect.left, y: e.clientY - rect.top });
  };

  const centerLabel = hovered?.category_name.slice(0, 14) ?? "Total spent";
  const centerAmount = hovered
    ? fmt(hovered.total_expenses, currency)
    : fmt(totalExpenses, currency, true);

  return (
    <div ref={containerRef} className="relative flex flex-col items-center">
      <svg
        viewBox={`0 0 ${SIZE} ${SIZE}`}
        className="w-full max-w-[220px]"
        onMouseLeave={() => {
          setHovered(null);
          setTip(null);
        }}
      >
        {slices.map((s) => (
          <path
            key={s.category_id ?? "__none__"}
            d={arcPath(cx, cy, R, ri, s.startAngle, s.endAngle)}
            fill={s.category_color ?? "#94a3b8"}
            className="cursor-pointer transition-opacity"
            style={{
              opacity:
                hovered && hovered.category_id !== s.category_id ? 0.55 : 1,
            }}
            onMouseMove={(e) => handleMouseMove(e, s)}
            onClick={() => onCategoryClick(s.category_id)}
          />
        ))}
        {/* Center label */}
        <text
          x={cx}
          y={cy - 9}
          textAnchor="middle"
          fontSize="8.5"
          fill="currentColor"
          opacity="0.5"
          style={{ fontFamily: "inherit" }}
        >
          {centerLabel}
        </text>
        <text
          x={cx}
          y={cy + 9}
          textAnchor="middle"
          fontSize="14"
          fontWeight="600"
          fill="currentColor"
          style={{ fontFamily: "inherit" }}
        >
          {centerAmount}
        </text>
        {hovered && (
          <text
            x={cx}
            y={cy + 24}
            textAnchor="middle"
            fontSize="9"
            fill="currentColor"
            opacity="0.5"
            style={{ fontFamily: "inherit" }}
          >
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
            <span
              className="w-2 h-2 rounded-full shrink-0"
              style={{ backgroundColor: hovered.category_color ?? "#94a3b8" }}
            />
            <span className="font-medium">{hovered.category_name}</span>
          </div>
          <div className="text-muted-foreground">
            {fmt(hovered.total_expenses, currency)} · {hovered.pct.toFixed(1)}%
          </div>
          <div className="text-muted-foreground">
            {hovered.transaction_count}
            {""}
            {hovered.transaction_count === 1 ? "transaction" : "transactions"}
          </div>
        </div>
      )}
    </div>
  );
}

// ── Condensed category bar ────────────────────────────────────────────────────

function CategoryBarCondensed({
  entry,
  maxExpense,
  currency,
  onClick,
}: {
  entry: CategoryEntry;
  maxExpense: number;
  currency: string;
  onClick: () => void;
}) {
  const pct = maxExpense > 0 ? (entry.total_expenses / maxExpense) * 100 : 0;
  const color = entry.category_color ?? "#94a3b8";
  return (
    <button
      onClick={onClick}
      className="flex items-center gap-2.5 py-1.5 w-full text-left -mx-4 px-4 hover:bg-muted/50 transition-colors rounded"
    >
      <span
        className="w-2 h-2 rounded-full shrink-0"
        style={{ backgroundColor: color }}
      />
      <span className="text-xs w-28 truncate shrink-0 text-foreground">
        {entry.category_icon && (
          <span className="mr-1">{entry.category_icon}</span>
        )}
        {entry.category_name}
      </span>
      <div className="flex-1 h-1.5 rounded-full bg-muted overflow-hidden">
        <div
          className="h-full rounded-full"
          style={{ width: `${pct}%`, backgroundColor: color, opacity: 0.75 }}
        />
      </div>
      <span className="text-xs tabular-nums text-muted-foreground shrink-0 w-16 text-right">
        {fmt(entry.total_expenses, currency)}
      </span>
    </button>
  );
}

// ── Envelope row (list view with budget data) ─────────────────────────────────

function CategoryEnvelopeRow({
  entry,
  currency,
  onClick,
  onBudgetSet,
}: {
  entry: CategoryEntry;
  currency: string;
  onClick: () => void;
  onBudgetSet: (categoryId: string, amount: number | null) => void;
}) {
  const color = entry.category_color ?? "#94a3b8";
  const hasBudget = entry.budgeted != null && entry.budgeted > 0;
  const pct = hasBudget
    ? Math.min((entry.total_expenses / (entry.budgeted ?? 1)) * 100, 100)
    : 0;
  const overBudget = entry.is_over_budget;
  const hasRollover = Math.abs(entry.rollover_amount ?? 0) >= 0.01;

  // Inline budget editing state
  const [editingBudget, setEditingBudget] = useState(false);
  const [budgetDraft, setBudgetDraft] = useState("");
  const [savingBudget, setSavingBudget] = useState(false);
  const budgetInputRef = useRef<HTMLInputElement>(null);

  function startBudgetEdit(e: React.MouseEvent) {
    e.stopPropagation();
    setBudgetDraft(entry.budgeted != null ? String(entry.budgeted) : "");
    setEditingBudget(true);
    setTimeout(() => {
      budgetInputRef.current?.select();
    }, 10);
  }

  async function saveBudget() {
    if (!entry.category_id) {
      setEditingBudget(false);
      return;
    }
    const raw = budgetDraft.trim().replace(/[$,]/g, "");
    const num = raw === "" ? null : parseFloat(raw);
    setSavingBudget(true);
    try {
      await mutate("PATCH", `/budget/categories/${entry.category_id}`, {
        default_monthly_amount:
          num != null && !isNaN(num) && num > 0 ? num : null,
      });
      onBudgetSet(
        entry.category_id,
        num != null && !isNaN(num) && num > 0 ? num : null,
      );
    } finally {
      setSavingBudget(false);
      setEditingBudget(false);
    }
  }

  function handleBudgetKey(e: React.KeyboardEvent) {
    if (e.key === "Enter") void saveBudget();
    if (e.key === "Escape") setEditingBudget(false);
  }

  return (
    <div className="flex flex-col gap-1 py-2.5 w-full -mx-4 px-4">
      <div className="flex items-center gap-2.5">
        {/* Name — clickable to navigate */}
        <button
          onClick={onClick}
          className="flex items-center gap-2.5 flex-1 min-w-0 text-left hover:opacity-70 transition-opacity"
        >
          <span
            className="w-2 h-2 rounded-full shrink-0"
            style={{ backgroundColor: color }}
          />
          <span className="text-xs flex-1 min-w-0 truncate text-foreground">
            {entry.category_icon && (
              <span className="mr-1">{entry.category_icon}</span>
            )}
            {entry.category_name}
            {hasRollover && (
              <span
                className={cn(
                  "ml-1.5 text-[10px]",
                  (entry.rollover_amount ?? 0) < 0
                    ? "text-budget-negative"
                    : "text-sky-500",
                )}
                title={`Rollover: ${(entry.rollover_amount ?? 0) >= 0 ? "+" : ""}${(entry.rollover_amount ?? 0).toFixed(2)} from last month`}
              >
                {(entry.rollover_amount ?? 0) >= 0 ? "+" : "−"}
                {fmt(Math.abs(entry.rollover_amount ?? 0), currency, true)}
                {""}
                carried
              </span>
            )}
          </span>
        </button>

        {/* Budget amount — clickable to edit inline */}
        {editingBudget ? (
          <div
            className="flex items-center gap-1 shrink-0"
            onClick={(e) => e.stopPropagation()}
          >
            <span className="text-xs text-muted-foreground tabular-nums">
              {fmt(entry.total_expenses, currency)} /
            </span>
            <input
              ref={budgetInputRef}
              type="number"
              min="0"
              step="1"
              value={budgetDraft}
              onChange={(e) => setBudgetDraft(e.target.value)}
              onBlur={() => void saveBudget()}
              onKeyDown={handleBudgetKey}
              placeholder="0"
              className="w-20 h-5 text-xs px-1.5 border rounded bg-background focus:outline-none focus:ring-1 focus:ring-ring tabular-nums text-right"
            />
            {savingBudget && (
              <Loader2 className="w-3 h-3 animate-spin text-muted-foreground" />
            )}
          </div>
        ) : hasBudget ? (
          <button
            onClick={startBudgetEdit}
            title="Click to edit budget"
            className={cn(
              "text-xs tabular-nums shrink-0 rounded px-0.5 hover:bg-muted transition-colors",
              overBudget
                ? "text-budget-negative font-medium"
                : "text-muted-foreground",
            )}
          >
            {fmt(entry.total_expenses, currency)}
            <span className="text-muted-foreground/60">
              {""}/ {fmt(entry.budgeted!, currency)}
            </span>
          </button>
        ) : (
          <button
            onClick={startBudgetEdit}
            title="Set a budget"
            className="text-xs tabular-nums text-muted-foreground/50 hover:text-muted-foreground shrink-0 rounded px-0.5 hover:bg-muted transition-colors"
          >
            {fmt(entry.total_expenses, currency)}
            {""}
            <span className="text-muted-foreground/30">/ —</span>
          </button>
        )}
      </div>

      {hasBudget && (
        <div className="ml-4.5 flex items-center gap-2">
          <div className="flex-1 h-1 rounded-full bg-muted overflow-hidden">
            <div
              className="h-full rounded-full transition-all"
              style={{
                width: `${pct}%`,
                backgroundColor: overBudget ? "#ef4444" : color,
                opacity: 0.8,
              }}
            />
          </div>
          <span
            className={cn(
              "text-xs tabular-nums shrink-0 w-20 text-right",
              overBudget ? "text-budget-negative" : "text-muted-foreground",
            )}
          >
            {overBudget
              ? `${fmt(Math.abs(entry.remaining ?? 0), currency)} over`
              : entry.remaining != null
                ? `${fmt(entry.remaining, currency)} left`
                : ""}
          </span>
        </div>
      )}
    </div>
  );
}

// ── Grouped breakdown ─────────────────────────────────────────────────────────

/**
 * Organise a flat list of CategoryEntry by group order.
 * Returns an array of { group, entries } pairs, respecting sort_order.
 * Entries whose category_id doesn't match any group fall into an"Other"bucket.
 */
function buildGroupedEntries(
  entries: CategoryEntry[],
  groups: GroupedCategory[],
): Array<{
  groupId: string | null;
  groupName: string;
  sortOrder: number;
  entries: CategoryEntry[];
}> {
  // Build a lookup: categoryId → group
  const catToGroup = new Map<
    string,
    { id: string | null; name: string; sort_order: number }
  >();
  for (const g of groups) {
    for (const cat of g.categories) {
      catToGroup.set(cat.id, {
        id: g.id,
        name: g.name,
        sort_order: g.sort_order,
      });
    }
  }

  const buckets = new Map<
    string | null,
    {
      groupId: string | null;
      groupName: string;
      sortOrder: number;
      entries: CategoryEntry[];
    }
  >();
  const OTHER_KEY = "__other__";

  for (const entry of entries) {
    const grp = entry.category_id
      ? catToGroup.get(entry.category_id)
      : undefined;
    const key = grp ? (grp.id ?? OTHER_KEY) : OTHER_KEY;
    if (!buckets.has(key)) {
      buckets.set(key, {
        groupId: grp?.id ?? null,
        groupName: grp?.name ?? "Other",
        sortOrder: grp?.sort_order ?? 999,
        entries: [],
      });
    }
    buckets.get(key)!.entries.push(entry);
  }

  return [...buckets.values()].sort((a, b) => a.sortOrder - b.sortOrder);
}

function GroupedBreakdown({
  entries,
  groups,
  currency,
  onCategoryClick,
  onBudgetSet,
}: {
  entries: CategoryEntry[];
  groups: GroupedCategory[];
  currency: string;
  onCategoryClick: (id: string | null) => void;
  onBudgetSet: (categoryId: string, amount: number | null) => void;
}) {
  const bucketed = buildGroupedEntries(entries, groups);
  const [collapsed, setCollapsed] = useState<Set<string>>(new Set());

  const toggleGroup = (key: string) => {
    setCollapsed((prev) => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });
  };

  // If no groups exist yet, fall back to flat list
  if (bucketed.length <= 1 && bucketed[0]?.groupId === null) {
    return (
      <div className="rounded-lg border px-4 py-1 divide-y">
        {entries.map((e) => (
          <CategoryEnvelopeRow
            key={e.category_id ?? "__none__"}
            entry={e}
            currency={currency}
            onClick={() => onCategoryClick(e.category_id)}
            onBudgetSet={onBudgetSet}
          />
        ))}
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-2">
      {bucketed.map((bucket) => {
        const key = bucket.groupId ?? "__other__";
        const isCollapsed = collapsed.has(key);
        const groupTotal = bucket.entries.reduce(
          (s, e) => s + e.total_expenses,
          0,
        );
        return (
          <div key={key} className="rounded-lg border overflow-hidden">
            {/* Group header */}
            <button
              onClick={() => toggleGroup(key)}
              className="flex items-center gap-2 w-full px-4 py-2 bg-muted/40 hover:bg-muted/70 transition-colors text-left"
            >
              {isCollapsed ? (
                <ChevronRight className="w-3 h-3 text-muted-foreground shrink-0" />
              ) : (
                <ChevronDown className="w-3 h-3 text-muted-foreground shrink-0" />
              )}
              <span className="text-xs font-semibold text-muted-foreground uppercase tracking-wide flex-1 truncate">
                {bucket.groupName}
              </span>
              <span className="text-xs tabular-nums text-muted-foreground shrink-0">
                {fmt(groupTotal, currency)}
              </span>
            </button>

            {/* Category rows */}
            {!isCollapsed && (
              <div className="px-4 py-1 divide-y">
                {bucket.entries.map((e) => (
                  <CategoryEnvelopeRow
                    key={e.category_id ?? "__none__"}
                    entry={e}
                    currency={currency}
                    onClick={() => onCategoryClick(e.category_id)}
                    onBudgetSet={onBudgetSet}
                  />
                ))}
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}

// ── Trends chart ─────────────────────────────────────────────────────────────

function TrendsChart({
  months,
  currency,
  isLoading,
}: {
  months: TrendMonth[];
  currency: string;
  isLoading: boolean;
}) {
  const SHORT_MONTHS = [
    "Jan",
    "Feb",
    "Mar",
    "Apr",
    "May",
    "Jun",
    "Jul",
    "Aug",
    "Sep",
    "Oct",
    "Nov",
    "Dec",
  ];
  const [hovered, setHovered] = useState<TrendMonth | null>(null);

  if (isLoading) {
    return (
      <div className="flex items-center justify-center py-12 text-muted-foreground gap-2 text-sm">
        <Loader2 className="w-4 h-4 animate-spin" /> Loading trends…
      </div>
    );
  }
  if (!months.length)
    return (
      <p className="text-sm text-muted-foreground text-center py-8">
        No data yet.
      </p>
    );

  const maxVal =
    Math.max(
      ...months.flatMap((m) => [
        m.total_income,
        m.total_expenses,
        m.total_budgeted,
      ]),
    ) || 1;
  const BAR_W = 18;
  const GAP = 10;
  const GROUP_GAP = 18;
  const H = 120;
  const COLS = months.length;
  const totalW = COLS * (3 * BAR_W + 2 * GAP + GROUP_GAP) - GROUP_GAP;
  const PAD_L = 48;
  const PAD_T = 8;
  const PAD_B = 28;
  const svgW = PAD_L + totalW;
  const svgH = H + PAD_T + PAD_B;

  const bar = (x: number, value: number, color: string) => {
    const h = Math.max(2, (value / maxVal) * H);
    const y = PAD_T + H - h;
    return (
      <rect
        x={x}
        y={y}
        width={BAR_W}
        height={h}
        rx={2}
        fill={color}
        opacity={0.85}
      />
    );
  };

  // Y-axis labels (3 ticks)
  const ticks = [0, 0.5, 1].map((f) => ({
    value: maxVal * f,
    y: PAD_T + H - f * H,
  }));

  const hov = hovered;

  return (
    <div className="rounded-lg border p-4">
      {/* Legend */}
      <div className="flex items-center gap-4 mb-3 text-xs text-muted-foreground">
        <span className="flex items-center gap-1.5">
          <span className="w-2.5 h-2.5 rounded-sm dot-budget-positive" />
          Income
        </span>
        <span className="flex items-center gap-1.5">
          <span className="w-2.5 h-2.5 rounded-sm dot-budget-negative" />
          Expenses
        </span>
        <span className="flex items-center gap-1.5">
          <span className="w-2.5 h-2.5 rounded-sm bg-sky-400/80" />
          Budgeted
        </span>
      </div>

      {/* Hovered month detail */}
      {hov && (
        <div className="flex items-center gap-4 mb-2 text-xs tabular-nums">
          <span className="font-medium text-foreground">
            {SHORT_MONTHS[hov.month - 1]} {hov.year}
          </span>
          <span className="text-budget-positive">
            +{fmt(hov.total_income, currency)}
          </span>
          <span className="text-budget-negative">
            −{fmt(hov.total_expenses, currency)}
          </span>
          {hov.total_budgeted > 0 && (
            <span className="text-sky-500">
              target {fmt(hov.total_budgeted, currency)}
            </span>
          )}
          <span
            className={cn(
              "ml-auto font-medium",
              hov.net >= 0 ? "text-budget-positive" : "text-budget-negative",
            )}
          >
            net {hov.net >= 0 ? "+" : "−"}
            {fmt(Math.abs(hov.net), currency)}
          </span>
        </div>
      )}

      <div className="overflow-x-auto">
        <svg width={svgW} height={svgH} className="overflow-visible">
          {/* Y-axis ticks */}
          {ticks.map((t) => (
            <g key={t.value}>
              <line
                x1={PAD_L - 4}
                x2={PAD_L + totalW}
                y1={t.y}
                y2={t.y}
                stroke="currentColor"
                strokeOpacity={0.08}
                strokeWidth={1}
              />
              <text
                x={PAD_L - 8}
                y={t.y + 4}
                textAnchor="end"
                fontSize={9}
                fill="currentColor"
                opacity={0.45}
              >
                {fmt(t.value, currency, true)}
              </text>
            </g>
          ))}

          {/* Bars per month */}
          {months.map((m, i) => {
            const gx = PAD_L + i * (3 * BAR_W + 2 * GAP + GROUP_GAP);
            const midX = gx + BAR_W + GAP + BAR_W / 2;
            const isHov = hov?.year === m.year && hov?.month === m.month;
            return (
              <g
                key={`${m.year}-${m.month}`}
                onMouseEnter={() => setHovered(m)}
                onMouseLeave={() => setHovered(null)}
                style={{ cursor: "default" }}
              >
                {/* hover bg */}
                {isHov && (
                  <rect
                    x={gx - 4}
                    y={PAD_T}
                    width={3 * BAR_W + 2 * GAP + 8}
                    height={H}
                    rx={3}
                    fill="currentColor"
                    opacity={0.05}
                  />
                )}
                {bar(gx, m.total_income, "#22c55e")}
                {bar(gx + BAR_W + GAP, m.total_expenses, "#f87171")}
                {bar(
                  gx + 2 * (BAR_W + GAP),
                  m.total_budgeted > 0 ? m.total_budgeted : 0,
                  "#38bdf8",
                )}
                {/* X label */}
                <text
                  x={midX}
                  y={PAD_T + H + 16}
                  textAnchor="middle"
                  fontSize={9}
                  fill="currentColor"
                  opacity={0.5}
                >
                  {SHORT_MONTHS[m.month - 1]}
                </text>
              </g>
            );
          })}
        </svg>
      </div>
    </div>
  );
}

// ── Category picker ───────────────────────────────────────────────────────────

function CategoryPicker({
  txn,
  categories,
  onAssigned,
  onTransferToggled,
}: {
  txn: BudgetTransaction;
  categories: BudgetCategory[];
  onAssigned: (txnId: string, catId: string | null) => void;
  onTransferToggled: (txnId: string, isTransfer: boolean) => void;
}) {
  const qc = useQueryClient();
  const [open, setOpen] = useState(false);
  const [dropUp, setDropUp] = useState(false);
  const [saving, setSaving] = useState(false);
  const [search, setSearch] = useState("");
  const [applyPrompt, setApplyPrompt] = useState<{
    catId: string;
    merchant: string;
  } | null>(null);
  const [applying, setApplying] = useState(false);
  const [applyResult, setApplyResult] = useState<string | null>(null);
  const [transferApplyPrompt, setTransferApplyPrompt] = useState<{
    merchant: string;
  } | null>(null);
  const [applyingTransfer, setApplyingTransfer] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  const triggerRef = useRef<HTMLButtonElement>(null);
  const assigned = categories.find((c) => c.id === txn.category_id);
  const filteredCats = search.trim()
    ? categories.filter((c) =>
        c.name.toLowerCase().includes(search.toLowerCase()),
      )
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
    const h = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node))
        setOpen(false);
    };
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
      const body: Record<string, unknown> = { is_transfer: isTransfer };
      if (isTransfer && txn.category_id) body.category_id = null;
      await mutate("PATCH", `/budget/transactions/${txn.id}`, body);
      if (isTransfer && txn.category_id) onAssigned(txn.id, null);
      onTransferToggled(txn.id, isTransfer);
      // Offer to propagate to other transactions from the same merchant
      if (isTransfer) {
        const matchText = txn.merchant_name || txn.description;
        if (matchText) setTransferApplyPrompt({ merchant: matchText });
      } else {
        setTransferApplyPrompt(null);
      }
    } finally {
      setSaving(false);
      setOpen(false);
    }
  };

  const applyTransferToSimilar = async () => {
    if (!transferApplyPrompt) return;
    setApplyingTransfer(true);
    try {
      const p = new URLSearchParams({ transaction_id: txn.id });
      const res = await mutate<{ updated: number }>(
        "POST",
        `/budget/apply-transfer-to-similar?${p}`,
      );
      setApplyResult(
        res.updated > 0
          ? `Marked ${res.updated} more transaction${res.updated === 1 ? "" : "s"} as transfer`
          : "No other matches found",
      );
      void qc.invalidateQueries({ queryKey: ["budget", "analytics"] });
      void qc.invalidateQueries({ queryKey: ["budget", "summary"] });
      void qc.invalidateQueries({ queryKey: ["budget", "transactions"] });
    } finally {
      setApplyingTransfer(false);
      setTransferApplyPrompt(null);
    }
  };

  const pick = async (catId: string | null) => {
    setSaving(true);
    try {
      await mutate("PATCH", `/budget/transactions/${txn.id}`, {
        category_id: catId,
      });
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
      const p = new URLSearchParams({
        transaction_id: txn.id,
        category_id: applyPrompt.catId,
      });
      const res = await mutate<{ updated: number; keyword_added: boolean }>(
        "POST",
        `/budget/apply-to-similar?${p}`,
      );
      setApplyResult(
        res.updated > 0
          ? `Applied to ${res.updated} more transaction${res.updated === 1 ? "" : "s"}`
          : "No other matches found",
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
          {saving ? (
            <Loader2 className="w-3 h-3 animate-spin" />
          ) : (
            <ArrowLeftRight className="w-3 h-3" />
          )}
          Transfer
        </button>
        {open && (
          <div
            className={cn(
              "absolute right-0 z-50 w-44 rounded-lg border bg-background shadow-lg text-sm py-1",
              dropUp ? "bottom-full mb-1" : "top-full mt-1",
            )}
          >
            <button
              onClick={() => void toggleTransfer(false)}
              className="w-full text-left px-3 py-1.5 hover:bg-muted transition-colors text-muted-foreground"
            >
              Unmark as transfer
            </button>
          </div>
        )}
        {/*"Mark all similar as transfer? "prompt — must live in both branches */}
        {(transferApplyPrompt || applyResult) && (
          <div
            className={cn(
              "absolute right-0 z-50 whitespace-nowrap rounded-lg border bg-background shadow-lg px-3 py-2 text-xs flex items-center gap-2",
              dropUp ? "bottom-full mb-1" : "top-full mt-1",
            )}
          >
            {applyResult ? (
              <span className="text-muted-foreground">{applyResult}</span>
            ) : (
              <>
                <span className="text-muted-foreground truncate max-w-[140px]">
                  Mark all &ldquo;{transferApplyPrompt!.merchant}&rdquo; as
                  transfer?
                </span>
                <button
                  onClick={() => void applyTransferToSimilar()}
                  disabled={applyingTransfer}
                  className="font-medium text-primary hover:underline disabled:opacity-50"
                >
                  {applyingTransfer ? (
                    <Loader2 className="w-3 h-3 animate-spin" />
                  ) : (
                    "Yes"
                  )}
                </button>
                <button
                  onClick={() => setTransferApplyPrompt(null)}
                  className="text-muted-foreground hover:text-foreground"
                >
                  ✕
                </button>
              </>
            )}
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
        className={cn(
          "flex items-center gap-1 rounded-full px-2 py-0.5 text-xs transition-colors",
          assigned
            ? "text-white"
            : "bg-muted text-muted-foreground hover:text-foreground",
        )}
        style={
          assigned?.color ? { backgroundColor: assigned.color } : undefined
        }
      >
        {saving ? (
          <Loader2 className="w-3 h-3 animate-spin" />
        ) : assigned ? (
          <>
            {assigned.icon && <span>{assigned.icon}</span>} {assigned.name}
          </>
        ) : (
          <>
            <Tag className="w-3 h-3" /> Categorize
          </>
        )}
      </button>

      {/*"Apply to all similar? "prompt — category */}
      {(applyPrompt || applyResult) && (
        <div
          className={cn(
            "absolute right-0 z-50 whitespace-nowrap rounded-lg border bg-background shadow-lg px-3 py-2 text-xs flex items-center gap-2",
            dropUp ? "bottom-full mb-1" : "top-full mt-1",
          )}
        >
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
                {applying ? (
                  <Loader2 className="w-3 h-3 animate-spin" />
                ) : (
                  "Yes"
                )}
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

      {/*"Mark all similar as transfer? "prompt */}
      {transferApplyPrompt && !applyResult && (
        <div
          className={cn(
            "absolute right-0 z-50 whitespace-nowrap rounded-lg border bg-background shadow-lg px-3 py-2 text-xs flex items-center gap-2",
            dropUp ? "bottom-full mb-1" : "top-full mt-1",
          )}
        >
          <span className="text-muted-foreground truncate max-w-[140px]">
            Mark all &ldquo;{transferApplyPrompt.merchant}&rdquo; as transfer?
          </span>
          <button
            onClick={() => void applyTransferToSimilar()}
            disabled={applyingTransfer}
            className="font-medium text-primary hover:underline disabled:opacity-50"
          >
            {applyingTransfer ? (
              <Loader2 className="w-3 h-3 animate-spin" />
            ) : (
              "Yes"
            )}
          </button>
          <button
            onClick={() => setTransferApplyPrompt(null)}
            className="text-muted-foreground hover:text-foreground"
          >
            ✕
          </button>
        </div>
      )}

      {open && (
        <div
          className={cn(
            "absolute right-0 z-50 w-52 rounded-lg border bg-background shadow-lg text-sm",
            dropUp ? "bottom-full mb-1" : "top-full mt-1",
          )}
        >
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
                  txn.category_id === cat.id && "bg-muted",
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
            {filteredCats.length === 0 && search && (
              <p className="px-3 py-2 text-muted-foreground text-xs">
                No matches
              </p>
            )}
            {categories.length === 0 && (
              <p className="px-3 py-2 text-muted-foreground text-xs">
                No categories yet
              </p>
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

// ── Transaction edit sheet ────────────────────────────────────────────────────

function TxnEditSheet({
  txn,
  currency,
  onClose,
  onSaved,
  onDeleted,
}: {
  txn: BudgetTransaction;
  currency: string;
  onClose: () => void;
  onSaved: (txnId: string) => void;
  onDeleted: (txnId: string) => void;
}) {
  const [date, setDate] = useState(txn.date);
  const [amountStr, setAmountStr] = useState(Math.abs(txn.amount).toFixed(2));
  const [isExpense, setIsExpense] = useState(txn.amount < 0);
  const [description, setDescription] = useState(txn.description);
  const [merchantName, setMerchantName] = useState(txn.merchant_name ?? "");
  const [notes, setNotes] = useState(txn.notes ?? "");
  const [isTransfer, setIsTransfer] = useState(txn.is_transfer);
  const [saving, setSaving] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const h = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    document.addEventListener("keydown", h);
    return () => document.removeEventListener("keydown", h);
  }, [onClose]);

  const handleSave = async () => {
    const parsed = parseFloat(amountStr);
    if (isNaN(parsed) || parsed < 0) {
      setError("Enter a valid amount.");
      return;
    }
    setSaving(true);
    setError(null);
    try {
      await mutate("PATCH", `/budget/transactions/${txn.id}`, {
        date,
        amount: isExpense ? -Math.abs(parsed) : Math.abs(parsed),
        description: description.trim() || txn.description,
        merchant_name: merchantName.trim() || null,
        notes: notes.trim() || null,
        is_transfer: isTransfer,
      });
      onSaved(txn.id);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Save failed.");
    } finally {
      setSaving(false);
    }
  };

  const handleDelete = async () => {
    setDeleting(true);
    try {
      await del(`/budget/transactions/${txn.id}`);
      onDeleted(txn.id);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Delete failed.");
      setDeleting(false);
      setConfirmDelete(false);
    }
  };

  const label = (text: string) => (
    <label className="block text-xs font-medium text-muted-foreground uppercase tracking-wide mb-1.5">
      {text}
    </label>
  );
  const inputCls =
    "w-full h-9 px-3 rounded-md border bg-background text-sm focus:outline-none focus:ring-1 focus:ring-ring";

  return (
    <>
      {/* Backdrop */}
      <div
        className="fixed inset-0 z-40 bg-black/40 backdrop-blur-[2px]"
        onClick={onClose}
      />
      {/* Sheet */}
      <div className="fixed inset-y-0 right-0 z-50 w-full max-w-sm bg-background border-l shadow-xl flex flex-col">
        {/* Header */}
        <div className="flex items-center justify-between px-5 py-4 border-b shrink-0">
          <h2 className="text-base font-semibold">Edit transaction</h2>
          <button
            onClick={onClose}
            className="text-muted-foreground hover:text-foreground transition-colors p-1"
          >
            <X className="w-4 h-4" />
          </button>
        </div>

        {/* Body */}
        <div className="flex-1 overflow-y-auto px-5 py-5 space-y-4">
          {/* Date */}
          <div>
            {label("Date")}
            <input
              type="date"
              value={date}
              onChange={(e) => setDate(e.target.value)}
              className={inputCls}
            />
          </div>

          {/* Amount */}
          <div>
            {label("Amount")}
            <div className="flex gap-2">
              <div className="flex rounded-md border overflow-hidden shrink-0 text-xs">
                <button
                  onClick={() => setIsExpense(true)}
                  className={cn(
                    "px-3 py-2 font-medium transition-colors",
                    isExpense
                      ? "bg-muted text-foreground"
                      : "text-muted-foreground hover:bg-muted/50",
                  )}
                >
                  Expense
                </button>
                <button
                  onClick={() => setIsExpense(false)}
                  className={cn(
                    "px-3 py-2 font-medium transition-colors border-l",
                    !isExpense
                      ? "bg-muted text-foreground"
                      : "text-muted-foreground hover:bg-muted/50",
                  )}
                >
                  Income
                </button>
              </div>
              <input
                type="number"
                step="0.01"
                min="0"
                value={amountStr}
                onChange={(e) => setAmountStr(e.target.value)}
                className={cn(inputCls, "flex-1")}
              />
            </div>
          </div>

          {/* Description */}
          <div>
            {label("Description")}
            <input
              type="text"
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              className={inputCls}
            />
          </div>

          {/* Merchant */}
          <div>
            {label("Merchant")}
            <input
              type="text"
              value={merchantName}
              onChange={(e) => setMerchantName(e.target.value)}
              placeholder="Optional"
              className={inputCls}
            />
          </div>

          {/* Notes */}
          <div>
            {label("Notes")}
            <textarea
              value={notes}
              onChange={(e) => setNotes(e.target.value)}
              placeholder="Optional"
              rows={2}
              className="w-full px-3 py-2 rounded-md border bg-background text-sm resize-none focus:outline-none focus:ring-1 focus:ring-ring placeholder:text-muted-foreground/50"
            />
          </div>

          {/* Transfer toggle */}
          <div className="flex items-center justify-between py-1">
            <div>
              <p className="text-sm font-medium">Mark as transfer</p>
              <p className="text-xs text-muted-foreground">
                Excluded from spending totals
              </p>
            </div>
            <button
              onClick={() => setIsTransfer((v) => !v)}
              className={cn(
                "w-10 h-5 rounded-full transition-colors relative shrink-0",
                isTransfer ? "bg-primary" : "bg-input border border-border",
              )}
              aria-label={isTransfer ? "Unmark transfer" : "Mark as transfer"}
            >
              <span
                className={cn(
                  "absolute top-0.5 w-4 h-4 rounded-full shadow-sm transition-transform",
                  isTransfer
                    ? "bg-primary-foreground translate-x-5"
                    : "bg-foreground/30 translate-x-0.5",
                )}
              />
            </button>
          </div>

          {error && <p className="text-xs text-destructive">{error}</p>}
        </div>

        {/* Footer */}
        <div className="border-t px-5 py-4 shrink-0">
          {confirmDelete ? (
            <div className="flex items-center justify-between gap-3">
              <span className="text-sm text-muted-foreground">
                Delete this transaction?
              </span>
              <div className="flex gap-2">
                <Button
                  size="sm"
                  variant="ghost"
                  onClick={() => setConfirmDelete(false)}
                  disabled={deleting}
                >
                  Cancel
                </Button>
                <Button
                  size="sm"
                  variant="destructive"
                  onClick={() => void handleDelete()}
                  disabled={deleting}
                >
                  {deleting && (
                    <Loader2 className="w-3 h-3 animate-spin mr-1" />
                  )}
                  Delete
                </Button>
              </div>
            </div>
          ) : (
            <div className="flex items-center justify-between gap-3">
              <Button
                size="sm"
                variant="ghost"
                className="text-destructive hover:text-destructive hover:bg-destructive/10"
                onClick={() => setConfirmDelete(true)}
              >
                <Trash2 className="w-3.5 h-3.5 mr-1.5" />
                Delete
              </Button>
              <div className="flex gap-2">
                <Button size="sm" variant="outline" onClick={onClose}>
                  Cancel
                </Button>
                <Button
                  size="sm"
                  onClick={() => void handleSave()}
                  disabled={saving}
                >
                  {saving && <Loader2 className="w-3 h-3 animate-spin mr-1" />}
                  Save
                </Button>
              </div>
            </div>
          )}
        </div>
      </div>
    </>
  );
}

// ── Per-transaction actions menu (move to profile, etc.) ─────────────────────

function TxnActionsMenu({
  txnId,
  profiles,
  currentProfileId,
  onMoved,
  recurring,
  recurringTemplateId,
  onRecurringChanged,
}: {
  txnId: string;
  profiles: BudgetProfile[];
  currentProfileId: string | null;
  onMoved: (txnId: string, profileId: string | null) => void;
  recurring: RecurringRule | null;
  recurringTemplateId: string | null;
  onRecurringChanged: () => void;
}) {
  const [open, setOpen] = useState(false);
  const [moving, setMoving] = useState(false);
  const [settingRecurring, setSettingRecurring] = useState(false);
  const [recurringPicker, setRecurringPicker] = useState(false);
  const [dropUp, setDropUp] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  const triggerRef = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    if (!open) return;
    const h = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node))
        setOpen(false);
    };
    document.addEventListener("mousedown", h);
    return () => document.removeEventListener("mousedown", h);
  }, [open]);

  const handleToggle = () => {
    if (!open && triggerRef.current) {
      const rect = triggerRef.current.getBoundingClientRect();
      setDropUp(rect.bottom > window.innerHeight * 0.55);
    }
    setRecurringPicker(false);
    setOpen((v) => !v);
  };

  const moveTo = async (targetProfileId: string | null) => {
    setMoving(true);
    try {
      await mutate("POST", `/budget/transactions/${txnId}/move-to-profile`, {
        target_profile_id: targetProfileId,
      });
      onMoved(txnId, targetProfileId);
    } finally {
      setMoving(false);
      setOpen(false);
    }
  };

  const setRecurring = async (
    frequency: "monthly" | "weekly" | "bi_weekly" | "semi_monthly",
  ) => {
    setSettingRecurring(true);
    try {
      await mutate("PATCH", `/budget/transactions/${txnId}`, {
        recurring: { frequency, interval: 1, end_date: null },
      });
      onRecurringChanged();
    } finally {
      setSettingRecurring(false);
      setOpen(false);
      setRecurringPicker(false);
    }
  };

  const removeRecurring = async () => {
    setSettingRecurring(true);
    try {
      await mutate("PATCH", `/budget/transactions/${txnId}`, {
        recurring: null,
      });
      onRecurringChanged();
    } finally {
      setSettingRecurring(false);
      setOpen(false);
    }
  };

  const isTemplate = !!recurring;
  const isInstance = !recurring && !!recurringTemplateId;
  const hasActions = profiles.length > 1 || !isInstance;

  if (!hasActions) return null;

  return (
    <div
      ref={ref}
      className="relative shrink-0 opacity-0 group-hover:opacity-100 transition-opacity"
    >
      <button
        ref={triggerRef}
        onClick={handleToggle}
        className="flex items-center justify-center w-6 h-6 rounded-md text-muted-foreground hover:text-foreground hover:bg-muted transition-colors"
      >
        {moving || settingRecurring ? (
          <Loader2 className="w-3 h-3 animate-spin" />
        ) : (
          <MoreHorizontal className="w-3.5 h-3.5" />
        )}
      </button>
      {open && (
        <div
          className={cn(
            "absolute right-0 z-50 w-48 rounded-lg border bg-background shadow-lg text-sm py-1",
            dropUp ? "bottom-full mb-1" : "top-full mt-1",
          )}
        >
          {/* Recurring section — not shown for auto-generated instances */}
          {!isInstance && (
            <>
              <p className="px-3 pt-1 pb-1.5 text-xs font-medium text-muted-foreground uppercase tracking-wide">
                Recurring
              </p>
              {isTemplate ? (
                <button
                  onClick={() => void removeRecurring()}
                  className="w-full text-left px-3 py-1.5 hover:bg-muted transition-colors text-destructive/80"
                >
                  Remove recurrence
                </button>
              ) : recurringPicker ? (
                <>
                  <button
                    onClick={() => void setRecurring("monthly")}
                    className="w-full text-left px-3 py-1.5 hover:bg-muted transition-colors"
                  >
                    Every month
                  </button>
                  <button
                    onClick={() => void setRecurring("bi_weekly")}
                    className="w-full text-left px-3 py-1.5 hover:bg-muted transition-colors"
                  >
                    Every two weeks
                  </button>
                  <button
                    onClick={() => void setRecurring("semi_monthly")}
                    className="w-full text-left px-3 py-1.5 hover:bg-muted transition-colors"
                  >
                    Twice a month
                  </button>
                  <button
                    onClick={() => void setRecurring("weekly")}
                    className="w-full text-left px-3 py-1.5 hover:bg-muted transition-colors"
                  >
                    Every week
                  </button>
                  <button
                    onClick={() => setRecurringPicker(false)}
                    className="w-full text-left px-3 py-1.5 hover:bg-muted transition-colors text-muted-foreground text-xs"
                  >
                    ← Cancel
                  </button>
                </>
              ) : (
                <button
                  onClick={() => setRecurringPicker(true)}
                  className="w-full text-left px-3 py-1.5 hover:bg-muted transition-colors"
                >
                  Set as recurring…
                </button>
              )}
            </>
          )}
          {/* Profile section */}
          {profiles.length > 1 && (
            <>
              <p
                className={cn(
                  "px-3 pb-1.5 text-xs font-medium text-muted-foreground uppercase tracking-wide",
                  !isInstance ? "pt-2 mt-1 border-t" : "pt-1",
                )}
              >
                Move to profile
              </p>
              {profiles.map((profile) => (
                <button
                  key={profile.id}
                  onClick={() => void moveTo(profile.id)}
                  disabled={profile.id === currentProfileId}
                  className={cn(
                    "w-full text-left px-3 py-1.5 hover:bg-muted transition-colors text-sm",
                    profile.id === currentProfileId &&
                      "opacity-40 cursor-not-allowed",
                  )}
                >
                  {profile.name}
                </button>
              ))}
            </>
          )}
        </div>
      )}
    </div>
  );
}

// ── Actions menu ──────────────────────────────────────────────────────────────

function ActionsMenu({
  onImport,
  onExport,
  onCategories,
  onAutoCategorize,
  onDeleteAll,
  onDeleteAccount,
  onConnectBank,
  exporting,
  autoCategorizing,
  tellerEnabled,
  selectedAccountName,
}: {
  onImport: () => void;
  onExport: () => void;
  onCategories: () => void;
  onAutoCategorize: () => void;
  onDeleteAll: () => void;
  onDeleteAccount: () => void;
  onConnectBank: () => void;
  exporting: boolean;
  autoCategorizing: boolean;
  tellerEnabled: boolean;
  selectedAccountName: string | null;
}) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const h = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node))
        setOpen(false);
    };
    document.addEventListener("mousedown", h);
    return () => document.removeEventListener("mousedown", h);
  }, [open]);

  const item = (
    label: string,
    icon: React.ReactNode,
    action: () => void,
    danger = false,
    disabled = false,
  ) => (
    <button
      type="button"
      onClick={() => {
        if (!disabled) {
          action();
          setOpen(false);
        }
      }}
      disabled={disabled}
      className={cn(
        "flex items-center gap-2.5 w-full px-3 py-2 text-sm text-left transition-colors",
        danger ? "text-destructive hover:bg-destructive/10" : "hover:bg-muted",
        disabled && "opacity-40 cursor-not-allowed",
      )}
    >
      {icon}
      {label}
    </button>
  );

  return (
    <div ref={ref} className="relative">
      <Button
        variant="ghost"
        size="sm"
        className="h-8 w-8 p-0"
        onClick={() => setOpen((v) => !v)}
      >
        <MoreHorizontal className="w-4 h-4" />
      </Button>
      {open && (
        <>
          <div className="fixed inset-0 z-10" onClick={() => setOpen(false)} />
          <div className="absolute right-0 top-full mt-1 z-20 bg-background border rounded-lg shadow-lg py-1 min-w-[200px]">
            {item(
              "Import transactions",
              <Upload className="w-3.5 h-3.5 shrink-0 text-muted-foreground" />,
              onImport,
            )}
            {item(
              exporting ? "Exporting…" : "Export CSV",
              exporting ? (
                <Loader2 className="w-3.5 h-3.5 shrink-0 animate-spin text-muted-foreground" />
              ) : (
                <Download className="w-3.5 h-3.5 shrink-0 text-muted-foreground" />
              ),
              onExport,
              false,
              exporting,
            )}
            {item(
              "Manage categories",
              <Settings2 className="w-3.5 h-3.5 shrink-0 text-muted-foreground" />,
              onCategories,
            )}
            {item(
              autoCategorizing ? "Categorizing…" : "Auto-categorize",
              autoCategorizing ? (
                <Loader2 className="w-3.5 h-3.5 shrink-0 animate-spin text-muted-foreground" />
              ) : (
                <Wand2 className="w-3.5 h-3.5 shrink-0 text-muted-foreground" />
              ),
              onAutoCategorize,
              false,
              autoCategorizing,
            )}
            {tellerEnabled &&
              item(
                "Connect bank",
                <ArrowLeftRight className="w-3.5 h-3.5 shrink-0 text-muted-foreground" />,
                onConnectBank,
              )}
            <div className="border-t my-1" />
            {selectedAccountName &&
              item(
                "Delete account",
                <Trash2 className="w-3.5 h-3.5 shrink-0" />,
                onDeleteAccount,
                true,
              )}
            {item(
              "Delete all transactions",
              <Trash2 className="w-3.5 h-3.5 shrink-0" />,
              onDeleteAll,
              true,
            )}
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

  // Profile selection (persisted in localStorage)
  const [selectedProfileId, setSelectedProfileId] = useState<string | null>(
    () => {
      if (typeof window === "undefined") return null;
      return localStorage.getItem(PROFILE_STORAGE_KEY) ?? null;
    },
  );

  // Account filter
  const [selectedAccount, setSelectedAccount] = useState<string | null>(null);

  // Analytics month picker
  const today = new Date();
  const [anaYear, setAnaYear] = useState(today.getFullYear());
  const [anaMonth, setAnaMonth] = useState(today.getMonth() + 1);

  // Summary date preset — persisted in localStorage so it survives navigation + app restarts
  const [preset, setPreset] = useState<SummaryPreset>(() => {
    if (typeof window === "undefined") return "mtd";
    try {
      return (
        (localStorage.getItem(`${PRESET_STORAGE_KEY}`) as SummaryPreset) ??
        "mtd"
      );
    } catch {
      return "mtd";
    }
  });
  const [customFrom, setCustomFrom] = useState(() => {
    if (typeof window !== "undefined") {
      try {
        const s = localStorage.getItem(`${PRESET_STORAGE_KEY}-from`);
        if (s) return s;
      } catch {}
    }
    const d = new Date(today);
    d.setDate(1);
    return toISO(d);
  });
  const [customTo, setCustomTo] = useState(() => {
    if (typeof window !== "undefined") {
      try {
        const s = localStorage.getItem(`${PRESET_STORAGE_KEY}-to`);
        if (s) return s;
      } catch {}
    }
    return toISO(today);
  });

  // Transactions
  const [txnOffset, setTxnOffset] = useState(0);
  const [txnSearch, setTxnSearch] = useState("");
  const [txnFilter, setTxnFilter] = useState<TxnFilter>(null);
  const [txnFilterOpen, setTxnFilterOpen] = useState(false);
  const [txnFilterSearch, setTxnFilterSearch] = useState("");
  const [catOverrides, setCatOverrides] = useState<
    Record<string, string | null>
  >({});
  const [transferOverrides, setTransferOverrides] = useState<
    Record<string, boolean>
  >({});

  // Ref + outside-click handler for the transaction filter combobox.
  // Must live at component level (Rules of Hooks — can't be inside an IIFE).
  const txnFilterRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!txnFilterOpen) return;
    const handler = (e: MouseEvent) => {
      if (
        txnFilterRef.current &&
        !txnFilterRef.current.contains(e.target as Node)
      ) {
        setTxnFilterOpen(false);
        setTxnFilterSearch("");
      }
    };
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, [txnFilterOpen]);

  // Analytics view toggle — persisted to localStorage so it survives navigation
  const VALID_CHART_VIEWS = ["pie", "envelope", "trends", "plan"] as const;
  type ChartView = (typeof VALID_CHART_VIEWS)[number];
  const [chartView, setChartView] = useState<ChartView>(() => {
    try {
      const saved = localStorage.getItem("hearth-budget-chart-view");
      if (saved && (VALID_CHART_VIEWS as readonly string[]).includes(saved))
        return saved as ChartView;
    } catch {
      /* SSR / private browsing */
    }
    return "pie";
  });
  useEffect(() => {
    try {
      localStorage.setItem("hearth-budget-chart-view", chartView);
    } catch {
      /* ignore */
    }
  }, [chartView]);

  // Actions state
  const [exporting, setExporting] = useState(false);
  const [autoCategorizing, setAutoCategorizing] = useState(false);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [confirmDeleteAccount, setConfirmDeleteAccount] = useState(false);
  const [deletingAccount, setDeletingAccount] = useState(false);
  const [connectingBank, setConnectingBank] = useState(false);

  // ── Queries ──────────────────────────────────────────────────────────────────

  const { data: accounts, isLoading: accountsLoading } = useQuery({
    queryKey: ["budget", "accounts"],
    queryFn: fetchAccounts,
  });
  const { data: tellerConfig } = useQuery({
    queryKey: ["budget", "teller", "config"],
    queryFn: fetchTellerConfig,
    staleTime: 60_000 * 10, // config rarely changes; cache for 10 min
  });
  const { data: profiles = [] } = useQuery({
    queryKey: ["budget", "profiles"],
    queryFn: fetchProfiles,
  });
  const { data: categories = [] } = useQuery({
    queryKey: ["budget", "categories", selectedProfileId],
    queryFn: () => fetchCategories(selectedProfileId),
  });
  const { data: groupedCategories = [] } = useQuery({
    queryKey: ["budget", "categories", "grouped", selectedProfileId],
    queryFn: () => fetchGroupedCategories(selectedProfileId),
  });

  // Resolve effective profile (fall back to first if stored ID not in list yet)
  const selectedProfile =
    profiles.find((p) => p.id === selectedProfileId) ?? profiles[0] ?? null;
  const effectiveProfileId = selectedProfile?.id ?? null;
  const isProfitTracking =
    selectedProfile?.budgeting_style === "profit_tracking";

  // Persist profile selection
  useEffect(() => {
    if (effectiveProfileId)
      localStorage.setItem(PROFILE_STORAGE_KEY, effectiveProfileId);
  }, [effectiveProfileId]);

  // Auto-select first profile on initial load
  useEffect(() => {
    if (profiles.length > 0 && !selectedProfileId) {
      setSelectedProfileId(profiles[0].id);
    }
  }, [profiles, selectedProfileId]);

  // Persist date preset to localStorage
  useEffect(() => {
    try {
      localStorage.setItem(PRESET_STORAGE_KEY, preset);
    } catch {}
  }, [preset]);
  useEffect(() => {
    try {
      localStorage.setItem(`${PRESET_STORAGE_KEY}-from`, customFrom);
      localStorage.setItem(`${PRESET_STORAGE_KEY}-to`, customTo);
    } catch {}
  }, [customFrom, customTo]);

  const { data: profitAnalytics, isLoading: profitAnaLoading } = useQuery({
    queryKey: [
      "budget",
      "analytics",
      "profit",
      anaYear,
      anaMonth,
      effectiveProfileId,
    ],
    queryFn: () => fetchProfitAnalytics(effectiveProfileId!, anaYear, anaMonth),
    enabled:
      !!accounts &&
      accounts.length > 0 &&
      isProfitTracking &&
      !!effectiveProfileId,
  });

  const { data: trendsData, isLoading: trendsLoading } = useQuery({
    queryKey: ["budget", "trends", effectiveProfileId, selectedAccount],
    queryFn: () => fetchTrends(effectiveProfileId, selectedAccount),
    enabled: !!accounts && accounts.length > 0 && chartView === "trends",
    staleTime: 5 * 60 * 1000,
  });

  // Compute effective date range from the selected preset
  const effectiveRange = presetRange(preset, customFrom, customTo);

  // Derive analytics year/month from preset:
  //"mtd"→ current calendar month (budget targets apply)
  //"last_month"→ previous calendar month (budget targets apply)
  //"ytd"/"custom"→ pass date_from/date_to instead (no budget targets)
  const lastMonthDate = new Date(today.getFullYear(), today.getMonth() - 1, 1);
  const effectiveAnaYear =
    preset === "last_month"
      ? lastMonthDate.getFullYear()
      : preset === "mtd"
        ? today.getFullYear()
        : anaYear;
  const effectiveAnaMonth =
    preset === "last_month"
      ? lastMonthDate.getMonth() + 1
      : preset === "mtd"
        ? today.getMonth() + 1
        : anaMonth;
  const useYearMonth = preset === "mtd" || preset === "last_month";
  const anaDateFrom = useYearMonth ? undefined : effectiveRange.from;
  const anaDateTo = useYearMonth ? undefined : effectiveRange.to;

  const { data: analytics, isLoading: anaLoading } = useQuery({
    queryKey: [
      "budget",
      "analytics",
      effectiveAnaYear,
      effectiveAnaMonth,
      selectedAccount,
      effectiveProfileId,
      anaDateFrom,
      anaDateTo,
    ],
    queryFn: () =>
      fetchAnalytics(
        effectiveAnaYear,
        effectiveAnaMonth,
        selectedAccount,
        effectiveProfileId,
        anaDateFrom,
        anaDateTo,
      ),
    enabled: !!accounts && accounts.length > 0 && !isProfitTracking,
  });

  const { data: forecastData, isLoading: forecastLoading } = useQuery({
    queryKey: [
      "budget",
      "forecast",
      effectiveProfileId,
      effectiveAnaYear,
      effectiveAnaMonth,
    ],
    queryFn: () =>
      fetchIncomeForecast(
        effectiveAnaYear,
        effectiveAnaMonth,
        effectiveProfileId,
      ),
    enabled:
      !!accounts &&
      accounts.length > 0 &&
      chartView === "plan" &&
      !isProfitTracking,
    staleTime: 2 * 60 * 1000,
  });

  const { data: summary, isLoading: summaryLoading } = useQuery({
    queryKey: [
      "budget",
      "summary",
      selectedAccount,
      effectiveRange.from,
      effectiveRange.to,
      preset,
      effectiveProfileId,
    ],
    queryFn: () =>
      fetchSummary(
        selectedAccount,
        effectiveRange.from,
        effectiveRange.to,
        effectiveProfileId,
      ),
    enabled: !!accounts && accounts.length > 0,
  });

  const { data: txnData, isLoading: txnsLoading } = useQuery({
    queryKey: [
      "budget",
      "transactions",
      selectedAccount,
      txnOffset,
      effectiveProfileId,
      txnSearch,
      txnFilter,
      effectiveRange.from,
      effectiveRange.to,
    ],
    queryFn: () =>
      fetchTransactions(
        selectedAccount,
        txnOffset,
        effectiveProfileId,
        txnSearch,
        txnFilter,
        effectiveRange.from,
        effectiveRange.to,
      ),
    enabled: !!accounts && accounts.length > 0,
  });

  useEffect(() => {
    setCatOverrides({});
    setTransferOverrides({});
  }, [txnData]);

  // Reset transaction offset when profile, filters, or date range changes
  useEffect(() => {
    setTxnOffset(0);
  }, [
    effectiveProfileId,
    txnSearch,
    txnFilter,
    effectiveRange.from,
    effectiveRange.to,
  ]);

  // Auto-compute rollover when navigating to a new month.
  // Fire-and-forget: if there are no rollover-enabled categories the endpoint
  // returns quickly with categories_updated=0. On success invalidate analytics
  // so the envelope view picks up the fresh carry-forward amounts.
  useEffect(() => {
    if (!accounts || accounts.length === 0 || isProfitTracking) return;
    const p = new URLSearchParams({
      year: String(anaYear),
      month: String(anaMonth),
    });
    if (effectiveProfileId) p.set("profile_id", effectiveProfileId);
    void mutate("POST", `/budget/rollover?${p}`)
      .then(() => qc.invalidateQueries({ queryKey: ["budget", "analytics"] }))
      .catch(() => {
        /* silent — rollover is best-effort */
      });
  }, [anaYear, anaMonth, accounts, effectiveProfileId, isProfitTracking]); // eslint-disable-line react-hooks/exhaustive-deps

  // Auto-generate recurring-transaction instances for the current month.
  // Idempotent — safe to fire on every month/profile change.
  useEffect(() => {
    if (!accounts || accounts.length === 0) return;
    const p = new URLSearchParams({
      year: String(anaYear),
      month: String(anaMonth),
    });
    void mutate<{ generated: number }>(
      "POST",
      `/budget/recurring/generate?${p}`,
    )
      .then((res) => {
        if (res.generated > 0)
          void qc.invalidateQueries({ queryKey: ["budget", "transactions"] });
      })
      .catch(() => {
        /* silent — recurring generation is best-effort */
      });
  }, [anaYear, anaMonth, accounts]); // eslint-disable-line react-hooks/exhaustive-deps

  // ── Month navigation ──────────────────────────────────────────────────────────

  const isCurrentMonth =
    anaYear === today.getFullYear() && anaMonth === today.getMonth() + 1;

  const prevMonth = () => {
    if (anaMonth === 1) {
      setAnaMonth(12);
      setAnaYear((y) => y - 1);
    } else setAnaMonth((m) => m - 1);
  };

  const nextMonth = () => {
    if (isCurrentMonth) return;
    if (anaMonth === 12) {
      setAnaMonth(1);
      setAnaYear((y) => y + 1);
    } else setAnaMonth((m) => m + 1);
  };

  // ── Actions ───────────────────────────────────────────────────────────────────

  const handleExport = async () => {
    setExporting(true);
    try {
      const p = new URLSearchParams();
      if (selectedAccount) p.set("account_id", selectedAccount);
      const res = await fetchWithAuth(
        `${apiBaseUrl}/budget/transactions/export?${p}`,
      );
      if (!res.ok) throw new Error("Export failed");
      const blob = await res.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      const match = res.headers
        .get("Content-Disposition")
        ?.match(/filename="([^"]+)"/);
      a.download = match?.[1] ?? "hearth-budget.csv";
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      URL.revokeObjectURL(url);
    } finally {
      setExporting(false);
    }
  };

  const handleAutoCategorize = async () => {
    setAutoCategorizing(true);
    try {
      const p = new URLSearchParams();
      if (selectedAccount) p.set("account_id", selectedAccount);
      await mutate(
        "POST",
        `/budget/auto-categorize${p.toString() ? `?${p}` : ""}`,
      );
      await qc.invalidateQueries({ queryKey: ["budget"] });
    } finally {
      setAutoCategorizing(false);
    }
  };

  const handleDeleteAll = async () => {
    setDeleting(true);
    try {
      const p = selectedAccount ? `?account_id=${selectedAccount}` : "";
      await mutate("DELETE", `/budget/transactions${p}`);
      await qc.invalidateQueries({ queryKey: ["budget"] });
      setTxnOffset(0);
    } finally {
      setDeleting(false);
      setConfirmDelete(false);
    }
  };

  const handleDeleteAccount = async () => {
    if (!effectiveDeleteAccountId) return;
    setDeletingAccount(true);
    try {
      await fetchWithAuth(
        `${apiBaseUrl}/budget/accounts/${effectiveDeleteAccountId}`,
        { method: "DELETE" },
      );
      setSelectedAccount(null);
      await qc.invalidateQueries({ queryKey: ["budget", "accounts"] });
      await qc.invalidateQueries({ queryKey: ["budget"] });
    } finally {
      setDeletingAccount(false);
      setConfirmDeleteAccount(false);
    }
  };

  // ── Teller Connect ────────────────────────────────────────────────────────────

  const handleConnectBank = () => {
    if (!tellerConfig?.enabled || !tellerConfig.app_id) return;
    setConnectingBank(true);

    const proceed = () => {
      const connect = window.TellerConnect?.setup({
        applicationId: tellerConfig.app_id!,
        environment: tellerConfig.environment ?? "sandbox",
        products: ["transactions"],
        onSuccess: async (enrollment) => {
          try {
            await fetchWithAuth(`${apiBaseUrl}/budget/teller/connect`, {
              method: "POST",
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify({
                access_token: enrollment.accessToken,
                enrollment_id: enrollment.enrollment.id,
                institution_name: enrollment.enrollment.institution.name,
              }),
            });
            await qc.invalidateQueries({ queryKey: ["budget", "accounts"] });
          } finally {
            setConnectingBank(false);
          }
        },
        onExit: () => setConnectingBank(false),
        onFailure: () => setConnectingBank(false),
      });
      connect?.open();
    };

    // Lazy-load the Teller Connect script if not already present
    if (window.TellerConnect) {
      proceed();
    } else {
      const script = document.createElement("script");
      script.src = "https://cdn.teller.io/connect/connect.js";
      script.onload = proceed;
      script.onerror = () => setConnectingBank(false);
      document.head.appendChild(script);
    }
  };

  const handleCategoryAssigned = useCallback(
    (txnId: string, catId: string | null) => {
      setCatOverrides((prev) => ({ ...prev, [txnId]: catId }));
      void qc.invalidateQueries({ queryKey: ["budget", "analytics"] });
      void qc.invalidateQueries({ queryKey: ["budget", "summary"] });
    },
    [qc],
  );

  const handleTransferToggled = useCallback(
    (txnId: string, isTransfer: boolean) => {
      setTransferOverrides((prev) => ({ ...prev, [txnId]: isTransfer }));
      // Transfer flag changes what's included in aggregates, so refresh both
      void qc.invalidateQueries({ queryKey: ["budget", "analytics"] });
      void qc.invalidateQueries({ queryKey: ["budget", "summary"] });
    },
    [qc],
  );

  const handleCategoryClick = useCallback(
    (categoryId: string | null) => {
      const qp = new URLSearchParams({
        year: String(effectiveAnaYear),
        month: String(effectiveAnaMonth),
        date_from: effectiveRange.from,
        date_to: effectiveRange.to,
        preset,
      });
      if (selectedProfile) qp.set("profile_id", selectedProfile.id);
      const base = categoryId
        ? `/budget/categories/${categoryId}`
        : "/budget/categories/uncategorized";
      router.push(`${base}?${qp}`);
    },
    [
      router,
      effectiveAnaYear,
      effectiveAnaMonth,
      effectiveRange.from,
      effectiveRange.to,
      preset,
      selectedProfile,
    ],
  );

  const handleTxnMoved = useCallback(
    (_txnId: string, _profileId: string | null) => {
      // After moving, refresh the transaction list and analytics so the item disappears
      void qc.invalidateQueries({ queryKey: ["budget", "transactions"] });
      void qc.invalidateQueries({ queryKey: ["budget", "analytics"] });
    },
    [qc],
  );

  // Transaction edit sheet
  const [editingTxn, setEditingTxn] = useState<BudgetTransaction | null>(null);

  const handleTxnSaved = useCallback(
    (_txnId: string) => {
      setEditingTxn(null);
      void qc.invalidateQueries({ queryKey: ["budget", "transactions"] });
      void qc.invalidateQueries({ queryKey: ["budget", "analytics"] });
      void qc.invalidateQueries({ queryKey: ["budget", "summary"] });
    },
    [qc],
  );

  const handleTxnDeleted = useCallback(
    (_txnId: string) => {
      setEditingTxn(null);
      void qc.invalidateQueries({ queryKey: ["budget", "transactions"] });
      void qc.invalidateQueries({ queryKey: ["budget", "analytics"] });
      void qc.invalidateQueries({ queryKey: ["budget", "summary"] });
    },
    [qc],
  );

  // Inline budget target set from envelope row — refresh analytics so progress bars update.
  const handleBudgetSet = useCallback(
    (_categoryId: string, _amount: number | null) => {
      void qc.invalidateQueries({ queryKey: ["budget", "analytics"] });
      void qc.invalidateQueries({ queryKey: ["budget", "categories"] });
    },
    [qc],
  );

  // Auto-fill Fixed Monthly targets from spending history.
  const [autoFilling, setAutoFilling] = useState(false);
  const [autoFillResult, setAutoFillResult] = useState<string | null>(null);
  const handleAutoFill = async () => {
    setAutoFilling(true);
    setAutoFillResult(null);
    try {
      const p = new URLSearchParams({ months: "3" });
      if (selectedProfile) p.set("profile_id", selectedProfile.id);
      const updated = await mutate<
        Array<{ name: string; new_amount: number; months_sampled: number }>
      >("POST", `/budget/categories/auto-budget?${p}`);
      if (updated.length === 0) {
        setAutoFillResult(
          "No Fixed Monthly transactions found in the last 3 months.",
        );
      } else {
        setAutoFillResult(
          `Updated ${updated.length} categor${updated.length === 1 ? "y" : "ies"} from 3-month averages.`,
        );
        void qc.invalidateQueries({ queryKey: ["budget", "analytics"] });
        void qc.invalidateQueries({ queryKey: ["budget", "categories"] });
      }
    } catch {
      setAutoFillResult(
        "Auto-fill failed — check that you have transactions in Fixed Monthly categories.",
      );
    } finally {
      setAutoFilling(false);
      setTimeout(() => setAutoFillResult(null), 5000);
    }
  };

  // ── Derived ───────────────────────────────────────────────────────────────────

  const transactions = txnData?.items ?? [];
  const txnTotal = txnData?.total ?? 0;
  const txnPages = Math.ceil(txnTotal / TXN_PAGE_SIZE);
  const txnPage = Math.floor(txnOffset / TXN_PAGE_SIZE) + 1;
  const currency =
    selectedProfile?.currency ?? transactions[0]?.currency ?? "USD";

  // For zero-based profiles use analytics; for P&L use profitAnalytics
  const activeAnaLoading = isProfitTracking ? profitAnaLoading : anaLoading;
  const activeCategoryData = isProfitTracking
    ? (profitAnalytics?.by_category ?? [])
    : (analytics?.by_category ?? []);

  const expenseEntries = activeCategoryData
    .filter((e) => e.total_expenses > 0)
    .sort((a, b) => b.total_expenses - a.total_expenses);
  const maxExpense =
    expenseEntries.length > 0
      ? Math.max(...expenseEntries.map((e) => e.total_expenses))
      : 0;
  const totalExpenses = isProfitTracking
    ? (profitAnalytics?.total_expenses ?? 0)
    : (analytics?.total_expenses ?? 0);
  const totalBudgeted = analytics?.total_budgeted ?? 0;
  const totalTargets = analytics?.total_targets ?? 0;
  // True when at least one expense category for this month has a budget target
  const hasBudgetTargets = expenseEntries.some((e) => e.budgeted != null);
  // True when any categories have targets set (even if no spending yet this month)
  const hasAnyTargets = totalTargets > 0;
  // Ready to assign = income this month minus all category targets (zero-based only)
  const readyToAssign = (analytics?.total_income ?? 0) - totalTargets;

  // Profit tracking metrics
  const netProfit = profitAnalytics?.net_profit ?? 0;
  const mrrActual = profitAnalytics?.mrr_actual ?? 0;
  const arrProjected = profitAnalytics?.arr_projected ?? 0;
  const mrrGrowthPct = profitAnalytics?.mrr_growth_pct ?? null;

  const hasAccounts = accounts && accounts.length > 0;

  // When there's only one account the selector renders as a plain label (no
  // dropdown), so selectedAccount stays null — fall back to the sole account
  // so delete-account still works in that case.
  const effectiveDeleteAccountId =
    selectedAccount ?? (accounts?.length === 1 ? accounts[0].id : null);
  const effectiveDeleteAccountName =
    accounts?.find((a) => a.id === effectiveDeleteAccountId)?.name ?? null;

  // Use analytics.total_expenses for"Spent"— it nets refunds per-category (clamped at 0)
  // which is more accurate than the summary endpoint's single-pass aggregation.
  const summaryExpenses = isProfitTracking
    ? (profitAnalytics?.total_expenses ?? summary?.total_expenses ?? 0)
    : (analytics?.total_expenses ?? summary?.total_expenses ?? 0);
  const summaryIncome = summary?.total_income ?? 0;
  const summaryNet = summaryIncome - summaryExpenses;
  const summaryLoaded = !summaryLoading;

  // ── Empty state ───────────────────────────────────────────────────────────────

  if (!accountsLoading && !hasAccounts) {
    return (
      <div className="flex flex-col items-center justify-center min-h-[60vh] gap-4 text-center px-4">
        <div className="rounded-full bg-muted p-4">
          <Upload className="w-8 h-8 text-muted-foreground" />
        </div>
        <div>
          <h1 className="text-xl font-semibold mb-1">Budget</h1>
          <p className="text-muted-foreground text-sm max-w-sm">
            Connect your bank or import statements to get started.
          </p>
        </div>
        <div className="flex gap-2 flex-wrap justify-center">
          {tellerConfig?.enabled && (
            <Button onClick={handleConnectBank} disabled={connectingBank}>
              {connectingBank ? (
                <Loader2 className="w-4 h-4 mr-2 animate-spin" />
              ) : (
                <ArrowLeftRight className="w-4 h-4 mr-2" />
              )}
              Connect bank
            </Button>
          )}
          <Button
            variant={tellerConfig?.enabled ? "outline" : "default"}
            onClick={() => router.push("/budget/import")}
          >
            Import transactions
          </Button>
        </div>
      </div>
    );
  }

  // ── Layout ────────────────────────────────────────────────────────────────────

  return (
    <div className="max-w-2xl mx-auto pt-6 pb-48 px-4 space-y-5">
      {/* ── Header row ── */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2.5 min-w-0">
          <h1 className="text-lg font-semibold shrink-0">Budget</h1>
          <ProfileSwitcher
            profiles={profiles}
            value={effectiveProfileId}
            onChange={(id) => {
              setSelectedProfileId(id);
              setTxnOffset(0);
            }}
          />
        </div>
        <ActionsMenu
          onImport={() => router.push("/budget/import")}
          onExport={() => void handleExport()}
          onCategories={() => router.push("/budget/categories")}
          onAutoCategorize={() => void handleAutoCategorize()}
          onDeleteAll={() => setConfirmDelete(true)}
          onDeleteAccount={() => setConfirmDeleteAccount(true)}
          onConnectBank={handleConnectBank}
          exporting={exporting}
          autoCategorizing={autoCategorizing}
          tellerEnabled={tellerConfig?.enabled ?? false}
          selectedAccountName={effectiveDeleteAccountName}
        />
      </div>

      {/* ── Account + month row ── */}
      <div className="flex items-center justify-between gap-3">
        <AccountDropdown
          accounts={accounts}
          value={selectedAccount}
          onChange={(v) => {
            setSelectedAccount(v);
            setTxnOffset(0);
          }}
        />
        <div className="flex items-center gap-2">
          <button
            onClick={prevMonth}
            className="p-1 rounded-full bg-muted text-muted-foreground hover:text-foreground transition-colors"
          >
            <ChevronLeft className="w-4 h-4" />
          </button>
          <span className="text-sm font-medium min-w-[9rem] text-center">
            {MONTH_NAMES[anaMonth - 1]} {anaYear}
          </span>
          <button
            onClick={nextMonth}
            disabled={isCurrentMonth}
            className={cn(
              "p-1 rounded-full bg-muted transition-colors",
              isCurrentMonth
                ? "text-muted-foreground/30"
                : "text-muted-foreground hover:text-foreground",
            )}
          >
            <ChevronRight className="w-4 h-4" />
          </button>
        </div>
      </div>

      {/* ── Account balance + Teller sync chips ── */}
      {selectedAccount &&
        (() => {
          const acc = accounts?.find((a) => a.id === selectedAccount);
          if (!acc) return null;
          return (
            <div className="flex items-center gap-4 flex-wrap">
              <AccountBalanceChip
                account={acc}
                onUpdated={() =>
                  qc.invalidateQueries({ queryKey: ["budget", "accounts"] })
                }
              />
              <TellerSyncChip
                account={acc}
                onSynced={() => {
                  void qc.invalidateQueries({
                    queryKey: ["budget", "accounts"],
                  });
                  void qc.invalidateQueries({
                    queryKey: ["budget", "transactions"],
                  });
                  void qc.invalidateQueries({
                    queryKey: ["budget", "analytics"],
                  });
                  void qc.invalidateQueries({
                    queryKey: ["budget", "summary"],
                  });
                }}
              />
            </div>
          );
        })()}

      {/* ── Net profit banner (P&L profiles) ── */}
      {isProfitTracking && !profitAnaLoading && profitAnalytics && (
        <div
          className={cn(
            "rounded-xl border px-5 py-4 flex items-center justify-between gap-4 transition-colors",
            netProfit >= 0
              ? "bg-budget-positive border-budget-positive"
              : "bg-budget-negative border-budget-negative",
          )}
        >
          <div>
            <p
              className={cn(
                "text-xs font-semibold uppercase tracking-wider mb-0.5",
                netProfit >= 0
                  ? "text-budget-positive"
                  : "text-budget-negative",
              )}
            >
              Net Profit
            </p>
            <p
              className={cn(
                "text-2xl font-bold tabular-nums",
                netProfit >= 0
                  ? "text-budget-positive"
                  : "text-budget-negative",
              )}
            >
              {netProfit < 0 ? "−" : "+"}
              {fmt(Math.abs(netProfit), currency)}
            </p>
          </div>
          <div className="text-right shrink-0 space-y-1">
            {mrrActual > 0 && (
              <div>
                <p className="text-xs text-muted-foreground">
                  MRR{""}
                  <span className="tabular-nums font-medium text-foreground">
                    {fmt(mrrActual, currency, true)}
                  </span>
                  {"·"}ARR{""}
                  <span className="tabular-nums font-medium text-foreground">
                    {fmt(arrProjected, currency, true)}
                  </span>
                </p>
                {mrrGrowthPct != null && (
                  <p
                    className={cn(
                      "text-xs tabular-nums",
                      mrrGrowthPct >= 0
                        ? "text-budget-positive"
                        : "text-budget-negative",
                    )}
                  >
                    {mrrGrowthPct >= 0 ? "+" : ""}
                    {mrrGrowthPct.toFixed(1)}% MoM
                  </p>
                )}
              </div>
            )}
            <p className="text-xs text-muted-foreground/60">
              {fmt(profitAnalytics.total_revenue, currency)} revenue −{""}
              {fmt(profitAnalytics.total_expenses, currency)} expenses
            </p>
          </div>
        </div>
      )}

      {/* ── Ready to assign ── */}
      {!isProfitTracking &&
        hasAnyTargets &&
        !anaLoading &&
        chartView !== "trends" &&
        chartView !== "plan" && (
          <div
            className={cn(
              "rounded-xl border px-5 py-3.5 flex items-center justify-between gap-4 transition-colors",
              readyToAssign > 0.005
                ? "bg-sky-50 border-sky-200 dark:bg-sky-950/30 dark:border-sky-800"
                : readyToAssign < -0.005
                  ? "bg-budget-negative border-budget-negative"
                  : "bg-budget-positive border-budget-positive",
            )}
          >
            {/* Left: label + amount + breakdown */}
            <div className="min-w-0">
              <p
                className={cn(
                  "text-[10px] font-semibold uppercase tracking-widest mb-0.5",
                  readyToAssign > 0.005
                    ? "text-sky-500 dark:text-sky-400"
                    : readyToAssign < -0.005
                      ? "text-budget-negative"
                      : "text-budget-positive",
                )}
              >
                Ready to assign
              </p>
              <p
                className={cn(
                  "text-2xl font-bold tabular-nums leading-tight",
                  readyToAssign > 0.005
                    ? "text-sky-700 dark:text-sky-300"
                    : readyToAssign < -0.005
                      ? "text-budget-negative"
                      : "text-budget-positive",
                )}
              >
                {readyToAssign < 0 ? "−" : ""}
                {fmt(Math.abs(readyToAssign), currency)}
              </p>
              <p className="text-xs text-muted-foreground/70 mt-1 tabular-nums">
                {fmt(analytics?.total_income ?? 0, currency)} income
                <span className="mx-1 opacity-50">−</span>
                {fmt(totalTargets, currency)} budgeted
              </p>
            </div>

            {/* Right: state message + CTA */}
            <div className="shrink-0 text-right">
              {readyToAssign > 0.005 ? (
                <>
                  <p className="text-xs text-muted-foreground mb-1.5">
                    {fmt(readyToAssign, currency)} left to assign
                  </p>
                  {chartView !== "envelope" && (
                    <button
                      onClick={() => setChartView("envelope")}
                      className="text-xs font-medium text-sky-600 dark:text-sky-400 hover:underline"
                    >
                      Assign in envelope view →
                    </button>
                  )}
                </>
              ) : readyToAssign < -0.005 ? (
                <p className="text-xs text-budget-negative-faint max-w-[130px]">
                  Over-allocated by {fmt(Math.abs(readyToAssign), currency)}
                </p>
              ) : (
                <p className="text-xs font-medium text-budget-positive">
                  Every dollar has a job ✓
                </p>
              )}
            </div>
          </div>
        )}

      {/* ── Summary presets + cards ── */}
      <section>
        {/* Preset pills */}
        <div className="flex items-center gap-1.5 mb-3 flex-wrap">
          {(["mtd", "last_month", "ytd", "custom"] as SummaryPreset[]).map(
            (p) => (
              <button
                key={p}
                onClick={() => setPreset(p)}
                className={cn(
                  "rounded-full px-3 py-0.5 text-xs font-medium transition-colors",
                  preset === p
                    ? "bg-primary text-primary-foreground"
                    : "bg-muted text-muted-foreground hover:text-foreground",
                )}
              >
                {p === "mtd"
                  ? "Month to date"
                  : p === "last_month"
                    ? "Last month"
                    : p === "ytd"
                      ? "Year to date"
                      : "Custom"}
              </button>
            ),
          )}
          {preset === "custom" && (
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

        {/* Summary cards */}
        <div className="grid grid-cols-3 gap-3">
          {[
            {
              key: "col1",
              label: isProfitTracking ? "Expenses" : "Spent",
              amount: summaryExpenses,
              color: "text-budget-negative",
              sign: "",
            },
            {
              key: "col2",
              label: isProfitTracking ? "Revenue" : "Income",
              amount: summaryIncome,
              color: "text-budget-positive",
              sign: "",
            },
            {
              key: "col3",
              label: isProfitTracking ? "Profit" : "Net",
              amount: summaryNet,
              color:
                summaryNet >= 0
                  ? "text-budget-positive"
                  : "text-budget-negative",
              sign: summaryNet >= 0 ? "+" : "−",
            },
          ].map(({ key, label, amount, color, sign }) => (
            <div key={key} className="rounded-lg border px-4 py-3">
              <p className="text-xs text-muted-foreground mb-1">{label}</p>
              {!summaryLoaded ? (
                <div className="h-5 w-20 bg-muted animate-pulse rounded" />
              ) : (
                <p className={cn("text-lg font-semibold", color)}>
                  {sign}
                  {fmt(Math.abs(amount), currency, true)}
                </p>
              )}
            </div>
          ))}
        </div>
      </section>

      {/* ── Spending breakdown ── */}
      <section>
        {/* Header row: title + view toggle */}
        <div className="flex items-center justify-between mb-3">
          <p className="text-xs font-semibold text-muted-foreground uppercase tracking-wider">
            {chartView === "trends"
              ? (isProfitTracking ? "P&L trends" : "Spending trends") +
                "· last 6 months"
              : chartView === "plan"
                ? `Income plan · ${MONTH_NAMES[effectiveAnaMonth - 1]} ${effectiveAnaYear}`
                : (() => {
                    const base = isProfitTracking
                      ? "P&L breakdown"
                      : "Spending breakdown";
                    const label =
                      preset === "mtd"
                        ? `${MONTH_NAMES[effectiveAnaMonth - 1]} ${effectiveAnaYear} (MTD)`
                        : preset === "last_month"
                          ? `${MONTH_NAMES[effectiveAnaMonth - 1]} ${effectiveAnaYear}`
                          : preset === "ytd"
                            ? `Jan – ${MONTH_NAMES[today.getMonth()]} ${today.getFullYear()}`
                            : `${fmtDate(customFrom)} – ${fmtDate(customTo)}`;
                    return `${base} · ${label}`;
                  })()}
          </p>
          <div className="flex items-center gap-0.5 rounded-md bg-muted p-0.5">
            <button
              onClick={() => setChartView("pie")}
              className={cn(
                "flex items-center justify-center w-6 h-6 rounded transition-colors",
                chartView === "pie"
                  ? "bg-background shadow-sm text-foreground"
                  : "text-muted-foreground hover:text-foreground",
              )}
              title="Pie chart"
            >
              <PieChartIcon className="w-3.5 h-3.5" />
            </button>
            {!isProfitTracking && (
              <button
                onClick={() => setChartView("envelope")}
                className={cn(
                  "flex items-center justify-center w-6 h-6 rounded transition-colors text-xs font-semibold",
                  chartView === "envelope"
                    ? "bg-background shadow-sm text-foreground"
                    : "text-muted-foreground hover:text-foreground",
                )}
                title="Envelope budget view"
              >
                %
              </button>
            )}
            <button
              onClick={() => setChartView("trends")}
              className={cn(
                "flex items-center justify-center w-6 h-6 rounded transition-colors",
                chartView === "trends"
                  ? "bg-background shadow-sm text-foreground"
                  : "text-muted-foreground hover:text-foreground",
              )}
              title="6-month trends"
            >
              <TrendingUp className="w-3.5 h-3.5" />
            </button>
            {!isProfitTracking && (
              <button
                onClick={() => setChartView("plan")}
                className={cn(
                  "flex items-center justify-center w-6 h-6 rounded transition-colors",
                  chartView === "plan"
                    ? "bg-background shadow-sm text-foreground"
                    : "text-muted-foreground hover:text-foreground",
                )}
                title="Income forecast & allocation plan"
              >
                <CalendarClock className="w-3.5 h-3.5" />
              </button>
            )}
          </div>
        </div>

        {/* Envelope view header — setup prompt when no targets, summary bar when targets exist */}
        {!activeAnaLoading &&
          !isProfitTracking &&
          chartView === "envelope" &&
          (!hasAnyTargets && categories.length > 0 ? (
            /* ── First-time setup prompt ── */
            <div className="rounded-lg border border-dashed border-sky-300 bg-sky-50 dark:bg-sky-950/30 dark:border-sky-800 px-4 py-3 mb-3 flex items-center justify-between gap-4">
              <div>
                <p className="text-sm font-medium text-sky-900 dark:text-sky-200">
                  Set up your envelope budgets
                </p>
                <p className="text-xs text-sky-700 dark:text-sky-400 mt-0.5">
                  Auto-fill uses your last 3 months of spending to suggest
                  targets for Fixed Monthly categories. You can fine-tune any
                  amount by clicking it.
                </p>
              </div>
              <button
                onClick={() => void handleAutoFill()}
                disabled={autoFilling}
                className="flex items-center gap-1.5 text-xs font-medium px-3 py-1.5 rounded-md bg-sky-600 hover:bg-sky-700 text-white transition-colors shrink-0 disabled:opacity-50"
              >
                {autoFilling ? (
                  <>
                    <Loader2 className="w-3 h-3 animate-spin" /> Filling…
                  </>
                ) : (
                  <>
                    <Wand2 className="w-3 h-3" /> Auto-fill Fixed Monthly
                  </>
                )}
              </button>
            </div>
          ) : (
            /* ── Budget vs spent summary line ── */
            <div className="flex items-center justify-between mb-2 px-1 gap-2">
              {totalBudgeted > 0 ? (
                <span className="text-xs text-muted-foreground">
                  {fmt(totalExpenses, currency)} spent of{""}
                  {fmt(totalBudgeted, currency)} budgeted
                </span>
              ) : (
                <span className="text-xs text-muted-foreground">
                  Click any <span className="font-medium">/ —</span> to set a
                  budget.
                </span>
              )}
              <div className="flex items-center gap-2 shrink-0">
                {autoFillResult && (
                  <span className="text-xs text-muted-foreground">
                    {autoFillResult}
                  </span>
                )}
                {totalBudgeted > 0 && (
                  <span
                    className={cn(
                      "text-xs font-medium tabular-nums",
                      totalExpenses > totalBudgeted
                        ? "text-budget-negative"
                        : "text-budget-positive",
                    )}
                  >
                    {totalExpenses > totalBudgeted
                      ? `${fmt(totalExpenses - totalBudgeted, currency)} over`
                      : `${fmt(totalBudgeted - totalExpenses, currency)} left`}
                  </span>
                )}
                <button
                  onClick={() => void handleAutoFill()}
                  disabled={autoFilling}
                  title="Set Fixed Monthly budgets from 3-month spending averages"
                  className="flex items-center gap-1 text-xs px-2 py-0.5 rounded-full border hover:bg-muted transition-colors text-muted-foreground disabled:opacity-50"
                >
                  {autoFilling ? (
                    <>
                      <Loader2 className="w-3 h-3 animate-spin" /> Filling…
                    </>
                  ) : (
                    <>
                      <Wand2 className="w-3 h-3" /> Auto-fill Fixed
                    </>
                  )}
                </button>
              </div>
            </div>
          ))}

        {chartView === "plan" ? (
          /* ── Income forecast & allocation plan ── */
          (() => {
            const forecast = forecastData;
            const leftToAllocate = forecast?.left_to_allocate ?? 0;
            const isOver = leftToAllocate < -0.005;
            const isZero = Math.abs(leftToAllocate) <= 0.005;

            return forecastLoading ? (
              <div className="flex items-center justify-center py-10 text-muted-foreground gap-2 text-sm">
                <Loader2 className="w-4 h-4 animate-spin" /> Loading forecast…
              </div>
            ) : (
              <div className="space-y-4">
                {/* ── Allocation status card ── */}
                <div
                  className={cn(
                    "rounded-xl border px-5 py-3.5 flex items-center justify-between gap-4 transition-colors",
                    isOver
                      ? "bg-budget-negative border-budget-negative"
                      : isZero
                        ? "bg-budget-positive border-budget-positive"
                        : "bg-sky-50 border-sky-200 dark:bg-sky-950/30 dark:border-sky-800",
                  )}
                >
                  <div className="min-w-0">
                    <p
                      className={cn(
                        "text-[10px] font-semibold uppercase tracking-widest mb-0.5",
                        isOver
                          ? "text-budget-negative"
                          : isZero
                            ? "text-budget-positive"
                            : "text-sky-500",
                      )}
                    >
                      {forecast?.is_future_month
                        ? "Left to allocate"
                        : "Planned vs actual"}
                    </p>
                    <p
                      className={cn(
                        "text-2xl font-bold tabular-nums leading-tight",
                        isOver
                          ? "text-budget-negative"
                          : isZero
                            ? "text-budget-positive"
                            : "text-sky-700 dark:text-sky-300",
                      )}
                    >
                      {isOver ? "−" : ""}
                      {fmt(Math.abs(leftToAllocate), currency)}
                    </p>
                    <p className="text-xs text-muted-foreground/70 mt-1 tabular-nums">
                      {fmt(forecast?.projected_income ?? 0, currency)} projected
                      <span className="mx-1 opacity-50">−</span>
                      {fmt(forecast?.total_targets ?? 0, currency)} budgeted
                    </p>
                  </div>
                  <div className="shrink-0 text-right space-y-1">
                    {isOver ? (
                      <p className="text-xs text-budget-negative-faint">
                        Over-allocated by{""}
                        {fmt(Math.abs(leftToAllocate), currency)}
                      </p>
                    ) : isZero ? (
                      <p className="text-xs font-medium text-budget-positive">
                        Every dollar has a job ✓
                      </p>
                    ) : (
                      <>
                        <p className="text-xs text-muted-foreground">
                          {fmt(leftToAllocate, currency)} left to assign
                        </p>
                        {chartView === "plan" && (
                          <button
                            onClick={() => setChartView("envelope")}
                            className="text-xs font-medium text-sky-600 dark:text-sky-400 hover:underline"
                          >
                            Assign in envelope view →
                          </button>
                        )}
                      </>
                    )}
                    {!forecast?.is_future_month &&
                      (forecast?.actual_income ?? 0) > 0 && (
                        <p className="text-xs text-muted-foreground/60 tabular-nums">
                          {fmt(forecast?.actual_income ?? 0, currency)} received
                          so far
                        </p>
                      )}
                  </div>
                </div>

                {/* ── Projected income sources ── */}
                {(forecast?.sources.length ?? 0) > 0 ? (
                  <div className="rounded-lg border divide-y">
                    <div className="px-4 py-2.5 flex items-center justify-between">
                      <p className="text-xs font-semibold text-muted-foreground uppercase tracking-wider">
                        Projected income · {forecast!.sources.length} source
                        {forecast!.sources.length !== 1 ? "s" : ""}
                      </p>
                      <p className="text-xs font-semibold tabular-nums text-budget-positive">
                        +{fmt(forecast?.projected_income ?? 0, currency)}
                      </p>
                    </div>
                    {forecast!.sources.map((s, i) => (
                      <div
                        key={`${s.template_id}-${i}`}
                        className="px-4 py-2.5 flex items-center justify-between gap-3"
                      >
                        <div className="min-w-0">
                          <p className="text-sm font-medium truncate">
                            {s.description}
                          </p>
                          <p className="text-xs text-muted-foreground">
                            {s.category_name ?? "Uncategorized"}
                            <span className="mx-1.5 opacity-40">·</span>
                            {new Date(
                              s.expected_date + "T00:00:00",
                            ).toLocaleDateString(undefined, {
                              month: "short",
                              day: "numeric",
                            })}
                          </p>
                        </div>
                        <p className="text-sm font-medium tabular-nums text-budget-positive shrink-0">
                          +{fmt(s.amount, currency)}
                        </p>
                      </div>
                    ))}
                  </div>
                ) : (
                  <div className="rounded-lg border border-dashed px-4 py-8 flex flex-col items-center gap-2 text-center">
                    <CalendarClock className="w-7 h-7 text-muted-foreground/40" />
                    <p className="text-sm text-muted-foreground">
                      No recurring income found for this month.
                    </p>
                    <p className="text-xs text-muted-foreground/70">
                      Mark an income transaction as recurring to project it
                      here.
                    </p>
                  </div>
                )}

                {/* ── Category targets for context ── */}
                {hasAnyTargets && (
                  <div>
                    <p className="text-xs font-semibold text-muted-foreground uppercase tracking-wider mb-2 px-1">
                      Budgeted ·{""}
                      {fmt(forecast?.total_targets ?? totalTargets, currency)}
                      {""}
                      total
                    </p>
                    <GroupedBreakdown
                      entries={expenseEntries}
                      groups={groupedCategories}
                      currency={currency}
                      onCategoryClick={handleCategoryClick}
                      onBudgetSet={handleBudgetSet}
                    />
                  </div>
                )}
              </div>
            );
          })()
        ) : chartView === "trends" ? (
          /* ── 6-month trends bar chart ── */
          <TrendsChart
            months={trendsData?.months ?? []}
            currency={currency}
            isLoading={trendsLoading}
          />
        ) : activeAnaLoading ? (
          <div className="flex items-center justify-center py-12 text-muted-foreground gap-2 text-sm">
            <Loader2 className="w-4 h-4 animate-spin" /> Loading…
          </div>
        ) : expenseEntries.length === 0 ? (
          <p className="text-sm text-muted-foreground text-center py-8">
            No {isProfitTracking ? "activity" : "expenses"} for{""}
            {MONTH_NAMES[anaMonth - 1]}.
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
        ) : chartView === "envelope" ? (
          /* ── Envelope view — budget vs actual per category, grouped ── */
          <GroupedBreakdown
            entries={expenseEntries}
            groups={groupedCategories}
            currency={currency}
            onCategoryClick={handleCategoryClick}
            onBudgetSet={handleBudgetSet}
          />
        ) : null}
      </section>

      {/* ── Delete confirmation modal ── */}
      {confirmDelete && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 backdrop-blur-[2px]">
          <div className="bg-background rounded-xl border shadow-xl px-6 py-5 max-w-sm w-full mx-4">
            <h2 className="text-base font-semibold mb-1.5">
              Delete all transactions?
            </h2>
            <p className="text-sm text-muted-foreground mb-5">
              This will permanently delete all{""}
              {selectedAccount
                ? "transactions for this account"
                : "budget transactions"}
              . This cannot be undone.
            </p>
            <div className="flex justify-end gap-2">
              <Button
                size="sm"
                variant="ghost"
                onClick={() => setConfirmDelete(false)}
                disabled={deleting}
              >
                Cancel
              </Button>
              <Button
                size="sm"
                variant="destructive"
                onClick={() => void handleDeleteAll()}
                disabled={deleting}
              >
                {deleting && <Loader2 className="w-3 h-3 animate-spin mr-1" />}
                Delete all
              </Button>
            </div>
          </div>
        </div>
      )}

      {/* ── Delete account confirmation modal ── */}
      {confirmDeleteAccount && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 backdrop-blur-[2px]">
          <div className="bg-background rounded-xl border shadow-xl px-6 py-5 max-w-sm w-full mx-4">
            <h2 className="text-base font-semibold mb-1.5">Delete account?</h2>
            <p className="text-sm text-muted-foreground mb-5">
              <span className="font-medium text-foreground">
                {effectiveDeleteAccountName}
              </span>
              {""}
              and all its transactions will be permanently deleted. This cannot
              be undone.
            </p>
            <div className="flex justify-end gap-2">
              <Button
                size="sm"
                variant="ghost"
                onClick={() => setConfirmDeleteAccount(false)}
                disabled={deletingAccount}
              >
                Cancel
              </Button>
              <Button
                size="sm"
                variant="destructive"
                onClick={() => void handleDeleteAccount()}
                disabled={deletingAccount}
              >
                {deletingAccount && (
                  <Loader2 className="w-3 h-3 animate-spin mr-1" />
                )}
                Delete account
              </Button>
            </div>
          </div>
        </div>
      )}

      {/* ── Recent transactions ── */}
      <section>
        <div className="flex items-center justify-between mb-2">
          <p className="text-xs font-semibold text-muted-foreground uppercase tracking-wider">
            Transactions
          </p>
          {txnTotal > 0 && (
            <span className="text-xs text-muted-foreground">
              {txnTotal} {txnSearch || txnFilter ? "matching" : "total"}
            </span>
          )}
        </div>

        {/* Search + filter row */}
        <div className="flex items-center gap-2 mb-3">
          <div className="relative flex-1">
            <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-muted-foreground pointer-events-none" />
            <input
              type="text"
              value={txnSearch}
              onChange={(e) => setTxnSearch(e.target.value)}
              placeholder="Search transactions…"
              className="w-full h-8 pl-8 pr-7 text-sm rounded-md border bg-background focus:outline-none focus:ring-1 focus:ring-ring"
            />
            {txnSearch && (
              <button
                onClick={() => setTxnSearch("")}
                className="absolute right-2 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground"
              >
                <X className="w-3.5 h-3.5" />
              </button>
            )}
          </div>
          {/* ── Transaction filter combobox ── */}
          {(() => {
            const activeLabel =
              txnFilter?.kind === "uncategorized"
                ? "Uncategorized"
                : txnFilter?.kind === "category"
                  ? txnFilter.name
                  : null;

            const q = txnFilterSearch.trim().toLowerCase();
            const showUncategorized = !q || "uncategorized".includes(q);
            const filteredCategories = (categories as BudgetCategory[]).filter(
              (c) => !q || c.name.toLowerCase().includes(q),
            );
            const hasResults =
              showUncategorized || filteredCategories.length > 0;

            const isUncategorizedActive = txnFilter?.kind === "uncategorized";
            const isCatActive = (id: string) =>
              txnFilter?.kind === "category" && txnFilter.id === id;

            const selectUncategorized = () => {
              setTxnFilter(
                isUncategorizedActive ? null : { kind: "uncategorized" },
              );
              setTxnFilterOpen(false);
              setTxnFilterSearch("");
            };
            const selectCat = (id: string, name: string) => {
              setTxnFilter(
                isCatActive(id) ? null : { kind: "category", id, name },
              );
              setTxnFilterOpen(false);
              setTxnFilterSearch("");
            };

            return (
              <div ref={txnFilterRef} className="relative shrink-0">
                <button
                  onClick={() => {
                    setTxnFilterOpen((v) => !v);
                    setTxnFilterSearch("");
                  }}
                  className={cn(
                    "h-8 px-2.5 text-xs rounded-md border transition-colors flex items-center gap-1.5",
                    txnFilter
                      ? "bg-primary text-primary-foreground border-primary"
                      : "bg-background text-muted-foreground hover:text-foreground hover:bg-muted",
                  )}
                >
                  <SlidersHorizontal className="w-3 h-3 shrink-0" />
                  {activeLabel ?? "Filter"}
                  {txnFilter && (
                    <span
                      role="button"
                      onClick={(e) => {
                        e.stopPropagation();
                        setTxnFilter(null);
                        setTxnFilterOpen(false);
                      }}
                      className="ml-0.5 rounded-full hover:bg-primary-foreground/20 p-0.5"
                    >
                      <X className="w-2.5 h-2.5" />
                    </span>
                  )}
                </button>

                {txnFilterOpen && (
                  <div className="absolute right-0 top-9 z-30 w-56 rounded-lg border bg-background shadow-lg overflow-hidden flex flex-col max-h-80">
                    {/* Search */}
                    <div className="flex items-center gap-2 border-b px-2.5 py-2 shrink-0">
                      <Search className="w-3 h-3 text-muted-foreground shrink-0" />
                      <input
                        autoFocus
                        value={txnFilterSearch}
                        onChange={(e) => setTxnFilterSearch(e.target.value)}
                        placeholder="Search filters…"
                        className="flex-1 text-xs bg-transparent outline-none placeholder:text-muted-foreground"
                      />
                    </div>

                    <div className="overflow-y-auto py-1">
                      {/* Uncategorized — top, visually separated */}
                      {showUncategorized && (
                        <>
                          <button
                            onClick={selectUncategorized}
                            className={cn(
                              "w-full flex items-center justify-between px-2.5 py-1.5 text-xs hover:bg-muted transition-colors text-left",
                              isUncategorizedActive && "bg-muted",
                            )}
                          >
                            <div>
                              <p className="font-medium">Uncategorized</p>
                              <p className="text-muted-foreground text-[10px]">
                                No category assigned
                              </p>
                            </div>
                            {isUncategorizedActive && (
                              <Check className="w-3 h-3 shrink-0 text-primary" />
                            )}
                          </button>
                          {filteredCategories.length > 0 && (
                            <div className="border-t my-1" />
                          )}
                        </>
                      )}

                      {/* Category filters */}
                      {filteredCategories.length > 0 && (
                        <>
                          {!q && (
                            <p className="px-2.5 pt-0.5 pb-1 text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">
                              Category
                            </p>
                          )}
                          {filteredCategories.map((cat) => (
                            <button
                              key={cat.id}
                              onClick={() => selectCat(cat.id, cat.name)}
                              className={cn(
                                "w-full flex items-center justify-between px-2.5 py-1.5 text-xs hover:bg-muted transition-colors text-left",
                                isCatActive(cat.id) && "bg-muted",
                              )}
                            >
                              <div className="flex items-center gap-2 min-w-0">
                                {cat.color && (
                                  <span
                                    className="w-2 h-2 rounded-full shrink-0"
                                    style={{ backgroundColor: cat.color }}
                                  />
                                )}
                                <span className="truncate">{cat.name}</span>
                              </div>
                              {isCatActive(cat.id) && (
                                <Check className="w-3 h-3 shrink-0 text-primary" />
                              )}
                            </button>
                          ))}
                        </>
                      )}

                      {!hasResults && (
                        <p className="px-2.5 py-2 text-xs text-muted-foreground">
                          No results.
                        </p>
                      )}
                    </div>
                  </div>
                )}
              </div>
            );
          })()}
        </div>

        {txnsLoading ? (
          <div className="flex items-center justify-center py-10 text-muted-foreground gap-2 text-sm">
            <Loader2 className="w-4 h-4 animate-spin" /> Loading…
          </div>
        ) : transactions.length === 0 ? (
          <div className="flex flex-col items-center justify-center py-10 gap-3 text-center">
            <Wallet className="w-7 h-7 text-muted-foreground" />
            <p className="text-sm text-muted-foreground">
              No transactions yet.
            </p>
            <Button
              size="sm"
              variant="outline"
              onClick={() => router.push("/budget/import")}
            >
              Import transactions
            </Button>
          </div>
        ) : (
          <div className="rounded-lg border">
            {transactions.map((txn, i) => {
              const effectiveCatId =
                txn.id in catOverrides ? catOverrides[txn.id] : txn.category_id;
              const effectiveIsTransfer =
                txn.id in transferOverrides
                  ? transferOverrides[txn.id]
                  : txn.is_transfer;
              const txnWithOverride = {
                ...txn,
                category_id: effectiveCatId,
                is_transfer: effectiveIsTransfer,
              };
              const isExpense = txn.amount < 0;
              const label = txn.merchant_name || txn.description;
              const sublabel = txn.merchant_name ? txn.description : null;
              const isTemplate = !!txn.recurring;
              const isInstance = !txn.recurring && !!txn.recurring_template_id;
              return (
                <div
                  key={txn.id}
                  className={cn(
                    "group flex items-center gap-3 px-4 py-3 text-sm cursor-pointer hover:bg-muted/40 transition-colors",
                    i > 0 && "border-t",
                    i === 0 && "rounded-t-lg",
                    i === transactions.length - 1 && "rounded-b-lg",
                    effectiveIsTransfer && "opacity-60",
                  )}
                  onClick={() => setEditingTxn(txn)}
                >
                  <span className="text-muted-foreground text-xs w-12 shrink-0 tabular-nums">
                    {fmtDate(txn.date)}
                  </span>
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-1.5 min-w-0">
                      <p className="truncate font-medium">{label}</p>
                      {(isTemplate || isInstance) && (
                        <span
                          title={
                            isTemplate
                              ? `Repeats ${
                                  txn.recurring!.frequency === "monthly"
                                    ? "every month"
                                    : txn.recurring!.frequency === "bi_weekly"
                                      ? "every two weeks"
                                      : txn.recurring!.frequency ===
                                          "semi_monthly"
                                        ? "twice a month (15th & 30th)"
                                        : txn.recurring!.frequency === "weekly"
                                          ? "every week"
                                          : txn.recurring!.frequency
                                }`
                              : "Recurring instance"
                          }
                          className={cn(
                            "shrink-0 flex items-center",
                            isTemplate
                              ? "text-sky-500"
                              : "text-muted-foreground/50",
                          )}
                        >
                          <Repeat className="w-3 h-3" />
                        </span>
                      )}
                    </div>
                    {sublabel && (
                      <p className="text-xs text-muted-foreground truncate">
                        {sublabel}
                      </p>
                    )}
                    {effectiveIsTransfer && (
                      <span className="inline-flex items-center gap-0.5 px-1.5 py-0.5 rounded text-[10px] font-medium bg-muted text-muted-foreground">
                        ⇄ Transfer
                      </span>
                    )}
                  </div>
                  {/* Stop row-click propagation on interactive sub-elements */}
                  <div onClick={(e) => e.stopPropagation()}>
                    <CategoryPicker
                      txn={txnWithOverride}
                      categories={categories}
                      onAssigned={handleCategoryAssigned}
                      onTransferToggled={handleTransferToggled}
                    />
                  </div>
                  <div onClick={(e) => e.stopPropagation()}>
                    <TxnActionsMenu
                      txnId={txn.id}
                      profiles={profiles}
                      currentProfileId={effectiveProfileId}
                      onMoved={handleTxnMoved}
                      recurring={txn.recurring}
                      recurringTemplateId={txn.recurring_template_id}
                      onRecurringChanged={() =>
                        void qc.invalidateQueries({
                          queryKey: ["budget", "transactions"],
                        })
                      }
                    />
                  </div>
                  <span
                    className={cn(
                      "shrink-0 tabular-nums font-medium w-24 text-right",
                      isExpense ? "text-foreground" : "text-budget-positive",
                    )}
                  >
                    {isExpense ? "−" : "+"}
                    {fmt(txn.amount, txn.currency)}
                  </span>
                </div>
              );
            })}
          </div>
        )}

        {txnPages > 1 && (
          <div className="flex items-center justify-between mt-3 text-sm text-muted-foreground">
            <span>
              {txnOffset + 1}–{Math.min(txnOffset + TXN_PAGE_SIZE, txnTotal)} of
              {""}
              {txnTotal}
            </span>
            <div className="flex items-center gap-1">
              <Button
                size="icon-sm"
                variant="ghost"
                disabled={txnOffset === 0}
                onClick={() =>
                  setTxnOffset(Math.max(0, txnOffset - TXN_PAGE_SIZE))
                }
              >
                <ChevronLeft className="w-4 h-4" />
              </Button>
              <span className="px-2 tabular-nums">
                {txnPage} / {txnPages}
              </span>
              <Button
                size="icon-sm"
                variant="ghost"
                disabled={txnOffset + TXN_PAGE_SIZE >= txnTotal}
                onClick={() => setTxnOffset(txnOffset + TXN_PAGE_SIZE)}
              >
                <ChevronRight className="w-4 h-4" />
              </Button>
            </div>
          </div>
        )}
      </section>

      {/* ── Transaction edit sheet ── */}
      {editingTxn && (
        <TxnEditSheet
          txn={editingTxn}
          currency={currency}
          onClose={() => setEditingTxn(null)}
          onSaved={handleTxnSaved}
          onDeleted={handleTxnDeleted}
        />
      )}
    </div>
  );
}
