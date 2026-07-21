"use client";

import { useState } from "react";
import {
  Check,
  Copy,
  ExternalLink,
  Loader2,
  Pause,
  Play,
  Plus,
  Trash2,
  TriangleAlert,
  Webhook,
} from "lucide-react";
import { useQueryClient } from "@tanstack/react-query";
import { $api } from "@/lib/api/query";
import { cn } from "@/lib/utils";

type Subscription = {
  id: string;
  description: string | null;
  url: string;
  event_patterns: string[];
  active: boolean;
  consecutive_failures: number;
  disabled_reason: string | null;
  last_delivery_at: string | null;
  created_at: string;
};

const SUBSCRIPTIONS_KEY = ["get", "/webhooks"];

function formatDate(iso: string | null): string {
  if (!iso) return "never";
  return new Date(iso).toLocaleString(undefined, {
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
  });
}

// ── Secret reveal ─────────────────────────────────────────────────────────────

function SecretReveal({ secret, onDismiss }: { secret: string; onDismiss: () => void }) {
  const [copied, setCopied] = useState(false);

  async function copy() {
    try {
      await navigator.clipboard.writeText(secret);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      // Clipboard can be blocked in an insecure context — the value is still
      // selectable, so this is non-fatal.
    }
  }

  return (
    <div className="border rounded-lg bg-warning p-4 space-y-3">
      <div className="flex items-start gap-2">
        <TriangleAlert className="h-4 w-4 text-warning mt-0.5 shrink-0" />
        <div>
          <p className="text-sm font-medium text-warning">Copy your signing secret now</p>
          <p className="text-xs text-warning">
            This is the only time it will be shown. Your receiver needs it to verify the
            <code className="font-mono"> X-Hearth-Signature </code> header — it can&apos;t be
            retrieved later.
          </p>
        </div>
      </div>
      <div className="flex items-center gap-2">
        <code className="flex-1 text-xs font-mono bg-background rounded-md border px-3 py-2 overflow-x-auto whitespace-nowrap">
          {secret}
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
        className="text-sm text-warning hover:opacity-80 transition-opacity"
      >
        Done
      </button>
    </div>
  );
}

// ── Create form ───────────────────────────────────────────────────────────────

function CreateWebhookForm({ onCreated }: { onCreated: (secret: string) => void }) {
  const qc = useQueryClient();
  const { data: catalog } = $api.useQuery("get", "/webhooks/events");
  const create = $api.useMutation("post", "/webhooks");

  const [url, setUrl] = useState("");
  const [description, setDescription] = useState("");
  const [selected, setSelected] = useState<string[]>([]);
  const [error, setError] = useState<string | null>(null);

  const canSubmit = url.trim().length > 0 && selected.length > 0 && !create.isPending;

  function toggle(event: string) {
    setSelected((prev) =>
      prev.includes(event) ? prev.filter((e) => e !== event) : [...prev, event],
    );
  }

  async function handleSubmit() {
    if (!canSubmit) return;
    setError(null);
    try {
      const res = await create.mutateAsync({
        body: {
          url: url.trim(),
          event_patterns: selected,
          description: description.trim() || null,
        },
      });
      qc.invalidateQueries({ queryKey: SUBSCRIPTIONS_KEY });
      setUrl("");
      setDescription("");
      setSelected([]);
      onCreated(res.secret);
    } catch (err: unknown) {
      // The API's messages are written to be shown as-is — an unusable event
      // pattern enumerates the valid ones, a rejected URL says why.
      setError(err instanceof Error ? err.message : "Could not create the webhook.");
    }
  }

  return (
    <div className="border rounded-lg bg-card p-4 space-y-4">
      <div className="space-y-1.5">
        <label htmlFor="webhook-url" className="text-sm font-medium">
          Endpoint URL
        </label>
        <input
          id="webhook-url"
          type="url"
          value={url}
          onChange={(e) => setUrl(e.target.value)}
          placeholder="http://homeassistant.local:8123/api/webhook/hearth"
          className="w-full text-sm rounded-md border bg-background px-3 py-2 focus:outline-none focus:ring-1 focus:ring-primary"
        />
      </div>

      <div className="space-y-1.5">
        <label htmlFor="webhook-description" className="text-sm font-medium">
          Label <span className="text-muted-foreground font-normal">(optional)</span>
        </label>
        <input
          id="webhook-description"
          type="text"
          value={description}
          onChange={(e) => setDescription(e.target.value)}
          placeholder="Home Assistant"
          maxLength={200}
          className="w-full text-sm rounded-md border bg-background px-3 py-2 focus:outline-none focus:ring-1 focus:ring-primary"
        />
      </div>

      <div className="space-y-2">
        <p className="text-sm font-medium">Events to send</p>
        <div className="space-y-1.5">
          {(catalog?.items ?? []).map((item) => (
            <label
              key={item.event}
              className="flex items-start gap-2.5 text-sm cursor-pointer py-1"
            >
              <input
                type="checkbox"
                className="checkbox-themed mt-0.5"
                checked={selected.includes(item.event)}
                onChange={() => toggle(item.event)}
              />
              <span className="min-w-0">
                <code className="font-mono text-xs">{item.event}</code>
                <span className="text-muted-foreground"> — {item.description}</span>
                <span className="block text-xs text-muted-foreground">
                  Sends: {item.summary_fields.join(", ")}
                </span>
              </span>
            </label>
          ))}
        </div>
        <p className="text-xs text-muted-foreground">
          You only receive events you can already see — a household member&apos;s personal
          to-dos are never delivered to your endpoint.
        </p>
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
        {create.isPending ? (
          <>
            <Loader2 className="h-3.5 w-3.5 animate-spin" /> Creating…
          </>
        ) : (
          <>
            <Plus className="h-3.5 w-3.5" /> Create webhook
          </>
        )}
      </button>
    </div>
  );
}

// ── Subscription row ──────────────────────────────────────────────────────────

function WebhookRow({ subscription }: { subscription: Subscription }) {
  const qc = useQueryClient();
  const update = $api.useMutation("patch", "/webhooks/{subscription_id}");
  const remove = $api.useMutation("delete", "/webhooks/{subscription_id}");
  const [confirming, setConfirming] = useState(false);

  const autoDisabled = !subscription.active && subscription.disabled_reason !== null;

  async function setActive(active: boolean) {
    await update.mutateAsync({
      params: { path: { subscription_id: subscription.id } },
      body: { active },
    });
    qc.invalidateQueries({ queryKey: SUBSCRIPTIONS_KEY });
  }

  async function handleDelete() {
    try {
      await remove.mutateAsync({ params: { path: { subscription_id: subscription.id } } });
    } finally {
      // A 404 means it is already gone — refresh either way.
      qc.invalidateQueries({ queryKey: SUBSCRIPTIONS_KEY });
    }
  }

  return (
    <div className="flex items-start justify-between gap-4 py-3 border-b last:border-0">
      <div className="min-w-0 space-y-1.5">
        <div className="flex items-center gap-2 flex-wrap">
          <Webhook className="h-3.5 w-3.5 text-muted-foreground shrink-0" />
          <p className="text-sm font-medium truncate">
            {subscription.description || subscription.url}
          </p>
          <span
            className={cn(
              "badge",
              subscription.active
                ? "badge-success"
                : autoDisabled
                  ? "badge-error"
                  : "badge-neutral badge-faded",
            )}
          >
            {subscription.active ? "Active" : autoDisabled ? "Auto-disabled" : "Paused"}
          </span>
        </div>
        <p className="text-xs font-mono text-muted-foreground truncate">{subscription.url}</p>
        <div className="flex flex-wrap gap-1">
          {subscription.event_patterns.map((pattern) => (
            <span key={pattern} className="badge badge-neutral">
              {pattern}
            </span>
          ))}
        </div>
        {autoDisabled ? (
          <p className="text-xs text-destructive">{subscription.disabled_reason}</p>
        ) : (
          <p className="text-xs text-muted-foreground">
            Last delivered {formatDate(subscription.last_delivery_at)}
            {subscription.consecutive_failures > 0 &&
              ` · ${subscription.consecutive_failures} consecutive failure${
                subscription.consecutive_failures === 1 ? "" : "s"
              }`}
          </p>
        )}
      </div>

      <div className="shrink-0 flex items-center gap-2">
        {confirming ? (
          <>
            <button
              type="button"
              onClick={handleDelete}
              disabled={remove.isPending}
              className="flex items-center gap-1 px-2.5 py-1.5 rounded-md text-xs font-medium bg-destructive text-destructive-foreground hover:bg-destructive/90 transition-colors disabled:opacity-50"
            >
              {remove.isPending ? <Loader2 className="h-3 w-3 animate-spin" /> : null}
              Delete
            </button>
            <button
              type="button"
              onClick={() => setConfirming(false)}
              className="text-xs text-muted-foreground hover:text-foreground transition-colors"
            >
              Cancel
            </button>
          </>
        ) : (
          <>
            <button
              type="button"
              onClick={() => setActive(!subscription.active)}
              disabled={update.isPending}
              className="flex items-center gap-1 px-2.5 py-1.5 rounded-md text-xs text-muted-foreground hover:text-foreground hover:bg-muted transition-colors disabled:opacity-50"
            >
              {subscription.active ? (
                <>
                  <Pause className="h-3.5 w-3.5" /> Pause
                </>
              ) : (
                <>
                  <Play className="h-3.5 w-3.5" /> Resume
                </>
              )}
            </button>
            <button
              type="button"
              onClick={() => setConfirming(true)}
              className="flex items-center gap-1 px-2.5 py-1.5 rounded-md text-xs text-muted-foreground hover:text-destructive hover:bg-destructive/10 transition-colors"
            >
              <Trash2 className="h-3.5 w-3.5" /> Delete
            </button>
          </>
        )}
      </div>
    </div>
  );
}

// ── Main section ──────────────────────────────────────────────────────────────

export function WebhooksSection() {
  const { data, isLoading } = $api.useQuery("get", "/webhooks");
  const [newSecret, setNewSecret] = useState<string | null>(null);
  const [creating, setCreating] = useState(false);

  const subscriptions = (data?.items ?? []) as Subscription[];

  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-xs font-semibold text-muted-foreground uppercase tracking-wide mb-1">
          Webhooks
        </h2>
        <p className="text-sm text-muted-foreground">
          Send household events to another system as they happen — a Home Assistant
          automation, an n8n flow, a family chat bot. Each delivery is signed with a secret
          only you and your receiver know.
        </p>
      </div>

      {newSecret && <SecretReveal secret={newSecret} onDismiss={() => setNewSecret(null)} />}

      {creating ? (
        <div className="space-y-2">
          <CreateWebhookForm
            onCreated={(secret) => {
              setNewSecret(secret);
              setCreating(false);
            }}
          />
          <button
            type="button"
            onClick={() => setCreating(false)}
            className="text-sm text-muted-foreground hover:text-foreground transition-colors"
          >
            Cancel
          </button>
        </div>
      ) : (
        <button
          type="button"
          onClick={() => setCreating(true)}
          className="flex items-center gap-1.5 px-4 py-2 rounded-md text-sm font-medium bg-primary text-primary-foreground hover:bg-primary/90 transition-colors"
        >
          <Plus className="h-3.5 w-3.5" /> Add webhook
        </button>
      )}

      <div className="border rounded-lg bg-card px-4">
        {isLoading ? (
          <p className="text-sm text-muted-foreground py-4">Loading…</p>
        ) : subscriptions.length === 0 ? (
          <p className="text-sm text-muted-foreground py-4">
            No webhooks yet. Add one to start sending events.
          </p>
        ) : (
          subscriptions.map((subscription) => (
            <WebhookRow key={subscription.id} subscription={subscription} />
          ))
        )}
      </div>

      <a
        href="https://github.com/brandon-olin/life-dashboard/blob/main/docs/webhooks.md"
        target="_blank"
        rel="noreferrer"
        className="inline-flex items-center gap-1.5 text-sm text-primary hover:underline"
      >
        <ExternalLink className="h-3.5 w-3.5" /> Payload format, signature verification, and the
        Home Assistant recipe
      </a>
    </div>
  );
}
