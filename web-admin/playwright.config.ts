// E2E админ-панели (глава 22, ADR 0026 п. 13–15): Playwright против стека backend из образа-кандидата
// (scripts/integration_stack.sh). Админ-панель — production-сборка (`/v1`, CSP) в `vite preview`, который
// проксирует `/v1` на стек: тот же origin, как nginx в production.
// Окружение: API_BASE_URL (стек), E2E_ADMIN_SEED (файл backend/scripts/e2e_admin.py seed).
// CI — только Chromium (`--project=chromium`); WebKit и Firefox — локально или ручным запуском ci.yml.
import { defineConfig, devices } from '@playwright/test'

const PORT = 4174
const api = process.env.API_BASE_URL ?? 'http://127.0.0.1:18080'

export default defineConfig({
  testDir: './e2e',
  timeout: 90_000,
  expect: { timeout: 10_000 },
  fullyParallel: false,
  workers: 1,
  retries: 0,
  reporter: process.env.CI ? [['list'], ['html', { open: 'never', outputFolder: 'playwright-report' }]] : 'list',
  use: {
    baseURL: `http://127.0.0.1:${PORT}`,
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
  webServer: {
    command: `npx vite build && npx vite preview --host 127.0.0.1 --port ${PORT} --strictPort`,
    url: `http://127.0.0.1:${PORT}`,
    reuseExistingServer: false,
    timeout: 120_000,
    env: { VITE_API_BASE_URL: '/v1', EV_API_PROXY: api },
  },
})
