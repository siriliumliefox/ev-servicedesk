import { useEffect, useState } from 'react'
import {
  Button,
  Card,
  MOCK_API_BASE_URL,
  StatusBadge,
  TextField,
  createApiClient,
  useTheme,
  type AggregateStatusValue,
  type components,
} from '@ev-servicedesk/web-shared'

type Ticket = components['schemas']['Ticket']

// До Auth (Глава 10/21) — mock-сервер Prism (`npm run mock`), токен любой.
const api = createApiClient(
  import.meta.env.VITE_API_BASE_URL ?? MOCK_API_BASE_URL,
  () => import.meta.env.VITE_API_TOKEN ?? 'mock-token',
)

const STATUSES: AggregateStatusValue[] = ['green', 'yellow', 'red', 'unknown']

function App() {
  const [tickets, setTickets] = useState<Ticket[] | null>(null)
  const [error, setError] = useState<string | null>(null)
  // Тёмная тема инженера по умолчанию (ТЗ раздел 6, ночные смены).
  const { theme, toggle } = useTheme('dark')

  useEffect(() => {
    api
      .GET('/tickets', { params: { query: { page: 1, page_size: 20 } } })
      .then(({ data, error, response }) =>
        data ? setTickets(data.items) : setError(error?.error.message ?? `HTTP ${response.status}`),
      )
      .catch(() => setError('API недоступен — запустите `npm run mock`'))
  }, [])

  return (
    <div className="min-h-screen bg-canvas text-fg">
      <header className="flex items-center justify-between border-b border-border bg-surface px-6 py-3">
        <h1 className="text-h2">EV-ServiceDesk — Кабинет инженера</h1>
        <Button variant="secondary" size="sm" onClick={toggle} aria-pressed={theme === 'dark'}>
          {theme === 'dark' ? 'Светлая тема' : 'Тёмная тема'}
        </Button>
      </header>

      {/* Витрина дизайн-системы (Глава 6). Канбан-доска тикетов — Глава 21. */}
      <main className="mx-auto grid max-w-5xl gap-6 p-6">
        <Card className="grid gap-3">
          <h2 className="text-h3">Статусы агрегатов</h2>
          <div className="flex flex-wrap gap-2">
            {STATUSES.map((s) => (
              <StatusBadge key={s} status={s} />
            ))}
          </div>
        </Card>

        <Card className="grid gap-3">
          <h2 className="text-h3">Кнопки</h2>
          <div className="flex flex-wrap items-center gap-2">
            <Button>Взять в работу</Button>
            <Button variant="secondary">Ответить</Button>
            <Button variant="ghost">Отмена</Button>
            <Button variant="danger">Закрыть тикет</Button>
            <Button disabled>Недоступно</Button>
            <Button size="sm">Компактная</Button>
          </div>
        </Card>

        <Card className="grid gap-4 sm:grid-cols-2">
          <TextField label="VIN" placeholder="LB37622Z0NX000000" hint="17 символов" />
          <TextField label="Пробег, км" defaultValue="-5" error="Пробег не может быть отрицательным" />
        </Card>

        <p className="text-body-sm text-fg-muted" data-testid="api-status">
          {error
            ? `Ошибка API: ${error}`
            : tickets === null
              ? 'Загрузка тикетов…'
              : `Тикетов с API: ${tickets.length}${tickets[0] ? ` (первый: #${tickets[0].id}, ${tickets[0].status})` : ''}`}
        </p>
      </main>
    </div>
  )
}

export default App
