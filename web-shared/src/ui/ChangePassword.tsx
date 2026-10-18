// Смена своего пароля сотрудником (глава 25, ADR 0029 п. 14): кнопка в шапке кабинета открывает модальный
// <dialog> с текущим и новым паролем. Длину проверяем до запроса (как схема), стойкость — сервер (zxcvbn);
// после смены прочие сессии сотрудника завершены — об этом сообщение.
import { useState, type FormEvent } from "react";
import { Button, TextField } from "../components";
import { errorText } from "../data/errors.ts";
import { PASSWORD_MAX, PASSWORD_MIN, passwordProblem } from "../data/password.ts";
import { ApiError } from "../data/repository.ts";
import { ModalDialog } from "./ModalDialog.tsx";

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
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [repeat, setRepeat] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<{ field: "current" | "next" | "repeat" | null; text: string } | null>(null);
  const [changed, setChanged] = useState(false);

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
      setError({ field: errorField(err), text: errorText(err) });
    } finally {
      setBusy(false);
    }
  };

  return (
    <ModalDialog title="Смена пароля" onCancel={onClose}>
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
    </ModalDialog>
  );
}

/** У какого поля показать ошибку сервера: неверный текущий — у текущего, слабый новый — у нового. */
function errorField(err: unknown): "current" | "next" | null {
  if (!(err instanceof ApiError)) return null;
  if (err.code === "PASSWORD_INVALID") return "current";
  return err.field ? "next" : null;
}
