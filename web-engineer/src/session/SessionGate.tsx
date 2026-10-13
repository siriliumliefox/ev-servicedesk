// Вход инженера на реальном API (глава 21, ADR 0025 п. 1, 3): восстановление сессии вкладки после
// перезагрузки, экран входа по телефону и паролю, только роль engineer (client и admin — отказ).
// Сессия завершилась (refresh отклонён: истекла, сотрудник заблокирован) — вход с объяснением.
// Адрес (`#/tickets/…`) при входе не меняется — после входа открывается запрошенный тикет.
import { useEffect, useState, type FormEvent } from 'react'
import {
  ApiError,
  Button,
  LoadingState,
  TextField,
  errorText,
  useTheme,
  type ApiSession,
  type EngineerRepository,
  type UserPublic,
} from '@ev-servicedesk/web-shared'
import App from '../App.tsx'

type Phase = 'resuming' | 'anonymous' | 'signed-in'

export function SessionGate({ session, repo }: { session: ApiSession; repo: EngineerRepository }) {
  const [phase, setPhase] = useState<Phase>(session.canResume ? 'resuming' : 'anonymous')
  const [notice, setNotice] = useState<string | null>(null)

  useEffect(
    () =>
      session.onEnd((end) => {
        setPhase('anonymous')
        setNotice(end === 'expired' ? 'Сессия завершена, войдите снова.' : null)
      }),
    [session],
  )

  useEffect(() => {
    if (phase !== 'resuming') return
    let cancelled = false
    session
      .resume()
      .then(() => repo.getCurrentUser())
      .then(
        (user) => {
          if (cancelled) return
          if (user.role === 'engineer') setPhase('signed-in')
          else void session.logout()
        },
        (e: unknown) => {
          if (cancelled) return
          setPhase('anonymous')
          if (e instanceof ApiError && e.code === 'NETWORK') setNotice(errorText(e))
        },
      )
    return () => {
      cancelled = true
    }
  }, [phase, session, repo])

  if (phase === 'resuming') return <LoadingState label="Восстановление сессии…" />
  if (phase === 'anonymous') {
    return (
      <LoginScreen
        session={session}
        notice={notice}
        onSignedIn={() => {
          setNotice(null)
          setPhase('signed-in')
        }}
      />
    )
  }
  return <App repo={repo} onLogout={() => void session.logout()} />
}

function loginError(e: unknown): string {
  if (!(e instanceof ApiError)) return errorText(e)
  if (e.code === 'UNAUTHORIZED') return 'Неверный номер телефона или пароль.'
  if (e.code === 'VALIDATION_ERROR') return 'Проверьте номер: формат +375XXXXXXXXX.'
  if (e.code === 'RATE_LIMITED') {
    return e.retryAfter
      ? `Слишком много попыток входа. Повторите через ${Math.ceil(e.retryAfter / 60)} мин.`
      : 'Слишком много попыток входа. Повторите позже.'
  }
  return errorText(e)
}

function LoginScreen({
  session,
  notice,
  onSignedIn,
}: {
  session: ApiSession
  notice: string | null
  onSignedIn: (user: UserPublic) => void
}) {
  useTheme('dark')
  const [phone, setPhone] = useState('+375')
  const [password, setPassword] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const submit = async (e: FormEvent) => {
    e.preventDefault()
    setBusy(true)
    setError(null)
    try {
      const user = await session.login(phone.replace(/[\s()-]/g, ''), password)
      if (user.role !== 'engineer') {
        await session.logout()
        setError(
          user.role === 'admin'
            ? 'Кабинет инженера — только для инженеров. Администратор работает в админ-панели.'
            : 'Кабинет инженера — только для инженеров.',
        )
        return
      }
      onSignedIn(user)
    } catch (err) {
      setError(loginError(err))
    } finally {
      setBusy(false)
      setPassword('')
    }
  }

  return (
    <main className="grid min-h-screen place-items-center bg-canvas p-6 text-fg">
      <form onSubmit={submit} aria-labelledby="login-title" className="grid w-96 gap-4 rounded-lg border border-border bg-surface p-6 shadow-md">
        <div className="grid gap-1">
          <h1 id="login-title" className="text-h2">
            Кабинет инженера
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
          {busy ? 'Вход…' : 'Войти'}
        </Button>
      </form>
    </main>
  )
}
