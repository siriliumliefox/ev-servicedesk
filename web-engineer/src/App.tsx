// Кабинет инженера (Глава 8 — прототип, ADR 0012; глава 21 — реальный API, ADR 0025): канбан-доска слева,
// карточка тикета справа (ТЗ раздел 9). Выбранный тикет — в адресе: `#/tickets/1042` (ссылку можно
// переслать; после входа открывается она же). Тема по умолчанию тёмная (ТЗ раздел 6, ночные смены).
import { useCallback, useEffect, useMemo, useState } from 'react'
import {
  Button,
  DemoPanel,
  ErrorState,
  LoadingState,
  useAsync,
  useHashRoute,
  useTheme,
  type EngineerRepository,
  type PrototypeRepository,
  type ThemePreference,
} from '@ev-servicedesk/web-shared'
import { Board } from './board/Board.tsx'
import { EngineerContext, type EngineerEnv } from './repo.ts'
import { TicketPanel } from './ticket/TicketPanel.tsx'
import { NoticeProvider } from './ui/Notices.tsx'

const systemNow = () => new Date()

const THEME_LABELS: Record<ThemePreference, string> = { system: 'Как в системе', light: 'Светлая', dark: 'Тёмная' }

export default function App({
  repo,
  now = systemNow,
  demo,
  onLogout,
}: {
  repo: EngineerRepository
  now?: () => Date
  /** Панель «Демо» — только для прототипа. */
  demo?: PrototypeRepository
  /** Выход — только на реальном API (в прототипе сессии нет). */
  onLogout?: () => void
}) {
  const { theme, preference, setPreference, toggle } = useTheme('dark')
  const [path, navigate] = useHashRoute()
  // version — данные всего приложения (панель «Демо»); boardTick — доска после действий в карточке;
  // panelTick — карточка после переноса на доске.
  const [version, setVersion] = useState(0)
  const [boardTick, setBoardTick] = useState(0)
  const [panelTick, setPanelTick] = useState(0)
  const bump = useCallback(() => setVersion((v) => v + 1), [])
  const refreshBoard = useCallback(() => setBoardTick((v) => v + 1), [])
  const refreshPanel = useCallback(() => setPanelTick((v) => v + 1), [])
  const me = useAsync(() => repo.getCurrentUser(), [repo, version])
  const [, setTick] = useState(0)

  // SLA «осталось N мин» пересчитывается раз в минуту.
  useEffect(() => {
    const id = window.setInterval(() => setTick((n) => n + 1), 60_000)
    return () => window.clearInterval(id)
  }, [])

  const match = /^\/tickets\/(\d+)$/.exec(path)
  const selectedId = match ? Number(match[1]) : null
  const closeTicket = useCallback(() => navigate('/'), [navigate])

  useEffect(() => {
    if (selectedId === null) return
    const onKey = (e: KeyboardEvent) => e.key === 'Escape' && !document.querySelector('dialog[open]') && closeTicket()
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [selectedId, closeTicket])

  const env = useMemo<EngineerEnv | null>(
    () => (me.data ? { repo, now, meId: me.data.id } : null),
    [repo, now, me.data],
  )

  return (
    <NoticeProvider>
      <div className="flex h-screen min-w-0 flex-col bg-canvas text-fg">
        <header className="flex items-center justify-between gap-4 border-b border-border bg-surface px-6 py-3">
          <div className="flex items-center gap-3">
            <span aria-hidden="true" className="size-3 rounded-full bg-primary" />
            <h1 className="text-h2">EV-ServiceDesk · Кабинет инженера</h1>
          </div>
          <div className="flex items-center gap-3">
            {me.data && (
              <span className="text-body-sm text-fg-muted">
                Инженер {me.data.phone ?? `#${me.data.id}`}
              </span>
            )}
            {demo && <DemoPanel repo={demo} theme={theme} onToggleTheme={toggle} onChange={bump} />}
            <label className="flex items-center gap-2 text-body-sm text-fg-muted">
              Тема
              <select
                value={preference}
                onChange={(e) => setPreference(e.target.value as ThemePreference)}
                className="h-(--size-control-web-sm) rounded-md border border-border-strong bg-surface px-2 text-body-sm text-fg"
              >
                {(Object.keys(THEME_LABELS) as ThemePreference[]).map((p) => (
                  <option key={p} value={p}>
                    {THEME_LABELS[p]}
                  </option>
                ))}
              </select>
            </label>
            {onLogout && (
              <Button variant="secondary" size="sm" onClick={onLogout}>
                Выйти
              </Button>
            )}
          </div>
        </header>

        {me.error ? (
          <div className="p-6">
            <ErrorState error={me.error} onRetry={me.reload} />
          </div>
        ) : !env ? (
          <LoadingState />
        ) : (
          <EngineerContext.Provider value={env}>
            <div className="flex min-h-0 flex-1">
              <Board
                version={version + boardTick}
                selectedId={selectedId}
                onSelect={(id) => navigate(`/tickets/${id}`)}
                onChanged={refreshPanel}
              />
              {selectedId !== null && (
                <TicketPanel
                  key={selectedId}
                  ticketId={selectedId}
                  version={version + panelTick}
                  onChanged={refreshBoard}
                  onClose={closeTicket}
                />
              )}
            </div>
          </EngineerContext.Provider>
        )}
      </div>
    </NoticeProvider>
  )
}
