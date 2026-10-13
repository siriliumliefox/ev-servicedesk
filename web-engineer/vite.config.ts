import tailwindcss from '@tailwindcss/vite'
import react from '@vitejs/plugin-react'
import { defineConfig, loadEnv } from 'vite'
import { apiProxy, contentSecurityPolicy } from '@ev-servicedesk/web-shared/vite'

// API на том же origin и CSP сборки — общие для кабинетов сотрудников (web-shared/vite.ts, ADR 0025 п. 2, 4).
export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), '')
  const proxy = apiProxy(env.EV_API_PROXY || undefined)
  return {
    plugins: [react(), tailwindcss(), contentSecurityPolicy(env.VITE_MEDIA_ORIGIN ?? '')],
    server: { proxy },
    preview: { proxy },
  }
})
