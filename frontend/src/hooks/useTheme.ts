import { useCallback, useEffect, useState } from "react";

// Light/dark theme (Spec-0026/T2): initially follow the system prefers-color-scheme; save user choices in localStorage,
// and apply them to <html data-theme> to override the system preference and survive refreshes.
export type Theme = "light" | "dark";

const STORAGE_KEY = "ad-theme";

function resolveInitial(): Theme {
  try {
    const saved = localStorage.getItem(STORAGE_KEY);
    if (saved === "light" || saved === "dark") return saved;
  } catch {
    /* localStorage unavailable (private browsing, etc.) → fall back to the system preference */
  }
  return window.matchMedia?.("(prefers-color-scheme: dark)").matches ? "dark" : "light";
}

// Apply data-theme synchronously in the useState initializer to reduce first-frame flicker before commit.
function applyAndResolve(): Theme {
  const theme = resolveInitial();
  document.documentElement.setAttribute("data-theme", theme);
  return theme;
}

export function useTheme(): { theme: Theme; toggle: () => void } {
  const [theme, setTheme] = useState<Theme>(applyAndResolve);

  useEffect(() => {
    document.documentElement.setAttribute("data-theme", theme);
    try {
      localStorage.setItem(STORAGE_KEY, theme);
    } catch {
      /* Write failures are nonfatal; the theme still applies for this session */
    }
  }, [theme]);

  const toggle = useCallback(() => {
    setTheme((t) => (t === "dark" ? "light" : "dark"));
  }, []);

  return { theme, toggle };
}
