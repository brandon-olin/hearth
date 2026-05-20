"use client";

import { useState, useRef } from "react";
import { useRouter } from "next/navigation";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { apiBaseUrl } from "@/lib/api/client";
import { fetchWithAuth } from "@/lib/api/fetch-with-auth";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select } from "@/components/ui/select";
import {
  Upload,
  ChevronRight,
  ChevronLeft,
  CheckCircle2,
  AlertCircle,
  Loader2,
  FileText,
  Plus,
} from "lucide-react";
import { cn } from "@/lib/utils";

// ── Types ─────────────────────────────────────────────────────────────────────

type Step = "account" | "upload" | "mapping" | "confirm";

interface ColumnMapping {
  date_col: string;
  description_col: string;
  amount_col: string | null;
  debit_col: string | null;
  credit_col: string | null;
  merchant_col: string | null;
}

interface DetectResult {
  format: "ofx" | "csv" | "unknown";
  columns?: string[];
  sample_rows?: string[][];
  detected_mapping?: ColumnMapping;
  mapping_confidence?: number;
  estimated_transaction_count?: number;
  date_range_start?: string;
  date_range_end?: string;
  errors?: string[];
}

interface ImportResult {
  inserted: number;
  skipped: number;
  parse_errors: string[];
}

type AccountScope = "personal" | "shared";
type AccountType = "checking" | "savings" | "credit_card" | "loan" | "investment" | "other";

interface BudgetAccount {
  id: string;
  name: string;
  account_type: AccountType;
  scope: AccountScope;
  currency: string;
}

const ACCOUNT_TYPE_LABELS: Record<AccountType, string> = {
  checking: "Checking",
  savings: "Savings",
  credit_card: "Credit card",
  loan: "Loan",
  investment: "Investment",
  other: "Other",
};

// ── API helpers ───────────────────────────────────────────────────────────────

async function fetchAccounts(): Promise<BudgetAccount[]> {
  const res = await fetchWithAuth(`${apiBaseUrl}/budget/accounts`);
  if (!res.ok) throw new Error("Failed to load accounts");
  return res.json() as Promise<BudgetAccount[]>;
}

async function createAccount(body: {
  name: string;
  account_type: AccountType;
  scope: AccountScope;
  currency: string;
}): Promise<BudgetAccount> {
  const res = await fetchWithAuth(`${apiBaseUrl}/budget/accounts`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({})) as { detail?: string };
    throw new Error(err.detail ?? "Failed to create account");
  }
  return res.json() as Promise<BudgetAccount>;
}

// ── Step indicator ────────────────────────────────────────────────────────────

const STEPS: { key: Step; label: string }[] = [
  { key: "account", label: "Account" },
  { key: "upload", label: "Upload" },
  { key: "mapping", label: "Columns" },
  { key: "confirm", label: "Import" },
];

function StepIndicator({ current }: { current: Step }) {
  const currentIdx = STEPS.findIndex((s) => s.key === current);
  return (
    <div className="flex items-center gap-2 mb-8">
      {STEPS.map((step, i) => (
        <div key={step.key} className="flex items-center gap-2">
          <div
            className={cn(
              "w-7 h-7 rounded-full flex items-center justify-center text-xs font-medium transition-colors",
              i < currentIdx
                ? "bg-primary text-primary-foreground"
                : i === currentIdx
                ? "bg-primary text-primary-foreground ring-2 ring-primary/30"
                : "bg-muted text-muted-foreground"
            )}
          >
            {i < currentIdx ? <CheckCircle2 className="w-4 h-4" /> : i + 1}
          </div>
          <span
            className={cn(
              "text-sm",
              i === currentIdx ? "text-foreground font-medium" : "text-muted-foreground"
            )}
          >
            {step.label}
          </span>
          {i < STEPS.length - 1 && (
            <ChevronRight className="w-4 h-4 text-muted-foreground mx-1" />
          )}
        </div>
      ))}
    </div>
  );
}

// ── Column selector ───────────────────────────────────────────────────────────

function ColumnSelect({
  label,
  value,
  columns,
  onChange,
  required,
}: {
  label: string;
  value: string | null;
  columns: string[];
  onChange: (v: string | null) => void;
  required?: boolean;
}) {
  return (
    <div className="flex flex-col gap-1">
      <Label className="text-xs text-muted-foreground">
        {label}
        {required && <span className="text-red-500 ml-0.5">*</span>}
      </Label>
      <Select
        value={value ?? ""}
        onChange={(e) => {
          const v = e.target.value;
          onChange(v === "" ? null : v);
        }}
        className="h-8 text-sm"
      >
        {!required && <option value="">— not used —</option>}
        {columns.map((col) => (
          <option key={col} value={col}>
            {col}
          </option>
        ))}
      </Select>
    </div>
  );
}

// ── Main wizard ───────────────────────────────────────────────────────────────

export default function BudgetImportPage() {
  const router = useRouter();
  const qc = useQueryClient();

  // Step state
  const [step, setStep] = useState<Step>("account");

  // Account step
  const [accountId, setAccountId] = useState<string>("");
  const [creatingAccount, setCreatingAccount] = useState(false);
  const [newAccountName, setNewAccountName] = useState("");
  const [newAccountType, setNewAccountType] = useState<AccountType>("checking");
  const [newAccountScope, setNewAccountScope] = useState<AccountScope>("personal");
  const [accountError, setAccountError] = useState("");

  // Upload step
  const [file, setFile] = useState<File | null>(null);
  const [detecting, setDetecting] = useState(false);
  const [detectResult, setDetectResult] = useState<DetectResult | null>(null);
  const [detectError, setDetectError] = useState("");
  const fileInputRef = useRef<HTMLInputElement>(null);

  // Mapping step
  const [mapping, setMapping] = useState<ColumnMapping>({
    date_col: "",
    description_col: "",
    amount_col: null,
    debit_col: null,
    credit_col: null,
    merchant_col: null,
  });

  // Confirm / results step
  const [importing, setImporting] = useState(false);
  const [importResult, setImportResult] = useState<ImportResult | null>(null);
  const [importError, setImportError] = useState("");

  // ── Data fetching ────────────────────────────────────────────────────────────

  const { data: accounts, isLoading: accountsLoading } = useQuery<BudgetAccount[]>({
    queryKey: ["budget", "accounts"],
    queryFn: fetchAccounts,
  });

  const createAccountMutation = useMutation({
    mutationFn: createAccount,
    onSuccess: (created) => {
      void qc.invalidateQueries({ queryKey: ["budget", "accounts"] });
      setAccountId(created.id);
      setCreatingAccount(false);
      setNewAccountName("");
    },
    onError: () => {
      setAccountError("Failed to create account.");
    },
  });

  // ── Handlers ─────────────────────────────────────────────────────────────────

  const handleCreateAccount = () => {
    if (!newAccountName.trim()) {
      setAccountError("Account name is required.");
      return;
    }
    setAccountError("");
    createAccountMutation.mutate({
      name: newAccountName.trim(),
      account_type: newAccountType,
      scope: newAccountScope,
      currency: "USD",
    });
  };

  const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const f = e.target.files?.[0] ?? null;
    setFile(f);
    setDetectResult(null);
    setDetectError("");
  };

  const handleDetect = async () => {
    if (!file) return;
    setDetecting(true);
    setDetectError("");
    try {
      const formData = new FormData();
      formData.append("file", file);
      const res = await fetchWithAuth(`${apiBaseUrl}/budget/import/detect`, {
        method: "POST",
        body: formData,
      });
      if (!res.ok) {
        const err = await res.json().catch(() => ({})) as { detail?: string };
        throw new Error(err.detail ?? "Detection failed.");
      }
      const data = await res.json() as DetectResult;
      setDetectResult(data);
      if (data.format === "csv" && data.detected_mapping) {
        setMapping(data.detected_mapping);
      }
    } catch (err: unknown) {
      setDetectError(err instanceof Error ? err.message : "Detection failed.");
    } finally {
      setDetecting(false);
    }
  };

  const handleImport = async () => {
    if (!file || !accountId) return;
    setImporting(true);
    setImportError("");
    try {
      const formData = new FormData();
      formData.append("file", file);
      formData.append("account_id", accountId);
      if (detectResult?.format === "csv") {
        formData.append("column_mapping", JSON.stringify(mapping));
      }
      const res = await fetchWithAuth(`${apiBaseUrl}/budget/import`, {
        method: "POST",
        body: formData,
      });
      if (!res.ok) {
        const err = await res.json().catch(() => ({})) as { detail?: string };
        throw new Error(err.detail ?? "Import failed.");
      }
      const data = await res.json() as ImportResult;
      setImportResult(data);
      void qc.invalidateQueries({ queryKey: ["budget", "transactions"] });
      setStep("confirm");
    } catch (err: unknown) {
      setImportError(err instanceof Error ? err.message : "Import failed.");
    } finally {
      setImporting(false);
    }
  };

  // ── Step: Account ────────────────────────────────────────────────────────────

  if (step === "account") {
    return (
      <div className="max-w-lg mx-auto py-10 px-4">
        <StepIndicator current="account" />
        <h1 className="text-lg font-semibold mb-1">Select account</h1>
        <p className="text-sm text-muted-foreground mb-6">
          Choose which account these transactions belong to, or create a new one.
        </p>

        {accountsLoading ? (
          <div className="flex items-center gap-2 text-muted-foreground text-sm">
            <Loader2 className="w-4 h-4 animate-spin" /> Loading accounts…
          </div>
        ) : (
          <div className="flex flex-col gap-2 mb-4">
            {(accounts ?? []).map((acc) => (
              <button
                key={acc.id}
                onClick={() => setAccountId(acc.id)}
                className={cn(
                  "flex items-center justify-between px-4 py-3 rounded-lg border text-sm transition-colors text-left",
                  accountId === acc.id
                    ? "border-primary bg-primary/5"
                    : "border-border hover:border-muted-foreground/40"
                )}
              >
                <span className="font-medium">{acc.name}</span>
                <span className="text-muted-foreground text-xs capitalize">
                  {acc.account_type.replace("_", " ")} · {acc.scope}
                </span>
              </button>
            ))}
          </div>
        )}

        {creatingAccount ? (
          <div className="border rounded-lg p-4 flex flex-col gap-3 mb-4">
            <div className="flex flex-col gap-1">
              <Label htmlFor="acc-name" className="text-xs text-muted-foreground">
                Account name
              </Label>
              <Input
                id="acc-name"
                placeholder="e.g. Chase Checking"
                value={newAccountName}
                onChange={(e) => setNewAccountName(e.target.value)}
                className="h-8 text-sm"
              />
            </div>
            <div className="grid grid-cols-2 gap-3">
              <div className="flex flex-col gap-1">
                <Label className="text-xs text-muted-foreground">Type</Label>
                <Select
                  value={newAccountType}
                  onChange={(e) => setNewAccountType(e.target.value as AccountType)}
                  className="h-8 text-sm"
                >
                  {Object.entries(ACCOUNT_TYPE_LABELS).map(([k, v]) => (
                    <option key={k} value={k}>{v}</option>
                  ))}
                </Select>
              </div>
              <div className="flex flex-col gap-1">
                <Label className="text-xs text-muted-foreground">Visibility</Label>
                <Select
                  value={newAccountScope}
                  onChange={(e) => setNewAccountScope(e.target.value as AccountScope)}
                  className="h-8 text-sm"
                >
                  <option value="personal">Personal</option>
                  <option value="shared">Shared (household)</option>
                </Select>
              </div>
            </div>
            {accountError && (
              <p className="text-xs text-red-500 flex items-center gap-1">
                <AlertCircle className="w-3 h-3" /> {accountError}
              </p>
            )}
            <div className="flex gap-2">
              <Button
                size="sm"
                onClick={handleCreateAccount}
                disabled={createAccountMutation.isPending}
              >
                {createAccountMutation.isPending && (
                  <Loader2 className="w-3 h-3 animate-spin mr-1" />
                )}
                Create
              </Button>
              <Button size="sm" variant="ghost" onClick={() => setCreatingAccount(false)}>
                Cancel
              </Button>
            </div>
          </div>
        ) : (
          <button
            onClick={() => setCreatingAccount(true)}
            className="flex items-center gap-2 text-sm text-muted-foreground hover:text-foreground transition-colors mb-4"
          >
            <Plus className="w-4 h-4" /> New account
          </button>
        )}

        <div className="flex justify-end">
          <Button disabled={!accountId} onClick={() => setStep("upload")}>
            Continue <ChevronRight className="w-4 h-4 ml-1" />
          </Button>
        </div>
      </div>
    );
  }

  // ── Step: Upload ─────────────────────────────────────────────────────────────

  if (step === "upload") {
    const canContinue =
      !!detectResult &&
      detectResult.format !== "unknown" &&
      !detectError;

    return (
      <div className="max-w-lg mx-auto py-10 px-4">
        <StepIndicator current="upload" />
        <h1 className="text-lg font-semibold mb-1">Upload file</h1>
        <p className="text-sm text-muted-foreground mb-6">
          Supported formats: OFX, QFX, and CSV exported from your bank.
        </p>

        <div
          onClick={() => fileInputRef.current?.click()}
          className={cn(
            "border-2 border-dashed rounded-lg p-8 flex flex-col items-center gap-3 cursor-pointer transition-colors mb-4",
            file
              ? "border-primary/40 bg-primary/5"
              : "border-border hover:border-muted-foreground/40"
          )}
        >
          {file ? (
            <>
              <FileText className="w-8 h-8 text-primary" />
              <span className="text-sm font-medium">{file.name}</span>
              <span className="text-xs text-muted-foreground">
                {(file.size / 1024).toFixed(1)} KB
              </span>
            </>
          ) : (
            <>
              <Upload className="w-8 h-8 text-muted-foreground" />
              <span className="text-sm text-muted-foreground">Click to choose a file</span>
              <span className="text-xs text-muted-foreground">.ofx · .qfx · .csv</span>
            </>
          )}
        </div>
        <input
          ref={fileInputRef}
          type="file"
          accept=".ofx,.qfx,.csv,.txt"
          className="hidden"
          onChange={handleFileChange}
        />

        {file && !detectResult && (
          <Button
            size="sm"
            variant="outline"
            onClick={() => void handleDetect()}
            disabled={detecting}
            className="mb-4"
          >
            {detecting && <Loader2 className="w-3 h-3 animate-spin mr-1" />}
            Detect format
          </Button>
        )}

        {detectError && (
          <div className="flex items-start gap-2 text-sm text-red-500 mb-4">
            <AlertCircle className="w-4 h-4 mt-0.5 shrink-0" />
            {detectError}
          </div>
        )}

        {detectResult && detectResult.format !== "unknown" && (
          <div className="rounded-lg border px-4 py-3 text-sm mb-4">
            <div className="font-medium mb-1 capitalize">{detectResult.format} file detected</div>
            {detectResult.estimated_transaction_count !== undefined && (
              <div className="text-muted-foreground">
                {detectResult.estimated_transaction_count} transactions
                {detectResult.date_range_start && detectResult.date_range_end && (
                  <>
                    {" "}· {detectResult.date_range_start} – {detectResult.date_range_end}
                  </>
                )}
              </div>
            )}
            {detectResult.format === "csv" && detectResult.columns && (
              <div className="text-muted-foreground">
                {detectResult.columns.length} columns detected
              </div>
            )}
            {detectResult.errors && detectResult.errors.length > 0 && (
              <div className="text-amber-600 mt-1 text-xs">
                {detectResult.errors.length} warning
                {detectResult.errors.length > 1 ? "s" : ""}
              </div>
            )}
          </div>
        )}

        <div className="flex justify-between">
          <Button variant="ghost" size="sm" onClick={() => setStep("account")}>
            <ChevronLeft className="w-4 h-4 mr-1" /> Back
          </Button>
          <Button
            disabled={!canContinue}
            onClick={() =>
              setStep(detectResult?.format === "csv" ? "mapping" : "confirm")
            }
          >
            Continue <ChevronRight className="w-4 h-4 ml-1" />
          </Button>
        </div>
      </div>
    );
  }

  // ── Step: Column mapping (CSV only) ──────────────────────────────────────────

  if (step === "mapping") {
    const columns = detectResult?.columns ?? [];
    const hasSingleAmount = !!mapping.amount_col;
    const hasSplitAmount = !!(mapping.debit_col || mapping.credit_col);
    const amountConfigured = hasSingleAmount || hasSplitAmount;
    const canContinue =
      !!mapping.date_col && !!mapping.description_col && amountConfigured;

    return (
      <div className="max-w-lg mx-auto py-10 px-4">
        <StepIndicator current="mapping" />
        <h1 className="text-lg font-semibold mb-1">Map columns</h1>
        <p className="text-sm text-muted-foreground mb-2">
          Tell us which CSV columns contain the date, amount, and description.
        </p>
        {detectResult?.mapping_confidence !== undefined &&
          detectResult.mapping_confidence < 0.8 && (
            <div className="flex items-center gap-2 text-xs text-amber-600 mb-4 bg-amber-50 dark:bg-amber-950/30 rounded px-3 py-2">
              <AlertCircle className="w-3 h-3 shrink-0" />
              Column names weren&apos;t recognised automatically — please review the mapping below.
            </div>
          )}

        <div className="flex flex-col gap-3 mb-6">
          <ColumnSelect
            label="Date column"
            value={mapping.date_col}
            columns={columns}
            onChange={(v) => setMapping((m) => ({ ...m, date_col: v ?? "" }))}
            required
          />
          <ColumnSelect
            label="Description column"
            value={mapping.description_col}
            columns={columns}
            onChange={(v) => setMapping((m) => ({ ...m, description_col: v ?? "" }))}
            required
          />

          <div className="border-t pt-3">
            <p className="text-xs text-muted-foreground mb-2">
              Amount — use a single signed column <em>or</em> separate debit/credit columns:
            </p>
            <div className="flex flex-col gap-2">
              <ColumnSelect
                label="Amount (single signed column)"
                value={mapping.amount_col}
                columns={columns}
                onChange={(v) =>
                  setMapping((m) => ({
                    ...m,
                    amount_col: v,
                    debit_col: v ? null : m.debit_col,
                    credit_col: v ? null : m.credit_col,
                  }))
                }
              />
              <ColumnSelect
                label="Debit column (money out)"
                value={mapping.debit_col}
                columns={columns}
                onChange={(v) =>
                  setMapping((m) => ({
                    ...m,
                    debit_col: v,
                    amount_col: v ? null : m.amount_col,
                  }))
                }
              />
              <ColumnSelect
                label="Credit column (money in)"
                value={mapping.credit_col}
                columns={columns}
                onChange={(v) =>
                  setMapping((m) => ({
                    ...m,
                    credit_col: v,
                    amount_col: v ? null : m.amount_col,
                  }))
                }
              />
            </div>
          </div>

          <ColumnSelect
            label="Merchant name (optional)"
            value={mapping.merchant_col}
            columns={columns}
            onChange={(v) => setMapping((m) => ({ ...m, merchant_col: v }))}
          />
        </div>

        {/* Sample rows preview */}
        {detectResult?.sample_rows && detectResult.sample_rows.length > 0 && (
          <div className="mb-6">
            <p className="text-xs text-muted-foreground mb-2">Sample rows from your file:</p>
            <div className="overflow-x-auto rounded border text-xs">
              <table className="w-full">
                <thead>
                  <tr className="bg-muted">
                    {columns.map((col) => (
                      <th
                        key={col}
                        className="px-2 py-1 text-left font-medium text-muted-foreground whitespace-nowrap"
                      >
                        {col}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {detectResult.sample_rows.map((row, i) => (
                    <tr key={i} className="border-t">
                      {row.map((cell, j) => (
                        <td
                          key={j}
                          className="px-2 py-1 whitespace-nowrap max-w-[120px] truncate"
                        >
                          {cell}
                        </td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        )}

        <div className="flex justify-between">
          <Button variant="ghost" size="sm" onClick={() => setStep("upload")}>
            <ChevronLeft className="w-4 h-4 mr-1" /> Back
          </Button>
          <Button disabled={!canContinue} onClick={() => setStep("confirm")}>
            Continue <ChevronRight className="w-4 h-4 ml-1" />
          </Button>
        </div>
      </div>
    );
  }

  // ── Step: Confirm / results ───────────────────────────────────────────────────

  return (
    <div className="max-w-lg mx-auto py-10 px-4">
      <StepIndicator current="confirm" />

      {importResult ? (
        // Done state
        <div className="flex flex-col items-center text-center gap-4 py-6">
          <CheckCircle2 className="w-12 h-12 text-green-500" />
          <div>
            <h1 className="text-lg font-semibold mb-1">Import complete</h1>
            <p className="text-sm text-muted-foreground">
              <strong>{importResult.inserted}</strong> transaction
              {importResult.inserted !== 1 ? "s" : ""} imported
              {importResult.skipped > 0 && (
                <>, {importResult.skipped} skipped as duplicates</>
              )}.
            </p>
          </div>
          {importResult.parse_errors.length > 0 && (
            <div className="w-full text-left rounded border px-4 py-3 text-xs text-amber-600">
              <p className="font-medium mb-1">
                {importResult.parse_errors.length} row
                {importResult.parse_errors.length > 1 ? "s" : ""} skipped:
              </p>
              <ul className="list-disc list-inside space-y-0.5">
                {importResult.parse_errors.slice(0, 10).map((e, i) => (
                  <li key={i}>{e}</li>
                ))}
                {importResult.parse_errors.length > 10 && (
                  <li>…and {importResult.parse_errors.length - 10} more</li>
                )}
              </ul>
            </div>
          )}
          <div className="flex gap-3">
            <Button onClick={() => router.push("/budget")}>Go to Budget</Button>
            <Button
              variant="outline"
              onClick={() => {
                setStep("account");
                setFile(null);
                setDetectResult(null);
                setImportResult(null);
              }}
            >
              Import another
            </Button>
          </div>
        </div>
      ) : (
        // Pre-import confirmation
        <>
          <h1 className="text-lg font-semibold mb-1">Ready to import</h1>
          <p className="text-sm text-muted-foreground mb-6">
            Review the details below, then click Import to add the transactions.
          </p>

          <div className="rounded-lg border divide-y text-sm mb-6">
            <div className="flex justify-between px-4 py-3">
              <span className="text-muted-foreground">File</span>
              <span className="font-medium">{file?.name}</span>
            </div>
            <div className="flex justify-between px-4 py-3">
              <span className="text-muted-foreground">Format</span>
              <span className="font-medium uppercase">{detectResult?.format}</span>
            </div>
            <div className="flex justify-between px-4 py-3">
              <span className="text-muted-foreground">Account</span>
              <span className="font-medium">
                {accounts?.find((a) => a.id === accountId)?.name ?? accountId}
              </span>
            </div>
            {detectResult?.estimated_transaction_count !== undefined && (
              <div className="flex justify-between px-4 py-3">
                <span className="text-muted-foreground">Transactions</span>
                <span className="font-medium">
                  {detectResult.estimated_transaction_count}
                </span>
              </div>
            )}
          </div>

          {importError && (
            <div className="flex items-start gap-2 text-sm text-red-500 mb-4">
              <AlertCircle className="w-4 h-4 mt-0.5 shrink-0" />
              {importError}
            </div>
          )}

          <div className="flex justify-between">
            <Button
              variant="ghost"
              size="sm"
              onClick={() =>
                setStep(detectResult?.format === "csv" ? "mapping" : "upload")
              }
              disabled={importing}
            >
              <ChevronLeft className="w-4 h-4 mr-1" /> Back
            </Button>
            <Button onClick={() => void handleImport()} disabled={importing}>
              {importing && <Loader2 className="w-4 h-4 animate-spin mr-1" />}
              Import
            </Button>
          </div>
        </>
      )}
    </div>
  );
}
