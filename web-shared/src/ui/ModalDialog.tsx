// Модальное окно кабинетов (главы 21–22, 25): <dialog> с фокусом внутри; Esc закрывает только окно, а не
// экран под ним (слушатели Esc у окна в приложениях). Каркас для ConfirmDialog и смены пароля.
import { useEffect, useId, useRef, type ReactNode } from "react";

export function ModalDialog({ title, onCancel, children }: { title: string; onCancel: () => void; children: ReactNode }) {
  const ref = useRef<HTMLDialogElement>(null);
  const titleId = useId();

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
      aria-labelledby={titleId}
      onKeyDown={(e) => e.key === "Escape" && e.stopPropagation()}
      onCancel={(e) => {
        e.preventDefault();
        onCancel();
      }}
      className="m-auto w-[28rem] rounded-lg border border-border bg-surface p-6 text-fg shadow-lg backdrop:bg-[rgb(0_0_0/0.5)]"
    >
      <h2 id={titleId} className="text-h3">
        {title}
      </h2>
      {children}
    </dialog>
  );
}
