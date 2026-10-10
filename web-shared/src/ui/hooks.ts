// Хуки веб-клиентов: загрузка данных и маршрут в hash (`#/tickets/1042`) — без роутера-зависимости.
import { useCallback, useEffect, useState } from "react";

export interface AsyncState<T> {
  data: T | undefined;
  error: unknown;
  loading: boolean;
  reload: () => void;
}

/** Загружает `load()` при монтировании и при смене `deps`; `reload` — повтор (кнопка «Повторить»). */
export function useAsync<T>(load: () => Promise<T>, deps: readonly unknown[]): AsyncState<T> {
  const [state, setState] = useState<{ data?: T; error?: unknown; loading: boolean }>({ loading: true });
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    let cancelled = false;
    setState((s) => ({ data: s.data, loading: true }));
    load().then(
      (data) => !cancelled && setState({ data, loading: false }),
      (error: unknown) => !cancelled && setState({ error, loading: false }),
    );
    return () => {
      cancelled = true;
    };
    // Зависимости передаёт вызывающий (как у useEffect); `load` пересоздаётся на каждом рендере.
  }, [...deps, attempt]);

  const reload = useCallback(() => setAttempt((n) => n + 1), []);
  return { data: state.data, error: state.error, loading: state.loading, reload };
}

function readHash(): string {
  return window.location.hash.replace(/^#/, "") || "/";
}

/** Текущий путь из `location.hash` и переход по нему (история браузера работает). */
export function useHashRoute(): [string, (path: string) => void] {
  const [path, setPath] = useState(readHash);

  useEffect(() => {
    const onChange = () => setPath(readHash());
    window.addEventListener("hashchange", onChange);
    return () => window.removeEventListener("hashchange", onChange);
  }, []);

  const navigate = useCallback((next: string) => {
    if (readHash() === next) return;
    window.location.hash = next;
    setPath(next);
  }, []);

  return [path, navigate];
}
