import { useEffect, useState } from 'react'
import {
  MOCK_API_BASE_URL,
  StatusBadge,
  createApiClient,
  type components,
} from '@ev-servicedesk/web-shared'

type Ticket = components['schemas']['Ticket']

// До Auth (Глава 10/21) — mock-сервер Prism (`npm run mock`), токен любой.
const api = createApiClient(
  import.meta.env.VITE_API_BASE_URL ?? MOCK_API_BASE_URL,
  () => import.meta.env.VITE_API_TOKEN ?? 'mock-token',
)

function App() {
  const [tickets, setTickets] = useState<Ticket[] | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    api
      .GET('/tickets', { params: { query: { page: 1, page_size: 20 } } })
      .then(({ data, error, response }) =>
        data ? setTickets(data.items) : setError(error?.error.message ?? `HTTP ${response.status}`),
      )
      .catch(() => setError('API недоступен — запустите `npm run mock`'))
  }, [])

  return (
    <div className="min-h-screen flex items-center justify-center bg-gray-50">
      <div className="text-center space-y-3">
        <h1 className="text-2xl font-semibold text-gray-800">
          EV-ServiceDesk — Кабинет инженера
        </h1>
        <p className="text-gray-500">
          Каркас, Глава 4. Канбан-доска тикетов — Глава 21.
        </p>
        <div className="flex gap-2 justify-center">
          <StatusBadge status="green" />
          <StatusBadge status="yellow" />
          <StatusBadge status="red" />
        </div>
        <p className="text-sm text-gray-600" data-testid="api-status">
          {error
            ? `Ошибка API: ${error}`
            : tickets === null
              ? 'Загрузка тикетов…'
              : `Тикетов с API: ${tickets.length}${tickets[0] ? ` (первый: #${tickets[0].id}, ${tickets[0].status})` : ''}`}
        </p>
      </div>
    </div>
  )
}

export default App
