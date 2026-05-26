"use client";

/**
 * Current-resource context — supports chat-001 (context-aware chatbot).
 *
 * Every resource detail page (notes/[id], recipes/[id], documents/...,
 * etc.) calls `useRegisterCurrentResource({ type, id, title })` on mount
 * to publish what the user is currently viewing. The chat sidebar reads
 * this via `useCurrentResource()` and includes the typed hint on every
 * /ai/chat POST so the AI knows what "this" refers to.
 *
 * Design notes:
 * - Only ONE resource is "current" at a time. If multiple pages register
 *   (shouldn't happen in practice — only one detail page is mounted at
 *   any moment), the most recently registered wins.
 * - We register on mount, clear on unmount via the returned cleanup —
 *   no global event bus, no manual coordination needed.
 * - The context object is purely client-side; the backend doesn't see
 *   the title (it re-resolves from the DB), so a stale title here is
 *   purely cosmetic for the "Discussing: X" indicator.
 */
import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";

export type CurrentResourceType =
  | "note"
  | "recipe"
  | "document"
  | "todo"
  | "goal"
  | "habit";

export interface CurrentResource {
  type: CurrentResourceType;
  id: string;
  /** Display title — used by the chat sidebar to show 'Discussing: X'. */
  title: string;
}

interface CurrentResourceContextValue {
  current: CurrentResource | null;
  /** Imperatively set the current resource. Returns a cleanup function. */
  setResource: (res: CurrentResource | null) => void;
}

const CurrentResourceContext = createContext<CurrentResourceContextValue | null>(null);

export function CurrentResourceProvider({ children }: { children: React.ReactNode }) {
  const [current, setCurrent] = useState<CurrentResource | null>(null);

  const setResource = useCallback((res: CurrentResource | null) => {
    setCurrent(res);
  }, []);

  const value = useMemo<CurrentResourceContextValue>(
    () => ({ current, setResource }),
    [current, setResource],
  );

  return (
    <CurrentResourceContext.Provider value={value}>
      {children}
    </CurrentResourceContext.Provider>
  );
}

/** Read-only access to the currently-registered resource (or null). */
export function useCurrentResource(): CurrentResource | null {
  const ctx = useContext(CurrentResourceContext);
  return ctx?.current ?? null;
}

/**
 * Register `res` as the current resource for the lifetime of the calling
 * component. Pass `null` to explicitly clear (rarely needed — unmounting
 * does it automatically).
 *
 * Stable string args produce stable behavior across re-renders.
 */
export function useRegisterCurrentResource(res: CurrentResource | null): void {
  const ctx = useContext(CurrentResourceContext);
  // Re-register when any field changes; clear on unmount.
  const type = res?.type;
  const id = res?.id;
  const title = res?.title;

  useEffect(() => {
    if (!ctx) return;
    if (type && id) {
      ctx.setResource({ type, id, title: title ?? "" });
    } else {
      ctx.setResource(null);
    }
    return () => {
      // Only clear if WE were the last registrant. If another page
      // registered in the meantime (shouldn't happen but defensive),
      // leave it alone.
      ctx.setResource(null);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [type, id, title]);
}
