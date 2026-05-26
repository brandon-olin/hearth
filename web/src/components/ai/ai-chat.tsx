"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import {
  Bot,
  ChevronDown,
  Send,
  Loader2,
  AlertCircle,
  Plus,
  Trash2,
  MessageSquare,
  X,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { cn } from "@/lib/utils";
import { getAccessToken, setAccessToken } from "@/lib/auth/token";
import { useCurrentResource } from "@/lib/chat-context/current-resource";

// ── types ─────────────────────────────────────────────────────────────────────

type Role = "user" | "assistant";

interface Message {
  id: string;
  role: Role;
  content: string;
  streaming?: boolean;
}

interface ConversationMeta {
  id: string;
  title: string | null;
  last_message_at: string;
}

// ── helpers ───────────────────────────────────────────────────────────────────

function apiBase() {
  return typeof window !== "undefined" ? "" : (process.env.API_URL ?? "");
}

/** Return true if the JWT is missing, malformed, or expires within 60 s. */
function isTokenExpiredOrMissing(token: string | null): boolean {
  if (!token) return true;
  try {
    const payload = JSON.parse(atob(token.split(".")[1]));
    // exp is in seconds; refresh if within 60 s of expiry
    return typeof payload.exp === "number" && payload.exp * 1000 < Date.now() + 60_000;
  } catch {
    return true; // malformed — treat as expired
  }
}

/** Singleton refresh promise so concurrent callers share one network request. */
let _refreshPromise: Promise<string | null> | null = null;

async function refreshToken(): Promise<string | null> {
  if (_refreshPromise) return _refreshPromise;
  _refreshPromise = (async () => {
    try {
      const res = await fetch(`${apiBase()}/api/auth/refresh`, {
        method: "POST",
        credentials: "same-origin",
      });
      if (res.ok) {
        const data = (await res.json()) as { access_token?: string };
        if (data.access_token) {
          setAccessToken(data.access_token);
          return data.access_token;
        }
      }
    } catch {
      /* ignore */
    }
    return null;
  })().finally(() => { _refreshPromise = null; });
  return _refreshPromise;
}

async function getValidToken(): Promise<string | null> {
  const existing = getAccessToken();
  if (!isTokenExpiredOrMissing(existing)) return existing!;
  // Token missing or expired — attempt a silent refresh
  return refreshToken();
}

async function authHeaders(): Promise<Record<string, string>> {
  const token = await getValidToken();
  return token ? { Authorization: `Bearer ${token}` } : {};
}

async function fetchAiSettings(): Promise<{ has_custom_key: boolean; provider: string }> {
  const res = await fetch(`${apiBase()}/api/ai/settings`, {
    headers: await authHeaders(),
  });
  if (!res.ok) throw new Error("Failed to load AI settings");
  return res.json();
}

function relativeTime(iso: string): string {
  const diff = Date.now() - new Date(iso).getTime();
  const mins = Math.floor(diff / 60_000);
  const hours = Math.floor(diff / 3_600_000);
  const days = Math.floor(diff / 86_400_000);
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins}m ago`;
  if (hours < 24) return `${hours}h ago`;
  if (days < 7) return `${days}d ago`;
  return new Date(iso).toLocaleDateString();
}

// ── markdown renderer ─────────────────────────────────────────────────────────

function MarkdownContent({ content, streaming }: { content: string; streaming?: boolean }) {
  return (
    <div className="text-sm leading-relaxed min-w-0">
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        components={{
          p: ({ children }) => <p className="mb-2 last:mb-0">{children}</p>,
          h1: ({ children }) => (
            <h1 className="text-base font-bold mb-2 mt-3 first:mt-0">{children}</h1>
          ),
          h2: ({ children }) => (
            <h2 className="text-sm font-bold mb-2 mt-3 first:mt-0">{children}</h2>
          ),
          h3: ({ children }) => (
            <h3 className="text-sm font-semibold mb-1 mt-2 first:mt-0">{children}</h3>
          ),
          ul: ({ children }) => (
            <ul className="list-disc pl-4 mb-2 space-y-0.5">{children}</ul>
          ),
          ol: ({ children }) => (
            <ol className="list-decimal pl-4 mb-2 space-y-0.5">{children}</ol>
          ),
          li: ({ children }) => <li className="leading-relaxed">{children}</li>,
          // eslint-disable-next-line @typescript-eslint/no-explicit-any
          code: ({ inline, children, ...props }: any) =>
            inline ? (
              <code
                className="bg-background/60 rounded px-1 py-0.5 text-xs font-mono"
                {...props}
              >
                {children}
              </code>
            ) : (
              <code
                className="block bg-background/60 rounded p-2 text-xs font-mono whitespace-pre-wrap overflow-x-auto"
                {...props}
              >
                {children}
              </code>
            ),
          pre: ({ children }) => <pre className="mb-2 overflow-x-auto">{children}</pre>,
          strong: ({ children }) => <strong className="font-semibold">{children}</strong>,
          em: ({ children }) => <em className="italic">{children}</em>,
          hr: () => <hr className="border-border my-3" />,
          blockquote: ({ children }) => (
            <blockquote className="border-l-2 border-muted-foreground/30 pl-3 italic text-muted-foreground my-2">
              {children}
            </blockquote>
          ),
          a: ({ href, children }) => (
            <a
              href={href}
              className="underline underline-offset-2 hover:opacity-80"
              target="_blank"
              rel="noopener noreferrer"
            >
              {children}
            </a>
          ),
          table: ({ children }) => (
            <div className="overflow-x-auto mb-2">
              <table className="text-xs border-collapse w-full">{children}</table>
            </div>
          ),
          th: ({ children }) => (
            <th className="border border-border/50 px-2 py-1 font-semibold text-left bg-background/30">
              {children}
            </th>
          ),
          td: ({ children }) => (
            <td className="border border-border/50 px-2 py-1">{children}</td>
          ),
        }}
      >
        {content}
      </ReactMarkdown>
      {streaming && (
        <span className="inline-block w-1.5 h-4 bg-current opacity-70 ml-0.5 animate-pulse rounded-sm align-middle" />
      )}
    </div>
  );
}

// ── message bubble ────────────────────────────────────────────────────────────

function MessageBubble({ message }: { message: Message }) {
  const isUser = message.role === "user";
  return (
    <div className={cn("flex gap-3 group", isUser ? "flex-row-reverse" : "flex-row")}>
      <div
        className={cn(
          "h-7 w-7 shrink-0 rounded-full flex items-center justify-center text-xs font-semibold mt-0.5",
          isUser
            ? "bg-primary text-primary-foreground"
            : "bg-muted text-muted-foreground border border-border",
        )}
      >
        {isUser ? "You" : <Bot className="h-3.5 w-3.5" />}
      </div>
      <div
        className={cn(
          "max-w-[75%] min-w-0 rounded-2xl px-4 py-2.5",
          isUser
            ? "bg-primary text-primary-foreground rounded-tr-sm text-sm leading-relaxed whitespace-pre-wrap"
            : "bg-muted text-foreground rounded-tl-sm",
        )}
      >
        {isUser ? (
          <>
            {message.content}
            {message.streaming && (
              <span className="inline-block w-1.5 h-4 bg-current opacity-70 ml-0.5 animate-pulse rounded-sm align-middle" />
            )}
          </>
        ) : (
          <MarkdownContent content={message.content} streaming={message.streaming} />
        )}
      </div>
    </div>
  );
}

// ── empty state ───────────────────────────────────────────────────────────────

function EmptyState() {
  return (
    <div className="flex-1 flex flex-col items-center justify-center gap-3 text-center px-8 h-full">
      <div className="h-12 w-12 rounded-full bg-muted flex items-center justify-center">
        <Bot className="h-6 w-6 text-muted-foreground" />
      </div>
      <div>
        <p className="font-medium text-sm">Ask me anything</p>
        <p className="text-xs text-muted-foreground mt-1">
          I have access to your dashboard data and can help you plan, track, and organise.
        </p>
      </div>
    </div>
  );
}

// ── sidebar conversation item ─────────────────────────────────────────────────

function ConvItem({
  conv,
  active,
  onSelect,
  onDelete,
}: {
  conv: ConversationMeta;
  active: boolean;
  onSelect: () => void;
  onDelete: (e: React.MouseEvent) => void;
}) {
  return (
    // div not button — avoids nested <button> (delete is inside)
    <div
      role="button"
      tabIndex={0}
      onClick={onSelect}
      onKeyDown={(e) => (e.key === "Enter" || e.key === " ") && onSelect()}
      className={cn(
        "group w-full text-left rounded-lg px-3 py-2.5 transition-colors cursor-pointer",
        "hover:bg-accent hover:text-accent-foreground",
        active ? "bg-accent text-accent-foreground" : "text-foreground",
      )}
    >
      <div className="flex items-start justify-between gap-1">
        <p className="text-xs font-medium leading-snug line-clamp-2 flex-1">
          {conv.title || "Untitled chat"}
        </p>
        <button
          onClick={onDelete}
          className={cn(
            "shrink-0 rounded p-0.5 text-muted-foreground opacity-0 group-hover:opacity-100 transition-opacity",
            "hover:text-destructive hover:bg-destructive/10",
          )}
          aria-label="Delete conversation"
        >
          <Trash2 className="h-3 w-3" />
        </button>
      </div>
      <p className="text-[10px] text-muted-foreground mt-0.5 text-left">
        {relativeTime(conv.last_message_at)}
      </p>
    </div>
  );
}

// ── tool labels ───────────────────────────────────────────────────────────────

const TOOL_LABELS: Record<string, string> = {
  // Workouts
  create_workout: "Saving workout…",
  update_workout: "Updating workout…",
  delete_workout: "Deleting workout…",
  get_workout: "Loading workout…",
  list_workouts: "Looking up workouts…",
  // Tasks
  list_todos: "Looking up tasks…",
  create_todo: "Creating task…",
  update_todo: "Updating task…",
  delete_todo: "Deleting task…",
  // Habits
  list_habits: "Looking up habits…",
  create_habit: "Creating habit…",
  update_habit: "Updating habit…",
  delete_habit: "Deleting habit…",
  log_habit_occurrence: "Logging habit…",
  // Goals
  list_goals: "Looking up goals…",
  create_goal: "Creating goal…",
  update_goal: "Updating goal…",
  delete_goal: "Deleting goal…",
  // Notes
  list_notes: "Searching notes…",
  get_note: "Reading note…",
  create_note: "Saving note…",
  update_note: "Updating note…",
  delete_note: "Deleting note…",
  // Calendar
  list_calendar_events: "Checking calendar…",
  create_calendar_event: "Adding event…",
  update_calendar_event: "Updating event…",
  delete_calendar_event: "Removing event…",
  // Recipes
  list_recipes: "Looking up recipes…",
  get_recipe: "Loading recipe…",
  create_recipe: "Saving recipe…",
  update_recipe: "Updating recipe…",
  delete_recipe: "Deleting recipe…",
  // Contacts
  list_contacts: "Looking up contacts…",
  get_contact: "Loading contact…",
  create_contact: "Saving contact…",
  update_contact: "Updating contact…",
  delete_contact: "Deleting contact…",
  // Grocery
  list_grocery_lists: "Looking up grocery lists…",
  create_grocery_list: "Creating grocery list…",
  update_grocery_list: "Updating grocery list…",
  delete_grocery_list: "Deleting grocery list…",
  add_grocery_items: "Adding items…",
  check_grocery_item: "Checking off item…",
  update_grocery_item: "Updating item…",
  // Documents
  get_documents: "Reading document…",
  list_documents: "Browsing documents…",
  search_documents: "Searching documents…",
  create_document: "Saving document…",
  update_document: "Updating document…",
  archive_document: "Archiving document…",
  // Collections
  list_collections: "Looking up collections…",
  create_collection: "Creating collection…",
  update_collection: "Updating collection…",
  delete_collection: "Deleting collection…",
  ensure_today_collection: "Checking today's collection…",
  // Projects
  list_projects: "Looking up projects…",
  create_project: "Creating project…",
  update_project: "Updating project…",
  archive_project: "Archiving project…",
  delete_project: "Deleting project…",
  // Budget
  get_budget_summary: "Reviewing your budget…",
  list_budget_transactions: "Looking up transactions…",
  get_spending_by_category: "Analysing spending…",
  get_account_balances: "Checking account balances…",
  set_category_budget: "Updating budget target…",
};

// ── AiChat ────────────────────────────────────────────────────────────────────

export interface AiChatProps {
  /** Called when the close button is pressed (panel mode only). */
  onClose?: () => void;
}

export function AiChat({ onClose }: AiChatProps) {
  // chat-001: what resource the user is currently viewing, if any. Sent
  // with every message so the AI knows what "this" refers to.
  const currentResource = useCurrentResource();

  // Conversation list
  const [conversations, setConversations] = useState<ConversationMeta[]>([]);
  const [convsLoading, setConvsLoading] = useState(true);

  // Active chat
  const [conversationId, setConversationId] = useState<string | null>(null);
  const conversationIdRef = useRef<string | null>(null);
  const [messages, setMessages] = useState<Message[]>([]);
  const [messagesLoading, setMessagesLoading] = useState(false);

  // Input / streaming
  const [input, setInput] = useState("");
  const [sending, setSending] = useState(false);
  const [toolStatus, setToolStatus] = useState<string | null>(null);

  // Settings
  const [keyMissing, setKeyMissing] = useState(false);
  const [settingsLoading, setSettingsLoading] = useState(true);

  // Scroll
  const [showScrollBtn, setShowScrollBtn] = useState(false);
  const scrollContainerRef = useRef<HTMLDivElement>(null);
  const bottomRef = useRef<HTMLDivElement>(null);
  const atBottomRef = useRef(true);
  const forceScrollRef = useRef(false);

  const textareaRef = useRef<HTMLTextAreaElement>(null);

  // Keep ref in sync with state (for use inside async closures)
  useEffect(() => {
    conversationIdRef.current = conversationId;
  }, [conversationId]);

  // ── on mount ────────────────────────────────────────────────────────────────

  useEffect(() => {
    fetchAiSettings()
      .then((s) => { if (!s.has_custom_key) setKeyMissing(true); })
      .catch(() => {})
      .finally(() => setSettingsLoading(false));

    loadConversations(true);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // ── conversation management ─────────────────────────────────────────────────

  async function loadConversations(autoSelectFirst = false) {
    try {
      const res = await fetch(`${apiBase()}/api/ai/conversations?limit=50`, {
        headers: await authHeaders(),
      });
      if (!res.ok) return;
      const data = await res.json() as { items: ConversationMeta[] };
      setConversations(data.items);
      if (autoSelectFirst && data.items.length > 0 && !conversationIdRef.current) {
        await openConversation(data.items[0]);
      }
    } finally {
      setConvsLoading(false);
    }
  }

  async function openConversation(conv: ConversationMeta) {
    if (conversationIdRef.current === conv.id) return;
    setConversationId(conv.id);
    conversationIdRef.current = conv.id;
    setMessages([]);
    setMessagesLoading(true);
    forceScrollRef.current = true;
    try {
      const res = await fetch(`${apiBase()}/api/ai/conversations/${conv.id}`, {
        headers: await authHeaders(),
      });
      if (!res.ok) return;
      const data = await res.json() as {
        messages: Array<{ id: string; role: string; content: string }>;
      };
      setMessages(
        data.messages.map((m) => ({
          id: m.id,
          role: m.role as Role,
          content: m.content,
          streaming: false,
        })),
      );
    } finally {
      setMessagesLoading(false);
    }
  }

  async function deleteConversation(id: string, e: React.MouseEvent) {
    e.stopPropagation();
    await fetch(`${apiBase()}/api/ai/conversations/${id}`, {
      method: "DELETE",
      headers: await authHeaders(),
    });
    setConversations((prev) => prev.filter((c) => c.id !== id));
    if (conversationIdRef.current === id) {
      setMessages([]);
      setConversationId(null);
      conversationIdRef.current = null;
    }
  }

  function startNewChat() {
    setMessages([]);
    setConversationId(null);
    conversationIdRef.current = null;
    setTimeout(() => textareaRef.current?.focus(), 50);
  }

  // ── scroll ──────────────────────────────────────────────────────────────────

  const handleScroll = useCallback(() => {
    const el = scrollContainerRef.current;
    if (!el) return;
    const dist = el.scrollHeight - el.scrollTop - el.clientHeight;
    atBottomRef.current = dist < 80;
    setShowScrollBtn(dist >= 80);
  }, []);

  const scrollToBottom = useCallback(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
    atBottomRef.current = true;
    setShowScrollBtn(false);
  }, []);

  useEffect(() => {
    if (forceScrollRef.current) {
      forceScrollRef.current = false;
      requestAnimationFrame(() => {
        bottomRef.current?.scrollIntoView({ behavior: "smooth" });
        atBottomRef.current = true;
        setShowScrollBtn(false);
      });
    } else if (atBottomRef.current) {
      bottomRef.current?.scrollIntoView({ behavior: "instant" });
    }
  }, [messages]);

  // ── send ─────────────────────────────────────────────────────────────────────

  async function sendMessage() {
    const content = input.trim();
    if (!content || sending) return;

    const userMsgId = crypto.randomUUID();
    const assistantMsgId = crypto.randomUUID();
    const wasNew = conversationIdRef.current === null;

    forceScrollRef.current = true;
    setMessages((prev) => [
      ...prev,
      { id: userMsgId, role: "user", content },
      { id: assistantMsgId, role: "assistant", content: "", streaming: true },
    ]);
    setInput("");
    setSending(true);

    try {
      const chatBody = JSON.stringify({
        content,
        ...(conversationIdRef.current
          ? { conversation_id: conversationIdRef.current }
          : {}),
        // chat-001: attach the currently-viewed resource as a typed hint.
        // The backend re-resolves the title from the DB; this client-side
        // value is purely cosmetic for the 'Discussing: X' chip.
        ...(currentResource
          ? { context: { type: currentResource.type, id: currentResource.id } }
          : {}),
      });

      let res = await fetch(`${apiBase()}/api/ai/chat`, {
        method: "POST",
        headers: { "Content-Type": "application/json", ...(await authHeaders()) },
        body: chatBody,
      });

      // If the token expired between the check and the request, refresh once and retry
      if (res.status === 401) {
        const newToken = await refreshToken();
        if (newToken) {
          res = await fetch(`${apiBase()}/api/ai/chat`, {
            method: "POST",
            headers: { "Content-Type": "application/json", Authorization: `Bearer ${newToken}` },
            body: chatBody,
          });
        }
      }

      if (!res.ok) {
        const err = await res.json().catch(() => ({ detail: "Unknown error" }));
        throw new Error(err.detail ?? "Request failed");
      }

      const reader = res.body!.getReader();
      const decoder = new TextDecoder();
      let buffer = "";

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split("\n");
        buffer = lines.pop() ?? "";

        for (const line of lines) {
          if (!line.startsWith("data: ")) continue;
          const raw = line.slice(6).trim();
          if (!raw) continue;

          let event: {
            type: string;
            content?: string;
            conversation_id?: string;
            message?: string;
            tool?: string;
          };
          try {
            event = JSON.parse(raw);
          } catch {
            continue;
          }

          if (event.type === "delta" && event.content) {
            setToolStatus(null);
            setMessages((prev) =>
              prev.map((m) =>
                m.id === assistantMsgId
                  ? { ...m, content: m.content + event.content }
                  : m,
              ),
            );
          } else if (event.type === "tool_use" && event.tool) {
            const match = event.tool.match(/^rate_limited_(\d+)s$/);
            if (match) {
              setToolStatus(`Rate limit reached — retrying in ${match[1]}s…`);
            } else {
              setToolStatus(TOOL_LABELS[event.tool] ?? `Looking up ${event.tool}…`);
            }
          } else if (event.type === "done") {
            setToolStatus(null);
            if (event.conversation_id) {
              const newId = event.conversation_id;
              setConversationId(newId);
              conversationIdRef.current = newId;
            }
            setMessages((prev) =>
              prev.map((m) =>
                m.id === assistantMsgId ? { ...m, streaming: false } : m,
              ),
            );
            if (wasNew) {
              loadConversations();
            } else {
              setConversations((prev) => {
                const now = new Date().toISOString();
                const updated = prev.map((c) =>
                  c.id === conversationIdRef.current
                    ? { ...c, last_message_at: now }
                    : c,
                );
                return [...updated].sort(
                  (a, b) =>
                    new Date(b.last_message_at).getTime() -
                    new Date(a.last_message_at).getTime(),
                );
              });
            }
          } else if (event.type === "error") {
            throw new Error(event.message ?? "AI error");
          }
        }
      }
    } catch (err) {
      const msg = err instanceof Error ? err.message : "Something went wrong";
      setMessages((prev) =>
        prev.map((m) =>
          m.id === assistantMsgId
            ? { ...m, content: msg, streaming: false }
            : m,
        ),
      );
    } finally {
      setSending(false);
      textareaRef.current?.focus();
    }
  }

  function handleKeyDown(e: React.KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      sendMessage();
    }
  }

  // ── derived ──────────────────────────────────────────────────────────────────

  const activeConv = conversations.find((c) => c.id === conversationId);

  // ── conversation list (shared between sidebar and popover) ──────────────────

  const [convPopoverOpen, setConvPopoverOpen] = useState(false);

  function ConversationList() {
    return (
      <>
        {convsLoading ? (
          <div className="flex items-center justify-center py-8">
            <Loader2 className="h-4 w-4 animate-spin text-muted-foreground" />
          </div>
        ) : conversations.length === 0 ? (
          <div className="px-2 py-6 text-center">
            <MessageSquare className="h-5 w-5 text-muted-foreground mx-auto mb-2 opacity-50" />
            <p className="text-xs text-muted-foreground">No conversations yet</p>
          </div>
        ) : (
          conversations.map((conv) => (
            <ConvItem
              key={conv.id}
              conv={conv}
              active={conv.id === conversationId}
              onSelect={() => {
                openConversation(conv);
                setConvPopoverOpen(false);
              }}
              onDelete={(e) => deleteConversation(conv.id, e)}
            />
          ))
        )}
      </>
    );
  }

  // panel = onClose is provided; full-page = no onClose
  const isPanel = !!onClose;

  // ── render ───────────────────────────────────────────────────────────────────

  return (
    <div className="flex h-full overflow-hidden">

      {/* ── Persistent sidebar (full-page mode only) ──────────────────────────── */}
      {!isPanel && (
        <aside className="w-52 shrink-0 flex flex-col border-r bg-muted/30 overflow-hidden">
          <div className="p-3 border-b shrink-0">
            <Button
              variant="outline"
              size="sm"
              className="w-full justify-start gap-2 text-xs"
              onClick={startNewChat}
            >
              <Plus className="h-3.5 w-3.5" />
              New chat
            </Button>
          </div>
          <div className="flex-1 overflow-y-auto p-2 space-y-0.5">
            <ConversationList />
          </div>
        </aside>
      )}

      {/* ── Chat area ────────────────────────────────────────────────────────── */}
      <div className="flex flex-col flex-1 min-w-0">

        {/* Header */}
        <div className="flex items-center gap-2 px-4 py-3 border-b shrink-0">
          {/* Panel mode: conversations popover + new chat */}
          {isPanel && (
            <div className="relative">
              <button
                onClick={() => setConvPopoverOpen((o) => !o)}
                className={cn(
                  "flex items-center gap-1.5 rounded-md px-2 py-1 text-xs font-medium transition-colors",
                  "text-muted-foreground hover:text-foreground hover:bg-muted",
                  convPopoverOpen && "bg-muted text-foreground",
                )}
                aria-label="Conversations"
              >
                <MessageSquare className="h-3.5 w-3.5" />
                Chats
              </button>

              {convPopoverOpen && (
                <>
                  {/* Backdrop */}
                  <div
                    className="fixed inset-0 z-10"
                    onClick={() => setConvPopoverOpen(false)}
                  />
                  {/* Dropdown */}
                  <div className="absolute left-0 top-full mt-1 z-20 w-64 rounded-lg border bg-popover shadow-lg overflow-hidden">
                    <div className="p-2 border-b">
                      <Button
                        variant="ghost"
                        size="sm"
                        className="w-full justify-start gap-2 text-xs h-7"
                        onClick={() => { startNewChat(); setConvPopoverOpen(false); }}
                      >
                        <Plus className="h-3.5 w-3.5" />
                        New chat
                      </Button>
                    </div>
                    <div className="max-h-72 overflow-y-auto p-1.5 space-y-0.5">
                      <ConversationList />
                    </div>
                  </div>
                </>
              )}
            </div>
          )}

          <Bot className="h-4 w-4 text-muted-foreground shrink-0" />
          <span className="text-sm font-semibold truncate flex-1">
            {activeConv?.title ?? (conversationId ? "Chat" : "AI Assistant")}
          </span>

          {/* New chat button in panel header */}
          {isPanel && (
            <button
              onClick={startNewChat}
              className="shrink-0 rounded-md p-1 text-muted-foreground hover:text-foreground hover:bg-muted transition-colors"
              aria-label="New chat"
            >
              <Plus className="h-4 w-4" />
            </button>
          )}

          {onClose && (
            <button
              onClick={onClose}
              className="shrink-0 rounded-md p-1 text-muted-foreground hover:text-foreground hover:bg-muted transition-colors"
              aria-label="Close"
            >
              <X className="h-4 w-4" />
            </button>
          )}
        </div>

        {/* Key missing banner */}
        {!settingsLoading && keyMissing && (
          <div className="mx-4 mt-3 flex items-start gap-2 rounded-lg border border-amber-200 bg-amber-50 dark:border-amber-900 dark:bg-amber-950/30 px-3 py-2.5 text-xs text-amber-800 dark:text-amber-300 shrink-0">
            <AlertCircle className="h-3.5 w-3.5 mt-0.5 shrink-0" />
            <span>
              No API key configured.{" "}
              <a href="/settings" className="underline font-medium">
                Settings → AI
              </a>
            </span>
          </div>
        )}

        {/* Messages */}
        <div
          ref={scrollContainerRef}
          className="flex-1 overflow-y-auto px-4 py-4 relative"
          onScroll={handleScroll}
        >
          {messagesLoading ? (
            <div className="flex items-center justify-center h-full">
              <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
            </div>
          ) : messages.length === 0 ? (
            <EmptyState />
          ) : (
            <div className="space-y-4">
              {messages.map((m) => (
                <MessageBubble key={m.id} message={m} />
              ))}
              <div ref={bottomRef} />
            </div>
          )}

          {showScrollBtn && (
            <div className="sticky bottom-4 flex justify-center pointer-events-none">
              <button
                onClick={scrollToBottom}
                className={cn(
                  "pointer-events-auto rounded-full bg-background border border-border shadow-md",
                  "p-2 text-muted-foreground hover:text-foreground transition-all",
                  "animate-in fade-in slide-in-from-bottom-2 duration-150",
                )}
                aria-label="Scroll to bottom"
              >
                <ChevronDown className="h-4 w-4" />
              </button>
            </div>
          )}
        </div>

        {/* Tool status */}
        {toolStatus && (
          <div className="shrink-0 px-4 pb-1">
            <div className="flex items-center gap-2 text-xs text-muted-foreground">
              <Loader2 className="h-3 w-3 animate-spin" />
              {toolStatus}
            </div>
          </div>
        )}

        {/* chat-001: 'Discussing:' chip — shows the user that the AI is
            aware of what they're currently viewing. Hidden when no
            resource is registered, so general chat is unchanged. */}
        {currentResource && (
          <div className="shrink-0 px-4 pt-1">
            <div className="inline-flex items-center gap-1.5 text-xs text-muted-foreground bg-muted/40 border border-border rounded-full px-2.5 py-0.5">
              <span className="text-[10px] uppercase tracking-wide opacity-70">
                Discussing
              </span>
              <span className="font-medium text-foreground truncate max-w-[14rem]">
                {currentResource.title || `${currentResource.type} ${currentResource.id.slice(0, 8)}`}
              </span>
            </div>
          </div>
        )}

        {/* Input */}
        <div className="shrink-0 border-t bg-background px-4 py-3">
          <div className="flex items-end gap-2">
            <Textarea
              ref={textareaRef}
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={handleKeyDown}
              placeholder="Ask anything… (Enter to send)"
              className="resize-none min-h-[40px] max-h-40 text-sm"
              rows={1}
              disabled={sending || settingsLoading}
            />
            <Button
              size="icon"
              onClick={sendMessage}
              disabled={!input.trim() || sending || settingsLoading}
              className="shrink-0 h-10 w-10"
            >
              {sending ? (
                <Loader2 className="h-4 w-4 animate-spin" />
              ) : (
                <Send className="h-4 w-4" />
              )}
            </Button>
          </div>
          <p className="text-[10px] text-muted-foreground text-center mt-1.5">
            AI can make mistakes. Verify important information.
          </p>
        </div>
      </div>
    </div>
  );
}
