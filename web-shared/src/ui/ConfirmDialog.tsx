// Подтверждение действия (глава 21 — «Решено» при переносе тикета; глава 22 — блокировка, роль, сброс
// пароля, публикация): модальный <dialog>, фокус внутри, Esc — отмена.
import type { ReactNode } from "react";
import { Button, type ButtonVariant } from "../components";
import { ModalDialog } from "./ModalDialog.tsx";

/** Модальное подтверждение: Esc и «Отмена» — отказ. */
export function ConfirmDialog({
  title,
  children,
  confirmLabel,
  confirmVariant = "primary",
  busy = false,
  onConfirm,
  onCancel,
}: {
  title: string;
  children: ReactNode;
  confirmLabel: string;
  /** Необратимое действие — `danger`. */
  confirmVariant?: ButtonVariant;
  /** Запрос идёт — кнопка подтверждения недоступна (без повторной отправки). */
  busy?: boolean;
  onConfirm: () => void;
  onCancel: () => void;
}) {
  return (
    <ModalDialog title={title} onCancel={onCancel}>
      <div className="mt-2 grid gap-2 text-body-sm text-fg-muted">{children}</div>
      <div className="mt-6 flex justify-end gap-2">
        <Button variant="secondary" onClick={onCancel}>
          Отмена
        </Button>
        <Button autoFocus variant={confirmVariant} disabled={busy} onClick={onConfirm}>
          {confirmLabel}
        </Button>
      </div>
    </ModalDialog>
  );
}
