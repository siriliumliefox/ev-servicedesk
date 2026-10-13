// Светлая/тёмная тема (Глава 6, ТЗ раздел 6 — тёмная тема инженера; глава 21, ADR 0025 п. 13).
// Тема — атрибут data-theme на <html> (см. tokens.css). Выбор пользователя — «как в системе», «светлая»
// или «тёмная» — хранится в localStorage; «как в системе» следует prefers-color-scheme.
import { useCallback, useEffect, useState } from "react";

export type ThemeName = "light" | "dark";
export type ThemePreference = ThemeName | "system";

const STORAGE_KEY = "ev-theme";
const DARK_QUERY = "(prefers-color-scheme: dark)";

const isPreference = (v: unknown): v is ThemePreference => v === "light" || v === "dark" || v === "system";

/** `?theme=light|dark` в адресе — тема для ссылки на экран (ревью, скриншоты); выбор не сохраняет. */
function readQuery(): ThemeName | null {
  try {
    const v = new URLSearchParams(window.location.search).get("theme");
    return v === "light" || v === "dark" ? v : null;
  } catch {
    return null;
  }
}

function readStored(): ThemePreference | null {
  try {
    const v = localStorage.getItem(STORAGE_KEY);
    return isPreference(v) ? v : null;
  } catch {
    return null;
  }
}

function systemDark(): boolean {
  try {
    return window.matchMedia?.(DARK_QUERY).matches ?? false;
  } catch {
    return false;
  }
}

/** @param fallback выбор, если пользователь ещё не выбирал (кабинет инженера — "dark"). */
export function useTheme(fallback: ThemePreference) {
  const [preference, setPreferenceState] = useState<ThemePreference>(() => readQuery() ?? readStored() ?? fallback);
  const [dark, setDark] = useState(systemDark);

  useEffect(() => {
    if (preference !== "system" || !window.matchMedia) return;
    const media = window.matchMedia(DARK_QUERY);
    const onChange = () => setDark(media.matches);
    onChange();
    media.addEventListener?.("change", onChange);
    return () => media.removeEventListener?.("change", onChange);
  }, [preference]);

  const theme: ThemeName = preference === "system" ? (dark ? "dark" : "light") : preference;

  useEffect(() => {
    document.documentElement.dataset.theme = theme;
  }, [theme]);

  const setPreference = useCallback((next: ThemePreference) => {
    try {
      localStorage.setItem(STORAGE_KEY, next);
    } catch {
      /* приватный режим — выбор живёт до перезагрузки */
    }
    setPreferenceState(next);
  }, []);

  const toggle = useCallback(() => setPreference(theme === "dark" ? "light" : "dark"), [setPreference, theme]);

  return { theme, preference, setPreference, toggle };
}
