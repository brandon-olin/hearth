"use client";

import { useMemo, useRef, useState } from "react";
import { Check, Copy, Loader2, Plus, KeyRound, Trash2, TriangleAlert } from "lucide-react";
import { useQueryClient } from "@tanstack/react-query";
import { $api } from "@/lib/api/query";
import { cn } from "@/lib/utils";

// Access levels a scope can be granted. "none" = not granted at all.
type Access = "none" | "read" | "write";

const EXPIRY_OPTIONS = [
  { value: 30, label: "30 days" },
  { value: 90, label: "90 days" },
  { value: 365, label: "1 year" },
  { value: 0, label: "Never" }, // 0 → send null (no expiry)
] as const;

function formatDate(iso: string | null): string {
  if (!iso) return "—";
  return new Date(iso).toLocaleDateString(undefined, {
    year: "numeric",
    month: "short",
    day: "numeric",
  });
}

function AccessSelect({
  value,
  onChange,
}: {
  value: Access;
  onChange: (v: Access) => void;
}) {
  return (
    <select
      value={value}
      onChange={(e) => onChange(e.target.value as Access)}
      className={cn(
        "text-xs rounded-md border bg-background px-2 py-1.5 pr-6",
        "focus:outline-none focus:ring-1 focus:ring-primary",
      )}
    >
      <option value="none">No access</option>
      <option value="read">Read</option>
      <option value="write">Read &amp; write</option>
    </select>
  );
}

// ── Create form ───────────────────────────────────────────────────────────────

function CreateTokenForm({ onCreated }: { onCreated: (rawToken: string) => void }) {
  const qc = useQueryClient();
  const { data: scopeOptions } = $api.useQuery("get", "/auth/tokens/scopes");
  const createToken = $api.useMutation("post", "/auth/tokens");

  const [name, setName] = useState("");
  const [expiry, setExpiry] = useState<number>(365);
  const [access, setAccess] = useState<Record<string, Access>>({});
  const [error, setError] = useState<string | null>(null);

  // Stable idempotency key for this form instance — regenerating on each
  // submit would defeat the purpose (see web/CLAUDE.md → Idempotency).
  const idempotencyKey = useRef(crypto.randomUUID());

  const grantedCount = useMemo(
    () => Object.values(access).filter((a) => a !== "none").length,
    [access],
  );

  const canSubmit = name.trim().length > 0 && grantedCount > 0 && !createToken.isPending;

  async function handleSubmit() {
    if (!canSubmit) return;
    setError(null);
    const scopes: Record<string, string> = {};
    for (const [domain, level] of Object.entries(access)) {
      if (level !== "none") scopes[domain] = level;
    }
    try {
      const res = await createToken.mutateAsync({
        body: {
          name: name.trim(),
          scopes,
          expires_in_days: expiry === 0 ? null : expiry,
        },
        headers: { "Idempotency-Key": idempotencyKey.current },
      });
      qc.invalidateQueries({ queryKey: ["get", "/auth/tokens"] });
      // Reset for a possible next token — new intent gets a new key.
      idempotencyKey.current = crypto.randomUUID();
      setName("");
      setAccess({});
      onCreated(res.token);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Failed to create token.");
    }
  }

  return (
    <div className="border rounded-lg bg-card p-4 space-y-4">
      <div className="space-y-1.5">
        <label className="text-xs font-medium text-muted-foreground">Name</label>
        <input
          type="text"
          value={name}
          maxLength={100}
          placeholder="e.g. Kitchen speaker"
          onChange={(e) => setName(e.target.value)}
          className="w-full text-sm rounded-md border bg-background px-3 py-2 focus:outline-none focus:ring-1 focus:ring-primary"
        />
      </div>

      <div className="space-y-1.5">
        <label className="text-xs font-medium text-muted-foreground">Access</label>
        <p className="text-xs text-muted-foreground">
          A token can never do more than your own account is allowed to.
        </p>
        <div className="border rounded-md divide-y">
          {(scopeOptions ?? []).map((opt) => (
            <div key={opt.key} className="flex items-center justify-between px-3 py-2">
              <span className="text-sm">{opt.label}</span>
              <AccessSelect
                value={access[opt.key] ?? "none"}
                onChange={(v) => setAccess((prev) => ({ ...prev, [opt.key]: v }))}
              />
            </div>
          ))}
        </div>
      </div>

      <div className="space-y-1.5">
        <label className="text-xs font-medium text-muted-foreground">Expires</label>
        <select
          value={expiry}
          onChange={(e) => setExpiry(Number(e.target.value))}
          className="text-sm rounded-md border bg-background px-2 py-1.5 pr-6 focus:outline-none focus:ring-1 focus:ring-primary"
        >
          {EXPIRY_OPTIONS.map((opt) => (
            <option key={opt.value} value={opt.value}>
              {opt.label}
            </option>
          ))}
        </select>
      </div>

      {error && <p className="text-sm text-destructive">{error}</p>}

      <button
        type="button"
        onClick={handleSubmit}
        disabled={!canSubmit}
        className={cn(
          "flex items-center gap-1.5 px-4 py-2 rounded-md text-sm font-medium transition-colors",
          canSubmit
            ? "bg-primary text-primary-foreground hover:bg-primary/90"
            : "bg-muted text-muted-foreground cursor-not-allowed",
        )}
      >
        {createToken.isPending ? (
          <>
            <Loader2 className="h-3.5 w-3.5 animate-spin" /> Creating…
          </>
        ) : (
          <>
            <Plus className="h-3.5 w-3.5" /> Create token
          </>
        )}
      </button>
    </div>
  );
}

// ── One-time secret reveal ────────────────────────────────────────────────────

function NewTokenReveal({ token, onDismiss }: { token: string; onDismiss: () => void }) {
  const [copied, setCopied] = useState(false);

  async function copy() {
    try {
      await navigator.clipboard.writeText(token);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      // Clipboard may be blocked (e.g. insecure context) — the value is still
      // selectable in the field, so this is non-fatal.
    }
  }

  return (
    <div className="border rounded-lg bg-warning p-4 space-y-3">
      <div className="flex items-start gap-2">
        <TriangleAlert className="h-4 w-4 text-warning mt-0.5 shrink-0" />
        <div>
          <p className="text-sm font-medium text-warning">Copy your token now</p>
          <p className="text-xs text-warning">
            This is the only time it will be shown. Store it somewhere safe — you can&apos;t
            retrieve it again.
          </p>
        </div>
      </div>
      <div className="flex items-center gap-2">
        <code className="flex-1 text-xs font-mono bg-background rounded-md border px-3 py-2 overflow-x-auto whitespace-nowrap">
          {token}
        </code>
        <button
          type="button"
          onClick={copy}
          className="flex items-center gap-1.5 px-3 py-2 rounded-md text-sm font-medium bg-primary text-primary-foreground hover:bg-primary/90 transition-colors shrink-0"
        >
          {copied ? <Check className="h-3.5 w-3.5" /> : <Copy className="h-3.5 w-3.5" />}
          {copied ? "Copied" : "Copy"}
        </button>
      </div>
      <button
        type="button"
        onClick={onDismiss}
        className="text-sm text-muted-foreground hover:text-foreground transition-colors"
      >
        Done
      </button>
    </div>
  );
}

// ── Token row ─────────────────────────────────────────────────────────────────

function TokenRow({
  token,
  onRevoked,
}: {
  token: {
    id: string;
    name: string;
    prefix: string;
    scopes: Record<string, string>;
    expires_at: string | null;
    last_used_at: string | null;
  };
  onRevoked: () => void;
}) {
  const qc = useQueryClient();
  const revoke = $api.useMutation("delete", "/auth/tokens/{token_id}");
  const [confirming, setConfirming] = useState(false);

  async function handleRevoke() {
    try {
      await revoke.mutateAsync({ params: { path: { token_id: token.id } } });
      qc.invalidateQueries({ queryKey: ["get", "/auth/tokens"] });
      onRevoked();
    } catch {
      // If it 404s it's already gone — refresh either way.
      qc.invalidateQueries({ queryKey: ["get", "/auth/tokens"] });
    }
  }

  const scopeChips = Object.entries(token.scopes ?? {});

  return (
    <div className="flex items-start justify-between gap-4 py-3 border-b last:border-0">
      <div className="min-w-0 space-y-1.5">
        <div className="flex items-center gap-2">
          <KeyRound className="h-3.5 w-3.5 text-muted-foreground shrink-0" />
          <p className="text-sm font-medium truncate">{token.name}</p>
        </div>
        <p className="text-xs font-mono text-muted-foreground">{token.prefix}…</p>
        <div className="flex flex-wrap gap-1">
          {scopeChips.map(([domain, level]) => (
            <span
              key={domain}
              className={cn("badge", level === "write" ? "badge-primary" : "badge-neutral")}
            >
              {domain}: {level}
            </span>
          ))}
        </div>
        <p className="text-xs text-muted-foreground">
          Last used {formatDate(token.last_used_at)} · Expires {formatDate(token.expires_at)}
        </p>
      </div>

      <div className="shrink-0">
        {confirming ? (
          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={handleRevoke}
              disabled={revoke.isPending}
              className="flex items-center gap-1 px-2.5 py-1.5 rounded-md text-xs font-medium bg-destructive text-destructive-foreground hover:bg-destructive/90 transition-colors disabled:opacity-50"
            >
              {revoke.isPending ? <Loader2 className="h-3 w-3 animate-spin" /> : null}
              Revoke
            </button>
            <button
              type="button"
              onClick={() => setConfirming(false)}
              className="text-xs text-muted-foreground hover:text-foreground transition-colors"
            >
              Cancel
            </button>
          </div>
        ) : (
          <button
            type="button"
            onClick={() => setConfirming(true)}
            className="flex items-center gap-1 px-2.5 py-1.5 rounded-md text-xs text-muted-foreground hover:text-destructive hover:bg-destructive/10 transition-colors"
          >
            <Trash2 className="h-3.5 w-3.5" /> Revoke
          </button>
        )}
      </div>
    </div>
  );
}

// ── Main section ──────────────────────────────────────────────────────────────

export function AccessTokensSection() {
  const { data: tokens, isLoading } = $api.useQuery("get", "/auth/tokens");
  const [newToken, setNewToken] = useState<string | null>(null);

  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-xs font-semibold text-muted-foreground uppercase tracking-wide mb-1">
          Access tokens
        </h2>
        <p className="text-sm text-muted-foreground">
          Long-lived tokens let agents and integrations (MCP clients, Home Assistant, calendar
          feeds) act on your behalf without your password. Each token is scoped and can be revoked
          at any time.
        </p>
      </div>

      {newToken && <NewTokenReveal token={newToken} onDismiss={() => setNewToken(null)} />}

      <CreateTokenForm onCreated={(t) => setNewToken(t)} />

      <div>
        <h3 className="text-xs font-semibold text-muted-foreground uppercase tracking-wide mb-2">
          Your tokens
        </h3>
        <div className="border rounded-lg bg-card px-4">
          {isLoading ? (
            <div className="flex items-center justify-center py-8 text-muted-foreground">
              <Loader2 className="h-4 w-4 animate-spin mr-2" />
              <span className="text-sm">Loading…</span>
            </div>
          ) : !tokens || tokens.length === 0 ? (
            <p className="text-sm text-muted-foreground py-8 text-center">
              No tokens yet. Create one above to connect an agent or integration.
            </p>
          ) : (
            tokens.map((t) => (
              <TokenRow key={t.id} token={t} onRevoked={() => setNewToken(null)} />
            ))
          )}
        </div>
      </div>
    </div>
  );
}
