"use client";

/**
 * proposal-002 — one row of the approval queue.
 *
 * The whole design rule for this component: **never render a control that is
 * already known to fail.** Routing is all-admins and first-to-decide wins, so a
 * second admin can arrive at a proposal someone else just decided. When that
 * happens they read the decision and who made it, not an approve button that
 * would 409. The realtime stream makes that swap happen live, without a reload.
 */
import { useState } from "react";
import { Check, Loader2, ShieldQuestion, X } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { cn } from "@/lib/utils";
import {
  type Proposal,
  SOURCE_LABEL,
  STATUS_BADGE,
  STATUS_LABEL,
  decisionLine,
  expiresIn,
  formatWhen,
  proposerLine,
  statusOf,
} from "@/lib/proposals/format";

interface Props {
  proposal: Proposal;
  /** Whether this member may decide (owner/admin). */
  canDecide: boolean;
  onApprove: (id: string) => Promise<void>;
  onReject: (id: string, reason: string) => Promise<void>;
  /** Set while any decision on this row is in flight. */
  busy?: boolean;
  /** The message shown when a decision was refused (e.g. someone was first). */
  error?: string | null;
  compact?: boolean;
}

export function ProposalRow({
  proposal,
  canDecide,
  onApprove,
  onReject,
  busy = false,
  error = null,
  compact = false,
}: Props) {
  const [rejecting, setRejecting] = useState(false);
  const [reason, setReason] = useState("");

  const status = statusOf(proposal);
  const decided = decisionLine(proposal);
  const actionable = status === "pending" && canDecide;

  return (
    <div className={cn("py-3", !compact && "border-b last:border-b-0")}>
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2 min-w-0">
            <ShieldQuestion className="h-3.5 w-3.5 shrink-0 text-muted-foreground" />
            <span className="text-sm font-medium truncate">{proposal.summary}</span>
          </div>
          <p className="mt-1 text-xs text-muted-foreground">
            {proposerLine(proposal)}
            {" · "}
            {SOURCE_LABEL[proposal.source] ?? proposal.source}
            {" · "}
            {proposal.domain}
            {" · "}
            {formatWhen(proposal.created_at)}
            {status === "pending" && proposal.expires_at
              ? ` · ${expiresIn(proposal.expires_at)}`
              : ""}
          </p>
        </div>
        <span className={cn("badge shrink-0", STATUS_BADGE[status])}>
          {STATUS_LABEL[status]}
        </span>
      </div>

      {/* A decided proposal shows its decision here — this is the slot the
          approve/reject buttons occupied while it was pending. */}
      {decided && <p className="mt-2 text-xs text-muted-foreground">{decided}</p>}
      {proposal.reject_reason && status !== "pending" && (
        <p className="mt-1 text-xs text-muted-foreground italic">
          “{proposal.reject_reason}”
        </p>
      )}

      {status === "pending" && !canDecide && (
        <p className="mt-2 text-xs text-muted-foreground">
          Waiting on a household admin.
        </p>
      )}

      {error && <p className="mt-2 text-xs text-destructive">{error}</p>}

      {actionable && !rejecting && (
        <div className="mt-2 flex items-center gap-2">
          <Button size="sm" disabled={busy} onClick={() => void onApprove(proposal.id)}>
            {busy ? (
              <Loader2 className="h-3.5 w-3.5 animate-spin" />
            ) : (
              <Check className="h-3.5 w-3.5" />
            )}
            Approve
          </Button>
          <Button
            size="sm"
            variant="outline"
            disabled={busy}
            onClick={() => setRejecting(true)}
          >
            <X className="h-3.5 w-3.5" />
            Decline
          </Button>
        </div>
      )}

      {actionable && rejecting && (
        <div className="mt-2 space-y-2">
          <Textarea
            value={reason}
            onChange={(e) => setReason(e.target.value)}
            maxLength={500}
            rows={2}
            placeholder="Why not? The agent can relay this back to whoever asked."
          />
          <div className="flex items-center gap-2">
            <Button
              size="sm"
              variant="destructive"
              disabled={busy}
              onClick={async () => {
                await onReject(proposal.id, reason.trim());
                setRejecting(false);
                setReason("");
              }}
            >
              {busy && <Loader2 className="h-3.5 w-3.5 animate-spin" />}
              Decline
            </Button>
            <Button
              size="sm"
              variant="ghost"
              disabled={busy}
              onClick={() => {
                setRejecting(false);
                setReason("");
              }}
            >
              Cancel
            </Button>
          </div>
        </div>
      )}
    </div>
  );
}
