import { useEffect, useState } from "react";

export type ThemePreference = "light" | "dark" | "system";

const THEME_STORAGE_KEY = "promptatelier.theme/v1";

function readPreference(): ThemePreference {
  try {
    const saved = window.localStorage?.getItem(THEME_STORAGE_KEY);
    if (saved === "light" || saved === "dark" || saved === "system") return saved;
  } catch {
    // 隐私模式等情况下 localStorage 不可用，按跟随系统处理。
  }
  return "system";
}

function systemPrefersDark(): boolean {
  return typeof window.matchMedia === "function" && window.matchMedia("(prefers-color-scheme: dark)").matches;
}

function applyTheme(preference: ThemePreference) {
  const dark = preference === "dark" || (preference === "system" && systemPrefersDark());
  document.documentElement.dataset.theme = dark ? "dark" : "light";
}

/** 主题偏好：浅色 / 深色 / 跟随系统；写到 <html data-theme>，tokens.css 按它切换变量。 */
export function useThemePreference(): [ThemePreference, (next: ThemePreference) => void] {
  const [preference, setPreference] = useState<ThemePreference>(readPreference);

  useEffect(() => {
    applyTheme(preference);
    if (preference !== "system" || typeof window.matchMedia !== "function") return;
    const query = window.matchMedia("(prefers-color-scheme: dark)");
    const onChange = () => applyTheme("system");
    query.addEventListener?.("change", onChange);
    return () => query.removeEventListener?.("change", onChange);
  }, [preference]);

  const update = (next: ThemePreference) => {
    setPreference(next);
    try {
      window.localStorage?.setItem(THEME_STORAGE_KEY, next);
    } catch {
      // 存不下也照样切换，只是刷新后回到跟随系统。
    }
  };
  return [preference, update];
}
