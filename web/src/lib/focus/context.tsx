"use client";

import { createContext, useCallback, useContext, useState } from "react";

interface FocusModeContextValue {
  focused: boolean;
  toggle: () => void;
  enter: () => void;
  exit: () => void;
}

const FocusModeContext = createContext<FocusModeContextValue>({
  focused: false,
  toggle: () => {},
  enter: () => {},
  exit: () => {},
});

const FOCUS_PHRASES = [
  "let the words flow",
  "just write",
  "tune everything else out",
  "this space is yours",
  "no distractions, only words",
];

export function FocusModeProvider({ children }: { children: React.ReactNode }) {
  const [focused, setFocused] = useState(false);

  const enter  = useCallback(() => setFocused(true),  []);
  const exit   = useCallback(() => setFocused(false), []);
  const toggle = useCallback(() => setFocused((f) => !f), []);

  return (
    <FocusModeContext.Provider value={{ focused, toggle, enter, exit }}>
      {children}
    </FocusModeContext.Provider>
  );
}

export function useFocusMode() {
  return useContext(FocusModeContext);
}

export { FOCUS_PHRASES };
