"use client";

import { useRef, useState } from "react";
import { Check, Copy, ExternalLink, Loader2, TriangleAlert, Zap } from "lucide-react";
import { useQueryClient } from "@tanstack/react-query";
import { $api } from "@/lib/api/query";
import { cn } from "@/lib/utils";

// The scopes Home Assistant needs: append groceries, create to-dos (read
// implied by write for the "to-dos today" count), and check in habits. This
// mirrors the scope table in docs/home-assistant-setup.md — keep them in sync.
const HA_SCOPES = { grocery: "write", todos: "write", habits: "write" } as const;
const HA_TOKEN_NAME = "Home Assistant";

function CopyButton({ value, label = "Copy" }: { value: string; label?: string }) {
  const [copied, setCopied] = useState(false);
  async function copy() {
    try {
      await navigator.clipboard.writeText(value);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      // Clipboard may be blocked in an insecure context — the value is still
      // selectable, so this is non-fatal.
    }
  }
  return (
    <button
      type="button"
      onClick={copy}
      className="flex items-center gap-1.5 px-3 py-2 rounded-md text-sm font-medium bg-primary text-primary-foreground hover:bg-primary/90 transition-colors shrink-0"
    >
      {copied ? <Check className="h-3.5 w-3.5" /> : <Copy className="h-3.5 w-3.5" />}
      {copied ? "Copied" : label}
    </button>
  );
}

// The ready-to-paste rest_command with the freshly minted token injected. The
// user still fills in BASE_URL and LIST_ID (deployment-specific) — see the guide.
function yamlSnippet(token: string): string {
  return `rest_command:
  hearth_add_grocery:
    url: "BASE_URL/grocery-lists/LIST_ID/items"
    method: POST
    headers:
      Authorization: "Bearer ${token}"
      Content-Type: "application/json"
    payload: '{"name": "{{ item }}"}'`;
}

function NewHaTokenReveal({ token }: { token: string }) {
  return (
    <div className="space-y-4">
      <div className="border rounded-lg bg-warning p-4 space-y-3">
        <div className="flex items-start gap-2">
          <TriangleAlert className="h-4 w-4 text-warning mt-0.5 shrink-0" />
          <div>
            <p className="text-sm font-medium text-warning">Copy your token now</p>
            <p className="text-xs text-warning">
              This is the only time it will be shown. Paste it into Home Assistant&apos;s
              config — you can&apos;t retrieve it again.
            </p>
          </div>
        </div>
        <div className="flex items-center gap-2">
          <code className="flex-1 text-xs font-mono bg-background rounded-md border px-3 py-2 overflow-x-auto whitespace-nowrap">
            {token}
          </code>
          <CopyButton value={token} />
        </div>
      </div>

      <div className="space-y-2">
        <div className="flex items-center justify-between">
          <p className="text-xs font-medium text-muted-foreground">
            Paste into <code className="font-mono">configuration.yaml</code>
          </p>
          <CopyButton value={yamlSnippet(token)} label="Copy YAML" />
        </div>
        <pre className="text-xs font-mono bg-card border rounded-md p-3 overflow-x-auto whitespace-pre">
          {yamlSnippet(token)}
        </pre>
        <p className="text-xs text-muted-foreground">
          Replace <code className="font-mono">BASE_URL</code> with your Hearth address and{" "}
          <code className="font-mono">LIST_ID</code>{" "}with your active shopping list&apos;s ID
          {" "}(<code className="font-mono">GET /grocery-lists?status=active</code>). The full guide
          covers to-do creation, the &quot;to-dos today&quot; sensor, and Assist voice intents.
        </p>
      </div>
    </div>
  );
}

export function HomeAssistantSection() {
  const qc = useQueryClient();
  const createToken = $api.useMutation("post", "/auth/tokens");
  const [newToken, setNewToken] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  // Stable across retries of the same generate intent (see web/CLAUDE.md → Idempotency).
  const idempotencyKey = useRef(crypto.randomUUID());

  async function generate() {
    setError(null);
    try {
      const res = await createToken.mutateAsync({
        body: { name: HA_TOKEN_NAME, scopes: HA_SCOPES, expires_in_days: null },
        headers: { "Idempotency-Key": idempotencyKey.current },
      });
      qc.invalidateQueries({ queryKey: ["get", "/auth/tokens"] });
      idempotencyKey.current = crypto.randomUUID();
      setNewToken(res.token);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Failed to generate token.");
    }
  }

  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-xs font-semibold text-muted-foreground uppercase tracking-wide mb-1">
          Home Assistant
        </h2>
        <p className="text-sm text-muted-foreground">
          Control Hearth from Home Assistant automations and the Assist voice assistant — add
          groceries, create to-dos, check in habits, and read your to-do count. HA calls Hearth&apos;s
          REST API directly; no custom component needed.
        </p>
      </div>

      <div className="border rounded-lg bg-card p-4 space-y-4">
        <div className="flex items-start gap-3">
          <div className="mt-0.5 shrink-0 rounded-md bg-primary/10 p-2">
            <Zap className="h-4 w-4 text-primary" />
          </div>
          <div className="space-y-1">
            <p className="text-sm font-medium">Generate a Home Assistant token</p>
            <p className="text-xs text-muted-foreground">
              Creates a scoped access token (grocery, to-dos, habits — write) named
              &quot;Home Assistant&quot;. It never expires and can be revoked any time under
              Access tokens.
            </p>
          </div>
        </div>

        {newToken ? (
          <NewHaTokenReveal token={newToken} />
        ) : (
          <>
            {error && <p className="text-sm text-destructive">{error}</p>}
            <button
              type="button"
              onClick={generate}
              disabled={createToken.isPending}
              className={cn(
                "flex items-center gap-1.5 px-4 py-2 rounded-md text-sm font-medium transition-colors",
                createToken.isPending
                  ? "bg-muted text-muted-foreground cursor-not-allowed"
                  : "bg-primary text-primary-foreground hover:bg-primary/90",
              )}
            >
              {createToken.isPending ? (
                <>
                  <Loader2 className="h-3.5 w-3.5 animate-spin" /> Generating…
                </>
              ) : (
                <>
                  <Zap className="h-3.5 w-3.5" /> Generate Home Assistant token
                </>
              )}
            </button>
          </>
        )}
      </div>

      <a
        href="https://github.com/brandon-olin/life-dashboard/blob/main/docs/home-assistant-setup.md"
        target="_blank"
        rel="noreferrer"
        className="inline-flex items-center gap-1.5 text-sm text-primary hover:underline"
      >
        <ExternalLink className="h-3.5 w-3.5" /> Full setup guide (configuration.yaml, sensor, voice intents)
      </a>
    </div>
  );
}
