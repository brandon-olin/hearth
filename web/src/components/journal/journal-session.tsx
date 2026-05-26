"use client";

/**
 * Journal session surface — journal-001 Phase A.
 *
 * Full-screen overlay launched from the 'Talk it out' button on today's
 * journal entry. Reuses the existing /ai/chat SSE streaming infrastructure
 * (the backend uses the journal-mode system prompt when conversation.kind
 * == 'journal') so we don't duplicate streaming logic here.
 *
 * Flow:
 *   1. Mount → POST /ai/journal/start to get the conversation_id (resumes
 *      if there's already an existing journal session for today's note).
 *   2. First-message path: the AI opens with a warm acknowledgement (the
 *      journal-mode prompt instructs 'open without a question'). We get
 *      that by sending an empty/system-style first user turn — see
 *      sendFirstTurn below.
 *   3. User sends messages → standard /ai/chat SSE stream.
 *   4. 'Finish' → POST /ai/journal/{id}/finish → render summary in an
 *      editable textarea with 'Save with transcript' toggle.
 *   5. Save → POST /ai/journal/save → appends to the target note's
 *      content_md → close overlay.
 *
 * Distinct chrome from the sidebar chat: calm background, larger text,
 * single message in flight, gentle exchange counter.
 */
import { useCallback, useEffect, useRef, useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { Loader2, Send, X, Sparkles, AlertCircle } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { cn } from "@/lib/utils";
import { apiBaseUrl } from "@/lib/api/client";
import { getAccessToken } from "@/lib/auth/token";

type Role = "user" | "assistant";

interface Message {
  id: string;
  role: Role;
  content: string;
  streaming?: boolean;
}

export interface JournalSessionProps {
  noteId: string;
  noteTitle: string;
  /** Called when the session is dismissed without saving. */
  onClose: () => void;
  /** Called after a successful save — parent should refresh the note. */
  onSaved: (noteId: string) => void;
}

// ── Small fetch helper ───────────────────────────────────────────────────────

async function authHeaders(): Promise<Record<string, string>> {
  const t = getAccessToken();
  return t ? { Authorization: `Bearer ${t}` } : {};
}

async function jpost<T>(path: string, body?: unknown): Promise<T> {
  const res = await fetch(`${apiBaseUrl}${path}`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      ...(await authHeaders()),
    },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  if (!res.ok) {
    const text = await res.text().catch(() => "");
    throw new Error(text || `Request failed (${res.status})`);
  }
  return (await res.json()) as T;
}

// ── Component ────────────────────────────────────────────────────────────────

type Phase = "loading" | "conversation" | "synthesizing" | "review" | "saving";

export function JournalSession({ noteId, noteTitle, onClose, onSaved }: JournalSessionProps) {
  const [phase, setPhase] = useState<Phase>("loading");
  const [conversationId, setConversationId] = useState<string | null>(null);
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState("");
  const [sending, setSending] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Synthesis / save state
  const [summary, setSummary] = useState("");
  const [includeTranscript, setIncludeTranscript] = useState(false);

  const scrollRef = useRef<HTMLDivElement>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  // Auto-grow the textarea up to 50% of viewport height as the user types.
  // The journal mode invites longer-form writing than the sidebar chat —
  // the constrained 10rem max felt cramped during rants. Approach:
  //   1. Reset height to 'auto' so scrollHeight reflects only content
  //   2. Set height to min(scrollHeight, 50vh) in pixels
  // Runs on every input change. Cheap — no observers, no measurement libs.
  useEffect(() => {
    const ta = textareaRef.current;
    if (!ta) return;
    ta.style.height = "auto";
    const max = Math.floor(window.innerHeight * 0.5);
    ta.style.height = Math.min(ta.scrollHeight, max) + "px";
  }, [input]);

  // ── Start (or resume) the session on mount ──────────────────────────────────
  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const resp = await jpost<{
          conversation_id: string;
          is_new: boolean;
          opening_message: string | null;
        }>("/ai/journal/start", { note_id: noteId });
        if (cancelled) return;
        setConversationId(resp.conversation_id);

        // journal-001 Phase B: render the AI's personalized opener
        // (already saved server-side as the first assistant turn) so
        // the user arrives at a non-empty conversation. Resumed
        // sessions: opening_message is null and we just show the empty
        // surface; the existing transcript is already on the backend
        // and will show up when the user sends the next turn.
        if (resp.is_new && resp.opening_message) {
          setMessages([
            {
              id: crypto.randomUUID(),
              role: "assistant",
              content: resp.opening_message,
            },
          ]);
        }
        setPhase("conversation");
      } catch (e) {
        if (!cancelled) {
          setError(e instanceof Error ? e.message : "Failed to start session");
          setPhase("conversation");
        }
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [noteId]);

  // ── Autoscroll on new messages ──────────────────────────────────────────────
  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: "smooth" });
  }, [messages]);

  // ── Send a turn (streaming) ────────────────────────────────────────────────
  const sendMessage = useCallback(async () => {
    const content = input.trim();
    if (!content || sending || !conversationId) return;

    const userMsgId = crypto.randomUUID();
    const assistantMsgId = crypto.randomUUID();
    setMessages((prev) => [
      ...prev,
      { id: userMsgId, role: "user", content },
      { id: assistantMsgId, role: "assistant", content: "", streaming: true },
    ]);
    setInput("");
    setSending(true);
    setError(null);

    try {
      const body = JSON.stringify({
        content,
        conversation_id: conversationId,
      });
      const res = await fetch(`${apiBaseUrl}/ai/chat`, {
        method: "POST",
        headers: { "Content-Type": "application/json", ...(await authHeaders()) },
        body,
      });
      if (!res.ok) {
        const text = await res.text().catch(() => "");
        throw new Error(text || "Request failed");
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
          if (!line.startsWith("data:")) continue;
          const data = line.slice(5).trim();
          if (!data) continue;
          try {
            const evt = JSON.parse(data) as { type: string; content?: string; message?: string };
            if (evt.type === "delta" && evt.content) {
              setMessages((prev) =>
                prev.map((m) =>
                  m.id === assistantMsgId
                    ? { ...m, content: m.content + (evt.content ?? "") }
                    : m,
                ),
              );
            } else if (evt.type === "done") {
              setMessages((prev) =>
                prev.map((m) =>
                  m.id === assistantMsgId ? { ...m, streaming: false } : m,
                ),
              );
            } else if (evt.type === "error") {
              setError(evt.message ?? "Stream error");
            }
          } catch {
            // ignore malformed event lines
          }
        }
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : "Send failed");
      setMessages((prev) => prev.filter((m) => m.id !== assistantMsgId));
    } finally {
      setSending(false);
      setMessages((prev) =>
        prev.map((m) => (m.id === assistantMsgId ? { ...m, streaming: false } : m)),
      );
      setTimeout(() => textareaRef.current?.focus(), 50);
    }
  }, [input, sending, conversationId]);

  // ── Finish → synthesize summary ────────────────────────────────────────────
  const finishSession = useCallback(async () => {
    if (!conversationId || phase !== "conversation") return;
    setPhase("synthesizing");
    setError(null);
    try {
      const resp = await jpost<{ summary_md: string }>(
        `/ai/journal/${conversationId}/finish`,
      );
      setSummary(resp.summary_md);
      setPhase("review");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to synthesize");
      setPhase("conversation");
    }
  }, [conversationId, phase]);

  // ── Save → append to note ──────────────────────────────────────────────────
  const saveSession = useCallback(async () => {
    if (!conversationId || !summary.trim()) return;
    setPhase("saving");
    setError(null);
    try {
      await jpost<{ note_id: string }>("/ai/journal/save", {
        conversation_id: conversationId,
        content_md: summary,
        include_transcript: includeTranscript,
      });
      onSaved(noteId);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Save failed");
      setPhase("review");
    }
  }, [conversationId, summary, includeTranscript, onSaved, noteId]);

  // ── Render ─────────────────────────────────────────────────────────────────
  const exchangeCount = messages.filter((m) => m.role === "user").length;

  return (
    <div className="fixed inset-0 z-50 bg-background/95 backdrop-blur-sm flex flex-col">
      {/* Header */}
      <div className="shrink-0 border-b border-border px-6 py-3 flex items-center gap-3">
        <Sparkles className="h-4 w-4 text-primary" />
        <div className="min-w-0 flex-1">
          <p className="text-sm font-medium truncate">Talk it out · {noteTitle}</p>
          {phase === "conversation" && (
            <p className="text-[11px] text-muted-foreground">
              {exchangeCount === 0
                ? "Take your time. Start wherever you want."
                : `${exchangeCount} exchange${exchangeCount === 1 ? "" : "s"}`}
            </p>
          )}
          {phase === "synthesizing" && (
            <p className="text-[11px] text-muted-foreground">Pulling it together…</p>
          )}
          {phase === "review" && (
            <p className="text-[11px] text-muted-foreground">Review and save</p>
          )}
        </div>
        {phase === "conversation" && exchangeCount >= 1 && (
          <Button size="sm" variant="ghost" onClick={finishSession} disabled={sending}>
            Finish
          </Button>
        )}
        <Button
          size="sm"
          variant="ghost"
          onClick={onClose}
          aria-label="Close without saving"
          className="h-8 w-8 p-0"
        >
          <X className="h-4 w-4" />
        </Button>
      </div>

      {/* Conversation phase */}
      {(phase === "conversation" || phase === "loading") && (
        <>
          <div ref={scrollRef} className="flex-1 overflow-y-auto px-6 py-6">
            <div className="max-w-2xl mx-auto space-y-4">
              {phase === "loading" && (
                <div className="text-sm text-muted-foreground flex items-center gap-2">
                  <Loader2 className="h-4 w-4 animate-spin" /> Starting session…
                </div>
              )}
              {messages.length === 0 && phase === "conversation" && (
                // Shown only when the session was resumed (no opener
                // re-fired) OR the opener generation failed and the
                // fallback also somehow returned empty. New sessions
                // arrive with the AI's personalized opener already in
                // the messages array.
                <p className="text-base text-muted-foreground italic">
                  Picking back up. Take your time.
                </p>
              )}
              {messages.map((m) => (
                <div
                  key={m.id}
                  className={cn(
                    "rounded-lg px-4 py-3 text-[15px] leading-relaxed",
                    m.role === "user"
                      ? "bg-primary/10 text-foreground"
                      : "bg-muted/30 text-foreground",
                  )}
                >
                  {m.role === "assistant" ? (
                    <div className="prose prose-sm max-w-none dark:prose-invert">
                      <ReactMarkdown remarkPlugins={[remarkGfm]}>
                        {m.content || "…"}
                      </ReactMarkdown>
                    </div>
                  ) : (
                    <p className="whitespace-pre-wrap">{m.content}</p>
                  )}
                  {m.streaming && (
                    <span className="inline-block w-2 h-4 bg-muted-foreground/40 animate-pulse ml-1" />
                  )}
                </div>
              ))}
              {error && (
                <div className="text-xs text-destructive flex items-center gap-1.5">
                  <AlertCircle className="h-3.5 w-3.5" /> {error}
                </div>
              )}
            </div>
          </div>

          {/* Input bar */}
          <div className="shrink-0 border-t border-border px-6 py-4">
            <div className="max-w-2xl mx-auto flex items-end gap-2">
              <Textarea
                ref={textareaRef}
                value={input}
                onChange={(e) => setInput(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter" && !e.shiftKey) {
                    e.preventDefault();
                    sendMessage();
                  }
                }}
                placeholder="What's on your mind?"
                // Auto-grow handled by the useEffect above (caps at 50vh).
                // overflow-y-auto kicks in only once the cap is reached.
                className="resize-none min-h-[48px] overflow-y-auto text-[15px] leading-relaxed"
                rows={1}
                disabled={sending || phase !== "conversation"}
                autoFocus
              />
              <Button
                size="icon"
                onClick={sendMessage}
                disabled={!input.trim() || sending || phase !== "conversation"}
                className="shrink-0 h-12 w-12"
              >
                {sending ? <Loader2 className="h-4 w-4 animate-spin" /> : <Send className="h-4 w-4" />}
              </Button>
            </div>
          </div>
        </>
      )}

      {/* Synthesizing phase */}
      {phase === "synthesizing" && (
        <div className="flex-1 flex items-center justify-center">
          <div className="text-center space-y-3">
            <Loader2 className="h-8 w-8 animate-spin text-muted-foreground mx-auto" />
            <p className="text-sm text-muted-foreground">Pulling together what came out of this…</p>
          </div>
        </div>
      )}

      {/* Review / save phase */}
      {(phase === "review" || phase === "saving") && (
        <div className="flex-1 overflow-y-auto px-6 py-6">
          <div className="max-w-2xl mx-auto space-y-4">
            <div>
              <p className="text-xs font-medium text-muted-foreground uppercase tracking-wider mb-2">
                Today's entry (edit anything before saving)
              </p>
              <Textarea
                value={summary}
                onChange={(e) => setSummary(e.target.value)}
                rows={14}
                className="w-full text-[15px] leading-relaxed resize-y min-h-[18rem]"
                disabled={phase === "saving"}
              />
            </div>

            <label className="flex items-start gap-2 text-sm cursor-pointer">
              <input
                type="checkbox"
                className="checkbox-themed mt-0.5 h-4 w-4 shrink-0"
                checked={includeTranscript}
                onChange={(e) => setIncludeTranscript(e.target.checked)}
                disabled={phase === "saving"}
              />
              <span>
                <span className="font-medium">Save with transcript</span>
                <span className="text-muted-foreground ml-2">
                  Append the full conversation below the summary, separated by a divider.
                </span>
              </span>
            </label>

            {error && (
              <div className="text-xs text-destructive flex items-center gap-1.5">
                <AlertCircle className="h-3.5 w-3.5" /> {error}
              </div>
            )}

            <div className="flex items-center gap-2 pt-2">
              <Button onClick={saveSession} disabled={phase === "saving" || !summary.trim()}>
                {phase === "saving" ? <Loader2 className="h-4 w-4 animate-spin" /> : "Save"}
              </Button>
              <Button
                variant="ghost"
                onClick={() => setPhase("conversation")}
                disabled={phase === "saving"}
              >
                Keep talking
              </Button>
              <Button
                variant="ghost"
                onClick={onClose}
                disabled={phase === "saving"}
                className="ml-auto text-muted-foreground"
              >
                Don't save this session
              </Button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
