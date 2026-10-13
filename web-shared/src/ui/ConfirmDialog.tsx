// Подтверждение действия (глава 21 — «Решено» при переносе тикета; глава 22 — блокировка, роль, сброс
// пароля, публикация): модальный <dialog>, фокус внутри, Esc — отмена.
import { useEffect, useRef, type ReactNode } from "react";
import { Button, type ButtonVariant } from "../components";

/** Модальное подтверждение (`<dialog>`): фокус внутри, Esc — отмена. */
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
  const ref = useRef<HTMLDialogElement>(null);

  useEffect(() => {
    const dialog = ref.current;
    if (!dialog) return;
    if (typeof dialog.showModal === "function" && !dialog.open) dialog.showModal();
    else dialog.setAttribute("open", "");
    return () => {
      if (dialog.open && typeof dialog.close === "function") dialog.close();
    };
  }, []);

  return (
    <dialog
      ref={ref}
      aria-labelledby="confirm-title"
      // Esc закрывает только диалог, а не экран под ним (слушатели Esc у окна в приложениях).
      onKeyDown={(e) => e.key === "Escape" && e.stopPropagation()}
      onCancel={(e) => {
        e.preventDefault();
        onCancel();
      }}
      className="m-auto w-[28rem] rounded-lg border border-border bg-surface p-6 text-fg shadow-lg backdrop:bg-black/50"
    >
      <h2 id="confirm-title" className="text-h3">
        {title}
      </h2>
      <div className="mt-2 grid gap-2 text-body-sm text-fg-muted">{children}</div>
      <div className="mt-6 flex justify-end gap-2">
        <Button variant="secondary" onClick={onCancel}>
          Отмена
        </Button>
        <Button autoFocus variant={confirmVariant} disabled={busy} onClick={onConfirm}>
          {confirmLabel}
        </Button>
      </div>
    </dialog>
  );
}
