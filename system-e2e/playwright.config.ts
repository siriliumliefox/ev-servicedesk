// Межролевые E2E (глава 23, ADR 0027 п. 8): Playwright открывает кабинет инженера и админ-панель на одном стеке
// backend из образа (scripts/integration_stack.sh), клиент действует по API, как мобильное приложение.
// Приложения — production-сборки (`/v1`, CSP) в `vite preview`, который проксирует `/v1` (REST и WebSocket) на
// стек: тот же origin, как nginx в production. E2E_ENGINEER_DIST / E2E_ADMIN_DIST — готовые сборки (абсолютный
// путь, regression по артефактам staging, ADR 0027 п. 5); без них приложения собираются из исходников.
// Окружение: API_BASE_URL, E2E_SYSTEM_SEED (backend/scripts/e2e_system.py seed), E2E_JOB_RUNNER (витрина
// аналитики). Повторов нет (retries: 0) — нестабильный P0 чинится, а не перезапускается (ADR 0027 п. 6).
import { defineConfig, devices } from '@playwright/test'
import { ADMIN_URL, ENGINEER_URL } from './e2e/apps.ts'

const api = process.env.API_BASE_URL ?? 'http://127.0.0.1:18080'
const media = process.env.E2E_MEDIA_ORIGIN ?? 'http://127.0.0.1:19000'

function app(name: 'web-engineer' | 'web-admin', url: string, prebuilt: string | undefined) {
  const dist = prebuilt ?? `../system-e2e/.apps/${name}`
  const build = prebuilt ? '' : `npx vite build --outDir ${dist} --emptyOutDir && `
  const port = new URL(url).port
  return {
    command: `cd ../${name} && ${build}npx vite preview --outDir ${dist} --host 127.0.0.1 --port ${port} --strictPort`,
    url,
    reuseExistingServer: false,
    timeout: 180_000,
    env: { VITE_API_BASE_URL: '/v1', VITE_MEDIA_ORIGIN: media, EV_API_PROXY: api },
  }
}

export default defineConfig({
  testDir: './e2e',
  timeout: 120_000,
  expect: { timeout: 10_000 },
  fullyParallel: false,
  workers: 1,
  retries: 0,
  reporter: process.env.CI ? [['list'], ['html', { open: 'never', outputFolder: 'playwright-report' }]] : 'list',
  use: {
    viewport: { width: 1920, height: 1080 },
    locale: 'ru-RU',
    timezoneId: 'Europe/Minsk',
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
  },
  projects: [
    { name: 'chromium', use: { ...devices['Desktop Chrome'], viewport: { width: 1920, height: 1080 } } },
    { name: 'firefox', use: { ...devices['Desktop Firefox'], viewport: { width: 1920, height: 1080 } } },
    { name: 'webkit', use: { ...devices['Desktop Safari'], viewport: { width: 1920, height: 1080 } } },
  ],
  webServer: [
    app('web-engineer', ENGINEER_URL, process.env.E2E_ENGINEER_DIST),
    app('web-admin', ADMIN_URL, process.env.E2E_ADMIN_DIST),
  ],
})
