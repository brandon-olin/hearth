/**
 * proposal-002 — shared presentation rules for the approval queue.
 *
 * The queue and the dashboard widget render the same rows, so the vocabulary
 * lives here rather than being written twice and drifting.
 */
import type { components } from "@/lib/api/schema";

export type Proposal = components["schemas"]["ProposalResponse"];
export type ProposalStatus = "pending" | "approved" | "rejected" | "expired";

/** Roles that see the household's whole queue and may decide it. */
const APPROVER_ROLES = new Set(["owner", "admin"]);

export function isApprover(role: string | null | undefined): boolean {
  return APPROVER_ROLES.has(role ?? "");
}

export const STATUS_BADGE: Record<ProposalStatus, string> = {
  pending: "badge-warning",
  approved: "badge-success",
  rejected: "badge-error",
  expired: "badge-neutral badge-faded",
};

export const STATUS_LABEL: Record<ProposalStatus, string> = {
  pending: "Waiting",
  approved: "Approved",
  rejected: "Declined",
  expired: "Expired",
};

/**
 * Where the request came from. "mcp" is an implementation detail nobody outside
 * the codebase should have to know, so it reads as what it is to a household.
 */
export const SOURCE_LABEL: Record<string, string> = {
  mcp: "Agent",
  voice: "Voice",
  web: "App",
  script: "Script",
};

export function statusOf(p: Proposal): ProposalStatus {
  return (p.status as ProposalStatus) ?? "pending";
}

/** "Alice · Kitchen iPad", or just whichever of the two we have. */
export function proposerLine(p: Proposal): string {
  const who = p.proposed_by_label ?? "Someone";
  const via = p.proposed_via_label;
  return via && via !== who ? `${who} · ${via}` : who;
}

export function formatWhen(iso: string | null | undefined): string {
  if (!iso) return "";
  return new Date(iso).toLocaleString(undefined, {
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
  });
}

/**
 * How long a pending proposal has left. Deliberately coarse: the exact minute
 * does not change anyone's decision, and "in 6 days" reads faster than a date.
 */
export function expiresIn(iso: string | null | undefined): string {
  if (!iso) return "";
  const ms = new Date(iso).getTime() - Date.now();
  if (ms <= 0) return "expired";
  const days = Math.floor(ms / 86_400_000);
  if (days >= 1) return `expires in ${days} day${days === 1 ? "" : "s"}`;
  const hours = Math.max(1, Math.floor(ms / 3_600_000));
  return `expires in ${hours} hour${hours === 1 ? "" : "s"}`;
}

/**
 * The one-line account of a decision, for a proposal that has one. This is what
 * a second admin sees where the approve button would have been — the decision
 * and who made it, never a control that is already guaranteed to fail.
 */
export function decisionLine(p: Proposal): string | null {
  const status = statusOf(p);
  if (status === "pending") return null;
  const who = p.decided_by_label;
  const when = formatWhen(p.decided_at);
  if (status === "approved") {
    return who ? `Approved by ${who}${when ? ` · ${when}` : ""}` : `Approved${when ? ` · ${when}` : ""}`;
  }
  if (status === "rejected") {
    return who ? `Declined by ${who}${when ? ` · ${when}` : ""}` : `Declined${when ? ` · ${when}` : ""}`;
  }
  return when ? `Expired · ${when}` : "Expired";
}
