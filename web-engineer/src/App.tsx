// Кабинет инженера (Глава 8, прототип; ADR 0012): канбан-доска слева, карточка тикета справа (ТЗ раздел 9).
// Выбранный тикет — в адресе: `#/tickets/1042`. Тёмная тема по умолчанию (ТЗ раздел 6, ночные смены).
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
} from '@ev-servicedesk/web-shared'
import { Board } from './board/Board.tsx'
import { EngineerContext, type EngineerEnv } from './repo.ts'
import { TicketPanel } from './ticket/TicketPanel.tsx'

const systemNow = () => new Date()

export default function App({
  repo,
  now = systemNow,
  demo,
}: {
  repo: EngineerRepository
  now?: () => Date
  /** Панель «Демо» — только для прототипа. */
  demo?: PrototypeRepository
}) {
  const { theme, toggle } = useTheme('dark')
  const [path, navigate] = useHashRoute()
  const [version, setVersion] = useState(0)
  const bump = useCallback(() => setVersion((v) => v + 1), [])
  const me = useAsync(() => repo.getCurrentUser(), [repo, version])
  const [, setTick] = useState(0)

  // SLA «осталось N мин» пересчитывается раз в минуту.
  useEffect(() => {
    const id = window.setInterval(() => setTick((n) => n + 1), 60_000)
    return () => window.clearInterval(id)
  }, [])

  const match = /^\/tickets\/(\d+)$/.exec(path)
  const selectedId = match ? Number(match[1]) : null

  useEffect(() => {
    if (selectedId === null) return
    const onKey = (e: KeyboardEvent) => e.key === 'Escape' && navigate('/')
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [selectedId, navigate])

  const env = useMemo<EngineerEnv | null>(
    () => (me.data ? { repo, now, meId: me.data.id } : null),
    [repo, now, me.data],
  )

  return (
    <div className="flex h-screen min-w-0 flex-col bg-canvas text-fg">
      <header className="flex items-center justify-between gap-4 border-b border-border bg-surface px-6 py-3">
        <div className="flex items-center gap-3">
          <span aria-hidden="true" className="size-3 rounded-full bg-primary" />
          <h1 className="text-h2">EV-ServiceDesk · Кабинет инженера</h1>
        </div>
        <div className="flex items-center gap-3">
          {me.data && <span className="text-body-sm text-fg-muted">Инженер #{me.data.id}</span>}
          {demo && <DemoPanel repo={demo} theme={theme} onToggleTheme={toggle} onChange={bump} />}
          <Button variant="secondary" size="sm" onClick={toggle} aria-pressed={theme === 'dark'}>
            {theme === 'dark' ? 'Светлая тема' : 'Тёмная тема'}
          </Button>
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
            <Board version={version} selectedId={selectedId} onSelect={(id) => navigate(`/tickets/${id}`)} />
            {selectedId !== null && (
              <TicketPanel
                key={selectedId}
                ticketId={selectedId}
                version={version}
                onChanged={bump}
                onClose={() => navigate('/')}
              />
            )}
          </div>
        </EngineerContext.Provider>
      )}
    </div>
  )
}
