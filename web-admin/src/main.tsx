import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { ApiSession, HttpAdminRepository, PrototypeRepository, sessionTokenStore } from '@ev-servicedesk/web-shared'
import './index.css'
import App from './App.tsx'
import { SessionGate } from './session/SessionGate.tsx'

// Без VITE_API_BASE_URL — прототип на фикстурах (Глава 8, ADR 0012); с ним — реальный API со входом
// администратора (глава 22, ADR 0026 п. 1). Сборка staging/production — `/v1` на том же origin.
const apiBaseUrl = import.meta.env.VITE_API_BASE_URL as string | undefined

function root() {
  if (!apiBaseUrl) {
    const repo = new PrototypeRepository({ role: 'admin', latencyMs: 250 })
    return <App repo={repo} demo={repo} />
  }
  const session = new ApiSession({ baseUrl: apiBaseUrl, store: sessionTokenStore('ev-admin-refresh') })
  return <SessionGate session={session} repo={new HttpAdminRepository(session)} />
}

createRoot(document.getElementById('root')!).render(<StrictMode>{root()}</StrictMode>)
