// Переключение светлой/тёмной темы (Глава 6, ТЗ раздел 6 — тёмная тема инженера).
// Тема — атрибут data-theme на <html> (см. tokens.css); выбор пользователя хранится в localStorage.
import { useCallback, useEffect, useState } from "react";

export type ThemeName = "light" | "dark";

const STORAGE_KEY = "ev-theme";

/** `?theme=light|dark` в адресе — тема для ссылки на экран (ревью, скриншоты); выбор не сохраняет. */
function readQuery(): ThemeName | null {
  try {
    const v = new URLSearchParams(window.location.search).get("theme");
    return v === "light" || v === "dark" ? v : null;
  } catch {
    return null;
  }
}

function readStored(): ThemeName | null {
  try {
    const v = localStorage.getItem(STORAGE_KEY);
    return v === "light" || v === "dark" ? v : null;
  } catch {
    return null;
  }
}

/** @param fallback тема, если пользователь ещё не выбирал (кабинет инженера — "dark"). */
export function useTheme(fallback: ThemeName) {
  const [theme, setTheme] = useState<ThemeName>(() => readQuery() ?? readStored() ?? fallback);

  useEffect(() => {
    document.documentElement.dataset.theme = theme;
  }, [theme]);

  const toggle = useCallback(() => {
    setTheme((current) => {
      const next = current === "dark" ? "light" : "dark";
      try {
        localStorage.setItem(STORAGE_KEY, next);
      } catch {
        /* приватный режим — выбор живёт до перезагрузки */
      }
      return next;
    });
  }, []);

  return { theme, toggle };
}
