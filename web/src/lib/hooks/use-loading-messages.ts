import { useState, useEffect } from "react";

function shuffle<T>(arr: T[]): T[] {
  const a = [...arr];
  for (let i = a.length - 1; i > 0; i--) {
    const j = Math.floor(Math.random() * (i + 1));
    [a[i], a[j]] = [a[j], a[i]];
  }
  return a;
}

/**
 * Cycles through a shuffled list of messages on a fixed interval.
 * Returns the current message string.
 *
 * @param messages - Array of strings to cycle through
 * @param intervalMs - How long each message is shown (default 2500ms)
 */
export function useLoadingMessages(
  messages: string[],
  intervalMs = 2500,
): string {
  const [shuffled] = useState(() => shuffle(messages));
  const [index, setIndex] = useState(0);

  useEffect(() => {
    if (messages.length <= 1) return;
    const timer = setInterval(() => {
      setIndex((i) => (i + 1) % shuffled.length);
    }, intervalMs);
    return () => clearInterval(timer);
  }, [shuffled, messages.length, intervalMs]);

  return shuffled[index] ?? messages[0];
}
