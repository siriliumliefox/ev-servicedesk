import { Card, StatusBadge } from '@ev-servicedesk/web-shared'

function App() {
  return (
    <div className="flex min-h-screen items-center justify-center bg-canvas">
      <Card className="space-y-3 text-center">
        <h1 className="text-h1 text-fg">EV-ServiceDesk — Админ-панель</h1>
        <p className="text-fg-muted">Каркас, Глава 4. Конструктор регламентов ТО — Глава 22.</p>
        <div className="flex justify-center gap-2">
          <StatusBadge status="unknown" />
        </div>
      </Card>
    </div>
  )
}

export default App
