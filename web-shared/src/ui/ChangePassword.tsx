// Смена своего пароля сотрудником (глава 25, ADR 0029 п. 14): кнопка в шапке кабинета открывает модальный
// <dialog> с текущим и новым паролем. Длину проверяем до запроса (как схема), стойкость — сервер (zxcvbn);
// после смены прочие сессии сотрудника завершены — об этом сообщение.
import { useEffect, useRef, useState, type FormEvent } from "react";
import { Button, TextField } from "../components";
import { errorText } from "../data/errors.ts";
import { PASSWORD_MAX, PASSWORD_MIN, passwordProblem } from "../data/password.ts";
import { ApiError } from "../data/repository.ts";

export function ChangePasswordButton({ onChange }: { onChange: (current: string, next: string) => Promise<void> }) {
  const [open, setOpen] = useState(false);
  return (
    <>
      <Button variant="secondary" size="sm" onClick={() => setOpen(true)}>
        Сменить пароль
      </Button>
      {open && <ChangePasswordDialog onChange={onChange} onClose={() => setOpen(false)} />}
    </>
  );
}

function ChangePasswordDialog({
  onChange,
  onClose,
}: {
  onChange: (current: string, next: string) => Promise<void>;
  onClose: () => void;
}) {
  const ref = useRef<HTMLDialogElement>(null);
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [repeat, setRepeat] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<{ field: "current" | "next" | "repeat" | null; text: string } | null>(null);
  const [changed, setChanged] = useState(false);

  useEffect(() => {
    const dialog = ref.current;
    if (!dialog) return;
    if (typeof dialog.showModal === "function" && !dialog.open) dialog.showModal();
    else dialog.setAttribute("open", "");
    return () => {
      if (dialog.open && typeof dialog.close === "function") dialog.close();
    };
  }, []);

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    const tooShort = passwordProblem(next);
    if (tooShort) return setError({ field: "next", text: tooShort });
    if (next !== repeat) return setError({ field: "repeat", text: "Пароли не совпадают" });
    setBusy(true);
    setError(null);
    try {
      await onChange(current, next);
      setChanged(true);
    } catch (err) {
      const field = err instanceof ApiError && err.code === "PASSWORD_INVALID" ? "current" : err instanceof ApiError && err.field ? "next" : null;
      setError({ field, text: errorText(err) });
    } finally {
      setBusy(false);
    }
  };

  return (
    <dialog
      ref={ref}
      aria-labelledby="change-password-title"
      onKeyDown={(e) => e.key === "Escape" && e.stopPropagation()}
      onCancel={(e) => {
        e.preventDefault();
        onClose();
      }}
      className="m-auto w-[28rem] rounded-lg border border-border bg-surface p-6 text-fg shadow-lg backdrop:bg-[rgb(0_0_0/0.5)]"
    >
      <h2 id="change-password-title" className="text-h3">
        Смена пароля
      </h2>
      {changed ? (
        <div className="mt-4 grid gap-4">
          <p role="status" className="text-body-sm">
            Пароль изменён. Вход на других устройствах завершён — там войдите с новым паролем.
          </p>
          <div className="flex justify-end">
            <Button autoFocus onClick={onClose}>
              Готово
            </Button>
          </div>
        </div>
      ) : (
        <form onSubmit={submit} className="mt-4 grid gap-4">
          <TextField
            label="Текущий пароль"
            type="password"
            autoComplete="current-password"
            required
            autoFocus
            value={current}
            error={error?.field === "current" ? error.text : undefined}
            onChange={(e) => setCurrent(e.target.value)}
          />
          <TextField
            label="Новый пароль"
            type="password"
            autoComplete="new-password"
            required
            maxLength={PASSWORD_MAX}
            hint={`От ${PASSWORD_MIN} символов: фраза из нескольких слов или случайный набор.`}
            value={next}
            error={error?.field === "next" ? error.text : undefined}
            onChange={(e) => setNext(e.target.value)}
          />
          <TextField
            label="Повторите новый пароль"
            type="password"
            autoComplete="new-password"
            required
            maxLength={PASSWORD_MAX}
            value={repeat}
            error={error?.field === "repeat" ? error.text : undefined}
            onChange={(e) => setRepeat(e.target.value)}
          />
          {error?.field === null && (
            <p role="alert" className="text-body-sm text-danger-text">
              {error.text}
            </p>
          )}
          <div className="flex justify-end gap-2">
            <Button type="button" variant="secondary" onClick={onClose}>
              Отмена
            </Button>
            <Button type="submit" disabled={busy || !current || !next || !repeat}>
              {busy ? "Сохранение…" : "Сменить пароль"}
            </Button>
          </div>
        </form>
      )}
    </dialog>
  );
}
