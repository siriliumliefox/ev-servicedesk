import tailwindcss from '@tailwindcss/vite'
import react from '@vitejs/plugin-react'
import { defineConfig, loadEnv, type Plugin } from 'vite'

// API на том же origin (ADR 0026 п. 1, как ADR 0025 п. 2): dev и preview проксируют `/v1` на backend —
// EV_API_PROXY, по умолчанию локальный uvicorn. В production то же делает nginx (глава 26).
const apiProxy = (target: string) => ({ '/v1': { target, ws: true, changeOrigin: false } })

/**
 * CSP сборки (ADR 0025 п. 4) — `<meta>` в index.html: скрипты, стили и запросы — только свой origin.
 * Медиа статей — ссылками в Markdown (ADR 0018), админ-панель их не загружает: img-src — свой origin и
 * data: (иконки). В dev не ставится: HMR Vite работает через inline-скрипты.
 */
function contentSecurityPolicy(): Plugin {
  const policy = [
    "default-src 'self'",
    "script-src 'self'",
    "style-src 'self'",
    "font-src 'self'",
    "connect-src 'self'",
    "img-src 'self' data:",
    "object-src 'none'",
    "base-uri 'self'",
    "form-action 'self'",
  ].join('; ')
  return {
    name: 'ev-csp',
    apply: 'build',
    transformIndexHtml: () => [{ tag: 'meta', attrs: { 'http-equiv': 'Content-Security-Policy', content: policy }, injectTo: 'head-prepend' }],
  }
}

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), '')
  const proxy = apiProxy(env.EV_API_PROXY || 'http://127.0.0.1:8000')
  return {
    plugins: [react(), tailwindcss(), contentSecurityPolicy()],
    server: { proxy },
    preview: { proxy },
  }
})
