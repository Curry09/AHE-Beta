import { useCallback, useEffect, useState } from "react";

// 浅/深主题（Spec-0026/T2）：首屏跟随系统 prefers-color-scheme，用户选择记 localStorage、
// 打在 <html data-theme> 上压过系统偏好；刷新不丢。
export type Theme = "light" | "dark";

const STORAGE_KEY = "ad-theme";

function resolveInitial(): Theme {
  try {
    const saved = localStorage.getItem(STORAGE_KEY);
    if (saved === "light" || saved === "dark") return saved;
  } catch {
    /* localStorage 不可用（隐私模式等）→ 退回系统偏好 */
  }
  return window.matchMedia?.("(prefers-color-scheme: dark)").matches ? "dark" : "light";
}

// useState 初始化器里同步落 data-theme，尽量避免首帧闪烁（在提交前把属性写好）。
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
      /* 写失败不致命，主题仍在本次会话生效 */
    }
  }, [theme]);

  const toggle = useCallback(() => {
    setTheme((t) => (t === "dark" ? "light" : "dark"));
  }, []);

  return { theme, toggle };
}
