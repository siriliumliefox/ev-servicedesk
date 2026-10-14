// E2E веб-кабинета инженера (глава 21, ADR 0025 п. 14): Playwright против стека backend из образа-кандидата
// (scripts/integration_stack.sh). Кабинет — production-сборка (`/v1`, CSP) в `vite preview`, который
// проксирует `/v1` (REST и WebSocket) на стек: тот же origin, как nginx в production.
// Окружение: API_BASE_URL (стек), E2E_ENGINEER_SEED (файл backend/scripts/e2e_engineer.py seed).
// CI — только Chromium (`--project=chromium`); WebKit и Firefox — локально перед merge.
import { defineConfig, devices } from '@playwright/test'

const PORT = 4173
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
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
  },
  projects: [
    { name: 'chromium', use: { ...devices['Desktop Chrome'], viewport: { width: 1920, height: 1080 } } },
    { name: 'firefox', use: { ...devices['Desktop Firefox'], viewport: { width: 1920, height: 1080 } } },
    { name: 'webkit', use: { ...devices['Desktop Safari'], viewport: { width: 1920, height: 1080 } } },
  ],
  webServer: {
    // Regression (глава 23, ADR 0027 п. 5): E2E_ENGINEER_DIST — готовая сборка cd-staging (абсолютный путь).
    command: process.env.E2E_ENGINEER_DIST
      ? `npx vite preview --outDir ${process.env.E2E_ENGINEER_DIST} --host 127.0.0.1 --port ${PORT} --strictPort`
      : `npx vite build && npx vite preview --host 127.0.0.1 --port ${PORT} --strictPort`,
    url: `http://127.0.0.1:${PORT}`,
    reuseExistingServer: false,
    timeout: 120_000,
    env: {
      VITE_API_BASE_URL: '/v1',
      VITE_MEDIA_ORIGIN: process.env.E2E_MEDIA_ORIGIN ?? 'http://127.0.0.1:19000',
      EV_API_PROXY: api,
    },
  },
})
