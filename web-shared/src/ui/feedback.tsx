// Состояния загрузки, пустые и ошибки (Глава 8). Текст ошибок — по коду `ApiError`, а не message сервера
// (Error.message контракта — «для логов/поддержки, не для UI напрямую»).
import type { ReactNode } from "react";
import { Button } from "../components.tsx";
import { ApiError } from "../data/repository.ts";

export function errorText(error: unknown): string {
  if (error instanceof ApiError) {
    switch (error.code) {
      case "NETWORK":
        return "Нет соединения с сервером. Проверьте сеть и повторите.";
      case "FORBIDDEN":
        return "Недостаточно прав для этого действия.";
      case "CONFLICT":
        return "Данные уже изменил другой пользователь. Обновите и повторите.";
      case "NOT_FOUND":
        return "Объект не найден — возможно, его удалили.";
      case "VALIDATION_ERROR":
        return error.message;
    }
  }
  return "Что-то пошло не так. Повторите попытку.";
}

export function LoadingState({ label = "Загрузка…" }: { label?: string }) {
  return (
    <div role="status" className="flex items-center gap-2 p-4 text-body-sm text-fg-muted">
      <svg viewBox="0 0 16 16" className="size-4 animate-spin" fill="none" stroke="currentColor" strokeWidth={2} aria-hidden="true">
        <path d="M8 1.5a6.5 6.5 0 1 0 6.5 6.5" strokeLinecap="round" />
      </svg>
      {label}
    </div>
  );
}

export function EmptyState({ title, children, action }: { title: string; children?: ReactNode; action?: ReactNode }) {
  return (
    <div className="flex flex-col items-center gap-2 rounded-lg border border-dashed border-border p-6 text-center">
      <p className="text-h3 text-fg">{title}</p>
      {children && <p className="max-w-sm text-body-sm text-fg-muted">{children}</p>}
      {action}
    </div>
  );
}

export function ErrorState({ error, onRetry }: { error: unknown; onRetry?: () => void }) {
  return (
    <div role="alert" className="flex flex-col items-start gap-3 rounded-lg border border-danger-text bg-status-red-bg p-4">
      <p className="text-label text-status-red-fg">{errorText(error)}</p>
      {onRetry && (
        <Button variant="secondary" size="sm" onClick={onRetry}>
          Повторить
        </Button>
      )}
    </div>
  );
}

/** Ошибка действия (кнопки/формы) — рядом с элементом, без замены экрана. */
export function InlineError({ error }: { error: unknown }) {
  if (!error) return null;
  return (
    <p role="alert" className="text-body-sm text-danger-text">
      {errorText(error)}
    </p>
  );
}
