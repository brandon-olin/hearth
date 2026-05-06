"use client";

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useState,
} from "react";
import {
  applyThemeConfig,
  DEFAULT_CONFIG,
  loadThemeConfig,
  saveThemeConfig,
  type ThemeConfig,
} from "./presets";

type ThemeContextValue = {
  config: ThemeConfig;
  setConfig: (config: ThemeConfig) => void;
};

const ThemeContext = createContext<ThemeContextValue>({
  config: DEFAULT_CONFIG,
  setConfig: () => {},
});

export function ThemeCustomizerProvider({
  children,
}: {
  children: React.ReactNode;
}) {
  const [config, setConfigState] = useState<ThemeConfig>(DEFAULT_CONFIG);

  // On mount: load saved config and apply it immediately.
  // Inline styles on <html> override both :root {} and .dark {} stylesheet rules.
  useEffect(() => {
    const saved = loadThemeConfig();
    setConfigState(saved);
    applyThemeConfig(saved);
  }, []);

  const setConfig = useCallback((next: ThemeConfig) => {
    setConfigState(next);
    saveThemeConfig(next);
    applyThemeConfig(next);
  }, []);

  return (
    <ThemeContext.Provider value={{ config, setConfig }}>
      {children}
    </ThemeContext.Provider>
  );
}

export function useThemeCustomizer() {
  return useContext(ThemeContext);
}
