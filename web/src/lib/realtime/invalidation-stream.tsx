"use client";

/**
 * realtime-001 — subscribes to the server's Server-Sent-Events invalidation
 * stream and turns each event into a React Query cache invalidation, so a write
 * on one device makes this device refetch the affected queries.
 *
 * Why a fetch reader instead of the browser `EventSource` API: EventSource
 * cannot send an Authorization header, and Hearth authenticates with an
 * in-memory Bearer token (not a cookie). We read `text/event-stream` off a
 * `fetch` ReadableStream and attach the token ourselves. Works identically in
 * the web build (through the Next.js proxy, which pipes SSE unbuffered) and the
 * Tauri desktop build (direct to the sidecar via apiBaseUrl).
 *
 * Mounted once inside the authenticated shell (see the protected layout).
 */
import { useQueryClient } from "@tanstack/react-query";
import { useEffect } from "react";

import { apiBaseUrl } from "@/lib/api/client";
import { useAuth } from "@/lib/auth/context";
import { getAccessToken } from "@/lib/auth/token";
import { prefixesForEntityType } from "@/lib/realtime/invalidation-map";

/** Reconnect backoff bounds (ms). */
const RECONNECT_MIN_MS = 1_000;
const RECONNECT_MAX_MS = 30_000;

interface InvalidationMessage {
  type: string;
  id: string;
  action: string;
}

export function InvalidationStream() {
  const { user } = useAuth();
  const queryClient = useQueryClient();
  const userId = user?.id ?? null;

  useEffect(() => {
    // Only run for an authenticated member; the effect re-subscribes if the
    // signed-in user changes (e.g. dev impersonation).
    if (!userId) return;

    const controller = new AbortController();
    let closed = false;
    let backoff = RECONNECT_MIN_MS;

    function invalidateForEntity(entityType: string) {
      const prefixes = prefixesForEntityType(entityType);
      if (prefixes.length === 0) return;
      queryClient.invalidateQueries({
        predicate: (query) => {
          const path = query.queryKey[1];
          return typeof path === "string" && prefixes.some((p) => path.startsWith(p));
        },
      });
    }

    function handleFrame(frame: string) {
      let eventName = "message";
      const dataLines: string[] = [];
      for (const line of frame.split("\n")) {
        if (line.startsWith(":")) continue; // comment / heartbeat
        if (line.startsWith("event:")) eventName = line.slice(6).trim();
        else if (line.startsWith("data:")) dataLines.push(line.slice(5).trim());
      }
      if (dataLines.length === 0) return;

      if (eventName === "resync") {
        // The server dropped events for a stalled connection — refetch broadly.
        queryClient.invalidateQueries();
        return;
      }
      if (eventName !== "invalidate") return;
      try {
        const msg = JSON.parse(dataLines.join("\n")) as InvalidationMessage;
        if (msg?.type) invalidateForEntity(msg.type);
      } catch {
        // Malformed frame — ignore rather than break the stream loop.
      }
    }

    async function connectOnce(): Promise<void> {
      const token = getAccessToken();
      if (!token) return; // no credential yet; the retry loop will try again

      const res = await fetch(`${apiBaseUrl}/realtime/stream`, {
        headers: { Authorization: `Bearer ${token}`, Accept: "text/event-stream" },
        signal: controller.signal,
      });
      if (!res.ok || !res.body) {
        throw new Error(`stream failed: ${res.status}`);
      }

      // A successful connect resets the backoff for the next disconnect.
      backoff = RECONNECT_MIN_MS;

      const reader = res.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";
      for (;;) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        // SSE frames are separated by a blank line.
        let sep: number;
        while ((sep = buffer.indexOf("\n\n")) !== -1) {
          handleFrame(buffer.slice(0, sep));
          buffer = buffer.slice(sep + 2);
        }
      }
    }

    async function run() {
      while (!closed) {
        try {
          await connectOnce();
        } catch (err) {
          if (closed || (err instanceof Error && err.name === "AbortError")) return;
          // fall through to backoff + retry
        }
        if (closed) return;
        await new Promise((r) => setTimeout(r, backoff));
        backoff = Math.min(backoff * 2, RECONNECT_MAX_MS);
      }
    }

    void run();
    return () => {
      closed = true;
      controller.abort();
    };
  }, [userId, queryClient]);

  return null;
}
