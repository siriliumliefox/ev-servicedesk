import { StatusBadge } from '@ev-servicedesk/web-shared'

function App() {
  return (
    <div className="min-h-screen flex items-center justify-center bg-gray-50">
      <div className="text-center space-y-3">
        <h1 className="text-2xl font-semibold text-gray-800">
          EV-ServiceDesk — Админ-панель
        </h1>
        <p className="text-gray-500">
          Каркас, Глава 4. Конструктор регламентов ТО — Глава 22.
        </p>
        <div className="flex gap-2 justify-center">
          <StatusBadge status="unknown" />
        </div>
      </div>
    </div>
  )
}

export default App
