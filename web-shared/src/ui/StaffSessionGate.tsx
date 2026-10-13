// Вход сотрудника на реальном API (глава 21, ADR 0025 п. 1, 3; глава 22, ADR 0026 п. 1): восстановление
// сессии вкладки после перезагрузки, экран входа по телефону и паролю, только своя роль приложения —
// кабинет инженера пускает инженера, админ-панель — администратора; чужая роль — отказ и выход.
// Сессия завершилась (refresh отклонён: истекла, сотрудник заблокирован) — вход с объяснением.
// Адрес (`#/…`) при входе не меняется — после входа открывается запрошенный экран.
import { useCallback, useEffect, useState, type FormEvent, type ReactNode } from "react";
import { Button, TextField } from "../components";
import { ERROR_TEXTS, errorText } from "../data/errors.ts";
import type { ApiSession } from "../data/http/session.ts";
import type { UserPublic, UserRole } from "../data/models.ts";
import { ApiError } from "../data/repository.ts";
import { useTheme, type ThemePreference } from "../theme/useTheme";
import { LoadingState } from "./feedback.tsx";

type Phase = "resuming" | "anonymous" | "signed-in";

/** Вошёл сотрудник с чужой для приложения ролью — оно не открывается, сессия завершается. */
class WrongRole extends Error {
  readonly role: UserRole;

  constructor(role: UserRole) {
    super(role);
    this.role = role;
  }
}

export interface StaffSessionGateProps {
  session: ApiSession;
  /** Кто вошёл — `getCurrentUser` репозитория приложения (объект стабилен между рендерами). */
  repo: { getCurrentUser(): Promise<UserPublic> };
  /** Кого пускает приложение. */
  role: "engineer" | "admin";
  /** Заголовок экрана входа: «Кабинет инженера», «Админ-панель». */
  title: string;
  /** Отказ вошедшему с другой ролью. */
  wrongRoleText: (role: UserRole) => string;
  /** Тема экрана входа, пока пользователь её не выбирал. */
  themeFallback: ThemePreference;
  /** Приложение после входа; `logout` — выход с сервера и из вкладки. */
  children: (logout: () => void) => ReactNode;
}

export function StaffSessionGate({ session, repo, role, title, wrongRoleText, themeFallback, children }: StaffSessionGateProps) {
  const [phase, setPhase] = useState<Phase>(session.canResume ? "resuming" : "anonymous");
  const [notice, setNotice] = useState<string | null>(null);

  /** Один путь для входа и восстановления: аутентификация → кто вошёл → только своя роль. */
  const admit = useCallback(
    async (authenticate: () => Promise<void>) => {
      await authenticate();
      const user = await repo.getCurrentUser();
      if (user.role !== role) {
        await session.logout();
        throw new WrongRole(user.role);
      }
    },
    [session, repo, role],
  );
  const enter = () => {
    setNotice(null);
    setPhase("signed-in");
  };
  const failure = useCallback((e: unknown) => signInError(e, wrongRoleText), [wrongRoleText]);

  useEffect(
    () =>
      session.onEnd((end) => {
        setPhase("anonymous");
        setNotice(end === "expired" ? ERROR_TEXTS.UNAUTHORIZED : null);
      }),
    [session],
  );

  useEffect(() => {
    if (phase !== "resuming") return;
    admit(() => session.resume()).then(enter, (e: unknown) => {
      setPhase("anonymous");
      // Отклонённый refresh объявляет onEnd («Сессия завершена»); здесь — сеть и чужая роль.
      if (e instanceof WrongRole || (e instanceof ApiError && e.code === "NETWORK")) setNotice(failure(e));
    });
  }, [phase, session, admit, failure]);

  if (phase === "resuming") return <LoadingState label="Восстановление сессии…" />;
  if (phase === "anonymous") {
    return (
      <LoginScreen
        title={title}
        themeFallback={themeFallback}
        notice={notice}
        describe={failure}
        onSubmit={(phone, password) => admit(() => session.login(phone, password)).then(enter)}
      />
    );
  }
  return <>{children(() => void session.logout())}</>;
}

function signInError(e: unknown, wrongRoleText: (role: UserRole) => string): string {
  if (e instanceof WrongRole) return wrongRoleText(e.role);
  if (!(e instanceof ApiError)) return errorText(e);
  if (e.code === "UNAUTHORIZED") return "Неверный номер телефона или пароль.";
  if (e.code === "VALIDATION_ERROR") return "Проверьте номер: формат +375XXXXXXXXX.";
  if (e.code === "RATE_LIMITED") {
    return e.retryAfter
      ? `Слишком много попыток входа. Повторите через ${Math.ceil(e.retryAfter / 60)} мин.`
      : "Слишком много попыток входа. Повторите позже.";
  }
  return errorText(e);
}

function LoginScreen({
  title,
  themeFallback,
  notice,
  describe,
  onSubmit,
}: {
  title: string;
  themeFallback: ThemePreference;
  notice: string | null;
  describe: (e: unknown) => string;
  onSubmit: (phone: string, password: string) => Promise<void>;
}) {
  useTheme(themeFallback);
  const [phone, setPhone] = useState("+375");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await onSubmit(phone.replace(/[\s()-]/g, ""), password);
    } catch (err) {
      setError(describe(err));
      setBusy(false);
      setPassword("");
    }
  };

  return (
    <main className="grid min-h-screen place-items-center bg-canvas p-6 text-fg">
      <form onSubmit={submit} aria-labelledby="login-title" className="grid w-96 gap-4 rounded-lg border border-border bg-surface p-6 shadow-md">
        <div className="grid gap-1">
          <h1 id="login-title" className="text-h2">
            {title}
          </h1>
          <p className="text-body-sm text-fg-muted">EV-ServiceDesk · вход для сотрудников</p>
        </div>
        {notice && (
          <p role="status" className="rounded-md bg-status-yellow-bg px-3 py-2 text-body-sm text-status-yellow-fg">
            {notice}
          </p>
        )}
        <TextField
          label="Телефон"
          type="tel"
          autoComplete="username"
          inputMode="tel"
          required
          value={phone}
          onChange={(e) => setPhone(e.target.value)}
        />
        <TextField
          label="Пароль"
          type="password"
          autoComplete="current-password"
          required
          value={password}
          onChange={(e) => setPassword(e.target.value)}
        />
        {error && (
          <p role="alert" className="text-body-sm text-danger-text">
            {error}
          </p>
        )}
        <Button type="submit" disabled={busy || !password}>
          {busy ? "Вход…" : "Войти"}
        </Button>
      </form>
    </main>
  );
}

const THEME_LABELS: Record<ThemePreference, string> = { system: "Как в системе", light: "Светлая", dark: "Тёмная" };

/** Выбор темы в шапке кабинета (ADR 0025 п. 13): «как в системе», светлая, тёмная. */
export function ThemeSelect({ value, onChange }: { value: ThemePreference; onChange: (next: ThemePreference) => void }) {
  return (
    <label className="flex items-center gap-2 text-body-sm text-fg-muted">
      {/* «Оформление», а не «Тема»: в админ-панели «Тема» — поле публикации (одинаковые подписи путают). */}
      Оформление
      <select
        value={value}
        onChange={(e) => onChange(e.target.value as ThemePreference)}
        className="h-(--size-control-web-sm) rounded-md border border-border-strong bg-surface px-2 text-body-sm text-fg"
      >
        {(Object.keys(THEME_LABELS) as ThemePreference[]).map((p) => (
          <option key={p} value={p}>
            {THEME_LABELS[p]}
          </option>
        ))}
      </select>
    </label>
  );
}
