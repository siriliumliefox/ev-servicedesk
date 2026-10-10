import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { PrototypeRepository } from '@ev-servicedesk/web-shared'
import './index.css'
import App from './App.tsx'

// Прототип (Глава 8, ADR 0012): фикстуры по OpenAPI v1 вместо API. HTTP-репозиторий — Глава 22.
const repo = new PrototypeRepository({ role: 'admin', latencyMs: 250 })

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <App repo={repo} demo={repo} />
  </StrictMode>,
)
