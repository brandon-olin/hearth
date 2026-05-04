"use client";

import { useTheme } from "next-themes";
import { useEffect, useState } from "react";

function SunIcon({ className }: { className?: string }) {
  return (
    <svg
      className={className}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      aria-hidden="true"
    >
      <circle cx="12" cy="12" r="4" />
      <line x1="12" y1="2" x2="12" y2="5" />
      <line x1="12" y1="19" x2="12" y2="22" />
      <line x1="2" y1="12" x2="5" y2="12" />
      <line x1="19" y1="12" x2="22" y2="12" />
      <line x1="4.93" y1="4.93" x2="7.05" y2="7.05" />
      <line x1="16.95" y1="16.95" x2="19.07" y2="19.07" />
      <line x1="4.93" y1="19.07" x2="7.05" y2="16.95" />
      <line x1="16.95" y1="7.05" x2="19.07" y2="4.93" />
    </svg>
  );
}

function MoonIcon({ className }: { className?: string }) {
  return (
    <svg
      className={className}
      viewBox="0 0 20 20"
      fill="currentColor"
      aria-hidden="true"
    >
      <path
        fillRule="evenodd"
        d="M7.455 2.004a.75.75 0 01.26.77 7 7 0 009.958 7.967.75.75 0 011.067.853A8.5 8.5 0 1110.5 1.5a.75.75 0 01-.045.504z"
        clipRule="evenodd"
      />
    </svg>
  );
}

const TRANSITION_MS = 350;

export function ThemeToggle() {
  const { resolvedTheme, setTheme } = useTheme();
  const [mounted, setMounted] = useState(false);

  useEffect(() => setMounted(true), []);

  // Reserve space while unmounted to avoid layout shift
  if (!mounted) return <div className="h-6 w-11 shrink-0" />;

  const isDark = resolvedTheme === "dark";
  const ariaChecked: "true" | "false" = isDark ? "true" : "false";

  function toggle() {
    const html = document.documentElement;
    html.classList.add("theme-switching");
    setTheme(isDark ? "light" : "dark");
    setTimeout(() => html.classList.remove("theme-switching"), TRANSITION_MS);
  }

  return (
    <button
      type="button"
      role="switch"
      aria-checked={ariaChecked}
      aria-label={isDark ? "Switch to light mode" : "Switch to dark mode"}
      onClick={toggle}
      className="relative inline-flex h-6 w-11 shrink-0 cursor-pointer items-center rounded-full border border-gray-300 bg-gray-200 transition-colors duration-200 dark:border-gray-600 dark:bg-gray-700"
    >
      <span
        className={`inline-flex h-5 w-5 items-center justify-center rounded-full bg-white shadow transition-transform duration-300 dark:bg-gray-900 ${
          isDark ? "translate-x-5" : "translate-x-0"
        }`}
      >
        {isDark ? (
          <MoonIcon className="h-3 w-3 text-white" />
        ) : (
          <SunIcon className="h-3 w-3 text-gray-700" />
        )}
      </span>
    </button>
  );
}
