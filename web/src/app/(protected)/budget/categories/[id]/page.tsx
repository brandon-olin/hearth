"use client";

import { useState, useEffect, useCallback, useRef } from "react";
import { useParams, useRouter, useSearchParams } from "next/navigation";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { apiBaseUrl } from "@/lib/api/client";
import { fetchWithAuth } from "@/lib/api/fetch-with-auth";
import { Button } from "@/components/ui/button";
import {
  ChevronLeft,
  ChevronRight,
  Loader2,
  Tag,
  CheckCircle2,
  Trash2,
  X,
  ArrowLeftRight,
} from "lucide-react";
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
  notes: string | null;
  is_transfer: boolean;
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
  if (!res.ok) throw new Error(`Failed: ${method} ${path}`);
  return res.json() as Promise<T>;
}
async function del(path: string): Promise<void> {
  const res = await fetchWithAuth(`${apiBaseUrl}${path}`, { method: "DELETE" });
  if (!res.ok) throw new Error(`Failed: DELETE ${path}`);
}

// ── Formatting ────────────────────────────────────────────────────────────────

function fmt(amount: number, currency = "USD"): string {
  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency,
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  }).format(Math.abs(amount));
}

function fmtDate(s: string) {
  return new Date(s + "T00:00:00").toLocaleDateString("en-US", {
    month: "short",
    day: "numeric",
  });
}

// ── Transaction edit sheet ────────────────────────────────────────────────────

function TxnEditSheet({
  txn,
  onClose,
  onSaved,
  onDeleted,
}: {
  txn: BudgetTransaction;
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

  const lbl = (text: string) => (
    <label className="block text-xs font-medium text-muted-foreground uppercase tracking-wide mb-1.5">
      {text}
    </label>
  );
  const inputCls =
    "w-full h-9 px-3 rounded-md border bg-background text-sm focus:outline-none focus:ring-1 focus:ring-ring";

  return (
    <>
      <div
        className="fixed inset-0 z-40 bg-black/40 backdrop-blur-[2px]"
        onClick={onClose}
      />
      <div className="fixed inset-y-0 right-0 z-50 w-full max-w-sm bg-background border-l shadow-xl flex flex-col">
        <div className="flex items-center justify-between px-5 py-4 border-b shrink-0">
          <h2 className="text-base font-semibold">Edit transaction</h2>
          <button
            onClick={onClose}
            className="text-muted-foreground hover:text-foreground transition-colors p-1"
          >
            <X className="w-4 h-4" />
          </button>
        </div>
        <div className="flex-1 overflow-y-auto px-5 py-5 space-y-4">
          <div>
            {lbl("Date")}
            <input
              type="date"
              value={date}
              onChange={(e) => setDate(e.target.value)}
              className={inputCls}
            />
          </div>
          <div>
            {lbl("Amount")}
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
          <div>
            {lbl("Description")}
            <input
              type="text"
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              className={inputCls}
            />
          </div>
          <div>
            {lbl("Merchant")}
            <input
              type="text"
              value={merchantName}
              onChange={(e) => setMerchantName(e.target.value)}
              placeholder="Optional"
              className={inputCls}
            />
          </div>
          <div>
            {lbl("Notes")}
            <textarea
              value={notes}
              onChange={(e) => setNotes(e.target.value)}
              placeholder="Optional"
              rows={2}
              className="w-full px-3 py-2 rounded-md border bg-background text-sm resize-none focus:outline-none focus:ring-1 focus:ring-ring placeholder:text-muted-foreground/50"
            />
          </div>
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

// ── Category picker ───────────────────────────────────────────────────────────

function CategoryPicker({
  txn,
  categories,
  onAssigned,
  onApplied,
  onTransferToggled,
  onRowRemove,
}: {
  txn: BudgetTransaction;
  categories: BudgetCategory[];
  onAssigned: (txnId: string, catId: string | null) => void;
  /** Called after apply-to-similar completes so the page can refresh its list */
  onApplied?: () => void;
  onTransferToggled?: (txnId: string, isTransfer: boolean) => void;
  /** Called when it's safe to remove this row from the list */
  onRowRemove?: (txnId: string) => void;
}) {
  const [open, setOpen] = useState(false);
  const [dropUp, setDropUp] = useState(false);
  const [saving, setSaving] = useState(false);
  const [search, setSearch] = useState("");
  const [applyPrompt, setApplyPrompt] = useState<{
    catId: string;
    merchant: string;
  } | null>(null);
  const [applyPopupPos, setApplyPopupPos] = useState<{
    top: number;
    right: number;
  } | null>(null);
  const [applying, setApplying] = useState(false);
  const [applyResult, setApplyResult] = useState<string | null>(null);
  const [transferApplyPrompt, setTransferApplyPrompt] = useState<{
    merchant: string;
    pos: { top: number; right: number };
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
      onTransferToggled?.(txn.id, isTransfer);
      if (isTransfer) {
        const matchText = txn.merchant_name || txn.description;
        if (matchText && triggerRef.current) {
          const rect = triggerRef.current.getBoundingClientRect();
          const spaceBelow = window.innerHeight - rect.bottom;
          const pos =
            spaceBelow >= 48
              ? { top: rect.bottom + 6, right: window.innerWidth - rect.right }
              : { top: rect.top - 48, right: window.innerWidth - rect.right };
          setApplyPopupPos(pos); // use same pos state so result toast renders here
          setTransferApplyPrompt({ merchant: matchText, pos });
        } else {
          // No merchant text to match — remove the row right away
          onRowRemove?.(txn.id);
        }
      } else {
        setTransferApplyPrompt(null);
        // Unmark as transfer: row might now belong here — don't remove it
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
      onApplied?.();
    } finally {
      setApplyingTransfer(false);
      setTransferApplyPrompt(null);
      // Delay row removal so the result toast stays visible for 3s
      setTimeout(() => {
        setApplyPopupPos(null);
        onRowRemove?.(txn.id);
      }, 3100);
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
        // Capture the trigger's viewport position NOW so the fixed popup appears
        // correctly regardless of parent overflow or scroll position.
        if (triggerRef.current) {
          const rect = triggerRef.current.getBoundingClientRect();
          const spaceBelow = window.innerHeight - rect.bottom;
          if (spaceBelow >= 48) {
            setApplyPopupPos({
              top: rect.bottom + 6,
              right: window.innerWidth - rect.right,
            });
          } else {
            setApplyPopupPos({
              top: rect.top - 48,
              right: window.innerWidth - rect.right,
            });
          }
        }
        setApplyPrompt({ catId, merchant: matchText });
        // Row stays visible while the prompt is shown; onRowRemove called when prompt resolves
      } else {
        // No prompt to show — remove the row right away
        setApplyPrompt(null);
        setApplyPopupPos(null);
        onRowRemove?.(txn.id);
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
      onApplied?.();
    } finally {
      setApplying(false);
      setApplyPrompt(null);
      // Delay row removal so the result toast stays visible for 3s
      setTimeout(() => {
        setApplyPopupPos(null);
        onRowRemove?.(txn.id);
      }, 3100);
    }
  };

  // Transfer transactions: show a badge with an"Unmark"option
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
        {/* Transfer apply prompt — must live here too: is_transfer=true causes the early return,
 so the popup in the normal branch below is never reached after marking as transfer */}
        {transferApplyPrompt && !applyResult && applyPopupPos && (
          <div
            className="fixed z-50 whitespace-nowrap rounded-lg border bg-background shadow-lg px-3 py-2 text-xs flex items-center gap-2"
            style={{ top: applyPopupPos.top, right: applyPopupPos.right }}
          >
            <span className="text-muted-foreground truncate max-w-[160px]">
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
              onClick={() => {
                setTransferApplyPrompt(null);
                setApplyPopupPos(null);
                onRowRemove?.(txn.id);
              }}
              className="text-muted-foreground hover:text-foreground"
            >
              ✕
            </button>
          </div>
        )}
        {/* Result toast after apply-transfer-to-similar */}
        {applyResult && applyPopupPos && (
          <div
            className="fixed z-50 whitespace-nowrap rounded-lg border bg-background shadow-lg px-3 py-2 text-xs"
            style={{ top: applyPopupPos.top, right: applyPopupPos.right }}
          >
            <span className="text-muted-foreground">{applyResult}</span>
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

      {/*"Apply to all similar?"prompt — fixed-positioned so it's never clipped by parent overflow */}
      {(applyPrompt || applyResult) && applyPopupPos && (
        <div
          className="fixed z-50 whitespace-nowrap rounded-lg border bg-background shadow-lg px-3 py-2 text-xs flex items-center gap-2"
          style={{ top: applyPopupPos.top, right: applyPopupPos.right }}
        >
          {applyResult ? (
            <span className="text-muted-foreground">{applyResult}</span>
          ) : (
            <>
              <span className="text-muted-foreground truncate max-w-[160px]">
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
                onClick={() => {
                  setApplyPrompt(null);
                  setApplyPopupPos(null);
                  onRowRemove?.(txn.id);
                }}
                className="text-muted-foreground hover:text-foreground"
              >
                ✕
              </button>
            </>
          )}
        </div>
      )}

      {/*"Mark all similar as transfer?"prompt — fixed-positioned */}
      {transferApplyPrompt && !applyResult && (
        <div
          className="fixed z-50 whitespace-nowrap rounded-lg border bg-background shadow-lg px-3 py-2 text-xs flex items-center gap-2"
          style={{
            top: transferApplyPrompt.pos.top,
            right: transferApplyPrompt.pos.right,
          }}
        >
          <span className="text-muted-foreground truncate max-w-[160px]">
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
            onClick={() => {
              setTransferApplyPrompt(null);
              setApplyPopupPos(null);
              onRowRemove?.(txn.id);
            }}
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

// ── Page ──────────────────────────────────────────────────────────────────────

export default function CategoryDetailPage() {
  const params = useParams();
  const router = useRouter();
  const searchParams = useSearchParams();
  const qc = useQueryClient();
  const id = params.id as string;
  const isUncategorized = id === "uncategorized";

  // Date range + profile context passed from the budget page via URL query params
  const now = new Date();
  const yearParam =
    parseInt(searchParams.get("year") ?? "0") || now.getFullYear();
  const monthParam =
    parseInt(searchParams.get("month") ?? "0") || now.getMonth() + 1;
  const profileIdParam = searchParams.get("profile_id") ?? null;
  const presetParam = searchParams.get("preset") ?? "mtd";

  // Prefer explicit date_from/date_to if passed (non-month presets); fall back to year/month
  const dateFromParam = searchParams.get("date_from");
  const dateToParam = searchParams.get("date_to");
  const dateFrom =
    dateFromParam ?? `${yearParam}-${String(monthParam).padStart(2, "0")}-01`;
  const dateTo =
    dateToParam ??
    new Date(yearParam, monthParam, 0).toISOString().slice(0, 10);

  // Human-readable label for the header
  const rangeLabel = (() => {
    if (presetParam === "ytd") return `Year to date ${now.getFullYear()}`;
    if (presetParam === "last_month") {
      return new Date(yearParam, monthParam - 1, 1).toLocaleDateString(
        "en-US",
        { month: "long", year: "numeric" },
      );
    }
    if (presetParam === "custom") {
      const fmtShort = (s: string) =>
        new Date(s + "T00:00:00").toLocaleDateString("en-US", {
          month: "short",
          day: "numeric",
        });
      const fmtFull = (s: string) =>
        new Date(s + "T00:00:00").toLocaleDateString("en-US", {
          month: "short",
          day: "numeric",
          year: "numeric",
        });
      return `${fmtShort(dateFrom)} – ${fmtFull(dateTo)}`;
    }
    //"mtd"or fallback: show"Month Year"
    return new Date(yearParam, monthParam - 1, 1).toLocaleDateString("en-US", {
      month: "long",
      year: "numeric",
    });
  })();

  const [offset, setOffset] = useState(0);
  const [catOverrides, setCatOverrides] = useState<
    Record<string, string | null>
  >({});
  const [transferOverrides, setTransferOverrides] = useState<
    Record<string, boolean>
  >({});
  // For uncategorized view: track transactions assigned away so they fade out
  const [assignedAway, setAssignedAway] = useState<Set<string>>(new Set());
  // Edit sheet
  const [editingTxn, setEditingTxn] = useState<BudgetTransaction | null>(null);

  // Fetch this category's info (skip for the special"uncategorized"slug)
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

  // Transactions filtered by this category, month, and profile
  const { data: txnData, isLoading: txnsLoading } =
    useQuery<TransactionListResponse>({
      queryKey: [
        "budget",
        "category-txns",
        id,
        offset,
        dateFrom,
        dateTo,
        profileIdParam,
      ],
      queryFn: () => {
        const p = new URLSearchParams({
          limit: String(PAGE_SIZE),
          offset: String(offset),
        });
        if (isUncategorized) {
          p.set("uncategorized", "true");
        } else {
          p.set("category_id", id);
        }
        p.set("date_from", dateFrom);
        p.set("date_to", dateTo);
        if (profileIdParam) p.set("profile_id", profileIdParam);
        return get(`/budget/transactions?${p}`);
      },
    });

  useEffect(() => {
    setCatOverrides({});
    setTransferOverrides({});
  }, [txnData]);

  const handleAssigned = useCallback(
    (txnId: string, catId: string | null) => {
      setCatOverrides((prev) => ({ ...prev, [txnId]: catId }));
      // Row removal is now driven by CategoryPicker via onRowRemove (after any apply-prompt
      // is resolved), so we only update overrides and invalidate charts here.
      void qc.invalidateQueries({ queryKey: ["budget", "analytics"] });
      void qc.invalidateQueries({ queryKey: ["budget", "summary"] });
    },
    [qc],
  );

  const handleTransferToggled = useCallback(
    (txnId: string, isTransfer: boolean) => {
      setTransferOverrides((prev) => ({ ...prev, [txnId]: isTransfer }));
      // Row removal driven by CategoryPicker via onRowRemove after transfer prompt resolves
      void qc.invalidateQueries({ queryKey: ["budget", "analytics"] });
      void qc.invalidateQueries({ queryKey: ["budget", "summary"] });
    },
    [qc],
  );

  // Called by CategoryPicker once it's safe to remove a row (prompt resolved / dismissed)
  const handleRowRemove = useCallback((txnId: string) => {
    setAssignedAway((prev) => new Set([...prev, txnId]));
  }, []);

  // Called after apply-to-similar: bulk of transactions were re-categorized,
  // so flush local overrides and re-fetch the list from the server.
  const handleApplied = useCallback(() => {
    setAssignedAway(new Set());
    setCatOverrides({});
    void qc.invalidateQueries({ queryKey: ["budget", "category-txns", id] });
    void qc.invalidateQueries({ queryKey: ["budget", "analytics"] });
    void qc.invalidateQueries({ queryKey: ["budget", "summary"] });
  }, [id, qc]);

  const handleTxnSaved = useCallback(
    (_txnId: string) => {
      setEditingTxn(null);
      void qc.invalidateQueries({ queryKey: ["budget", "category-txns", id] });
      void qc.invalidateQueries({ queryKey: ["budget", "analytics"] });
      void qc.invalidateQueries({ queryKey: ["budget", "summary"] });
    },
    [id, qc],
  );

  const handleTxnDeleted = useCallback(
    (txnId: string) => {
      setEditingTxn(null);
      setAssignedAway((prev) => new Set([...prev, txnId]));
      void qc.invalidateQueries({ queryKey: ["budget", "category-txns", id] });
      void qc.invalidateQueries({ queryKey: ["budget", "analytics"] });
      void qc.invalidateQueries({ queryKey: ["budget", "summary"] });
    },
    [id, qc],
  );

  const transactions = (txnData?.items ?? []).filter(
    (t) => !assignedAway.has(t.id),
  );
  const txnTotal = txnData?.total ?? 0;
  const visibleTotal = txnTotal - assignedAway.size;
  const txnPages = Math.ceil(txnTotal / PAGE_SIZE);
  const txnPage = Math.floor(offset / PAGE_SIZE) + 1;

  const headerColor = isUncategorized
    ? "#94a3b8"
    : (category?.color ?? "#94a3b8");
  const headerName = isUncategorized
    ? "Uncategorized"
    : (category?.name ?? "…");
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
        <Button size="icon-sm" variant="ghost" onClick={() => router.back()}>
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
              {rangeLabel} · {visibleTotal} transaction
              {visibleTotal !== 1 ? "s" : ""}
              {isUncategorized && visibleTotal > 0 && "· click to categorize"}
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
            {isUncategorized
              ? "All caught up — no uncategorized transactions."
              : "No transactions in this category."}
          </p>
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
            return (
              <div
                key={txn.id}
                className={cn(
                  "flex items-center gap-3 px-4 py-3 text-sm cursor-pointer hover:bg-muted/40 transition-colors",
                  i > 0 && "border-t",
                  i === 0 && "rounded-t-lg",
                  i === transactions.length - 1 && "rounded-b-lg",
                )}
                onClick={() => setEditingTxn(txn)}
              >
                <span className="text-muted-foreground text-xs w-12 shrink-0 tabular-nums">
                  {fmtDate(txn.date)}
                </span>
                <div className="flex-1 min-w-0">
                  <p className="truncate font-medium">{label}</p>
                  {sublabel && (
                    <p className="text-xs text-muted-foreground truncate">
                      {sublabel}
                    </p>
                  )}
                  {txn.is_transfer && (
                    <span className="inline-flex items-center gap-1 mt-0.5 px-1.5 py-0.5 rounded text-[10px] font-medium bg-muted text-muted-foreground">
                      ⇄ Transfer · excluded from analytics
                    </span>
                  )}
                </div>
                <div onClick={(e) => e.stopPropagation()}>
                  <CategoryPicker
                    txn={txnWithOverride}
                    categories={allCategories}
                    onAssigned={handleAssigned}
                    onApplied={handleApplied}
                    onTransferToggled={handleTransferToggled}
                    onRowRemove={handleRowRemove}
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

      {/* ── Transaction edit sheet ── */}
      {editingTxn && (
        <TxnEditSheet
          txn={editingTxn}
          onClose={() => setEditingTxn(null)}
          onSaved={handleTxnSaved}
          onDeleted={handleTxnDeleted}
        />
      )}

      {/* ── Pagination ── */}
      {txnPages > 1 && (
        <div className="flex items-center justify-between mt-3 text-sm text-muted-foreground">
          <span>
            {offset + 1}–{Math.min(offset + PAGE_SIZE, txnTotal)} of {txnTotal}
          </span>
          <div className="flex items-center gap-1">
            <Button
              size="icon-sm"
              variant="ghost"
              disabled={offset === 0}
              onClick={() => setOffset(Math.max(0, offset - PAGE_SIZE))}
            >
              <ChevronLeft className="w-4 h-4" />
            </Button>
            <span className="px-2 tabular-nums">
              {txnPage} / {txnPages}
            </span>
            <Button
              size="icon-sm"
              variant="ghost"
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
