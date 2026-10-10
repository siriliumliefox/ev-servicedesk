// Панель «Демо» прототипа (Глава 8, ADR 0012) — переключение сценариев ревью: нет сети, пустые данные,
// тема, сброс. Только для `PrototypeRepository`; в HTTP-клиенте глав 21–22 панели нет.
import { useId } from "react";
import type { PrototypeRepository } from "../prototype/PrototypeRepository.ts";
import type { ThemeName } from "../theme/useTheme.ts";

export function DemoPanel({
  repo,
  theme,
  onToggleTheme,
  onChange,
}: {
  repo: PrototypeRepository;
  theme: ThemeName;
  onToggleTheme: () => void;
  /** Данные прототипа изменились — экран перезагружает их. */
  onChange: () => void;
}) {
  const id = useId();
  const scenario = repo.getScenario();
  return (
    <details className="relative">
      <summary className="flex h-(--size-control-web-sm) cursor-pointer list-none items-center gap-2 rounded-md border border-border-strong px-3 text-label text-fg hover:bg-surface-subtle">
        <svg viewBox="0 0 16 16" className="size-4" fill="none" stroke="currentColor" strokeWidth={1.5} aria-hidden="true">
          <path d="M2 4h7m3 0h2M2 12h3m3 0h6M9 2.5v3M5 10.5v3" strokeLinecap="round" />
        </svg>
        Демо
      </summary>
      <div className="absolute right-0 z-20 mt-2 grid w-72 gap-3 rounded-lg border border-border bg-surface p-4 shadow-lg">
        <p className="text-caption text-fg-muted">Сценарии прототипа для ревью. Данные — фикстуры по OpenAPI v1.</p>
        <label className="flex items-center gap-2 text-body">
          <input
            type="checkbox"
            className="size-4 accent-(--ev-fg)"
            checked={repo.isOffline()}
            onChange={(e) => {
              repo.setOffline(e.target.checked);
              onChange();
            }}
          />
          Нет сети
        </label>
        <fieldset className="grid gap-1">
          <legend className="text-label">Данные</legend>
          {(
            [
              ["demo", "Демонстрационные"],
              ["empty", "Пусто (новая система)"],
            ] as const
          ).map(([value, label]) => (
            <label key={value} className="flex items-center gap-2 text-body">
              <input
                type="radio"
                name={`${id}-scenario`}
                className="size-4 accent-(--ev-fg)"
                checked={scenario === value}
                onChange={() => {
                  repo.setScenario(value);
                  onChange();
                }}
              />
              {label}
            </label>
          ))}
        </fieldset>
        <div className="flex flex-wrap gap-2">
          <button
            type="button"
            className="h-(--size-control-web-sm) rounded-md border border-border-strong px-3 text-label hover:bg-surface-subtle"
            aria-pressed={theme === "dark"}
            onClick={onToggleTheme}
          >
            {theme === "dark" ? "Светлая тема" : "Тёмная тема"}
          </button>
          <button
            type="button"
            className="h-(--size-control-web-sm) rounded-md border border-border-strong px-3 text-label hover:bg-surface-subtle"
            onClick={() => {
              repo.reset();
              onChange();
            }}
          >
            Сбросить данные
          </button>
        </div>
      </div>
    </details>
  );
}
