// Опора межролевых E2E (глава 23, ADR 0027 п. 8): данные стека (backend/scripts/e2e_system.py seed), запросы
// клиента и сотрудника по API, вход в приложения сотрудников с проверкой CSP, разовые задачи в контейнере API.
import { execFileSync } from 'node:child_process'
import { readFileSync } from 'node:fs'
import { expect, test, type Page } from '@playwright/test'

export interface Account {
  phone: string
  password: string
}

export interface Car {
  id: number
  /** Агрегаты сценариев: `replace` — E2E-08, `golden` — E2E-16 (оба «требуется замена» после seed). */
  aggregates: { replace: string; golden: string }
  aggregate_names: { replace: string; golden: string }
}

export interface ClientAccount {
  phone: string
  access_token: string
  user_id: number
}

export interface Seed {
  admin: Account & { id: number }
  engineer: Account & { id: number }
  client_x: ClientAccount & { model_id: number; cars: Car[] }
  client_y: ClientAccount & { id: number; model_id: number }
  model_label: string
}

export function loadSeed(): Seed {
  const path = process.env.E2E_SYSTEM_SEED
  if (!path) throw new Error('Нужен E2E_SYSTEM_SEED — файл backend/scripts/e2e_system.py seed')
  return JSON.parse(readFileSync(path, 'utf8')) as Seed
}

const PROJECTS = ['chromium', 'firefox', 'webkit']

/** Авто клиента X текущего браузера: chromium — 0, firefox — 1, webkit — 2 (seed --sets 3). */
export function carFor(seed: Seed): Car {
  const index = PROJECTS.indexOf(test.info().project.name)
  const car = seed.client_x.cars[index]
  if (!car) throw new Error(`Нет авто для ${test.info().project.name}: seed --sets ${index + 1}`)
  return car
}

const API = `${process.env.API_BASE_URL ?? 'http://127.0.0.1:18080'}/v1`

/** Запрос к API напрямую (клиент — как мобильное приложение); `expected` — ожидаемый статус. */
export async function api<T>(method: string, path: string, token: string | null, body?: unknown, expected = 200): Promise<T> {
  const response = await fetch(`${API}${path}`, {
    method,
    headers: { ...(token ? { Authorization: `Bearer ${token}` } : {}), 'Content-Type': 'application/json' },
    body: body === undefined ? undefined : JSON.stringify(body),
  })
  const text = await response.text()
  expect(response.status, `${method} ${path} → ${response.status} ${text}`).toBe(expected)
  return (text ? JSON.parse(text) : undefined) as T
}

export async function staffToken(account: Account): Promise<string> {
  const body = await api<{ access_token: string }>('POST', '/auth/staff/login', null, account)
  return body.access_token
}

/** Статус «светофор» агрегата так, как его видит клиент. */
export async function clientStatus(client: ClientAccount, vehicleId: number, code: string): Promise<string> {
  const { items } = await api<{ items: { aggregate_type_code: string; status: string }[] }>(
    'GET',
    `/vehicles/${vehicleId}/aggregate-statuses`,
    client.access_token,
  )
  return items.find((s) => s.aggregate_type_code === code)?.status ?? 'нет агрегата'
}

export interface FeedItem {
  type: string
  message: string
}

export async function feed(client: ClientAccount): Promise<FeedItem[]> {
  return (await api<{ items: FeedItem[] }>('GET', '/notifications?page_size=100', client.access_token)).items
}

/** Сегодня по Минску (YYYY-MM-DD) — период аналитики (ADR 0020). */
export function todayInMinsk(): string {
  return new Intl.DateTimeFormat('en-CA', { timeZone: 'Europe/Minsk' }).format(new Date())
}

/** Разовая задача в контейнере API стека (E2E_JOB_RUNNER — shlex-строка docker compose … exec -T backend). */
export function runJob(...args: string[]): string {
  const runner = process.env.E2E_JOB_RUNNER
  if (!runner) throw new Error('Нужен E2E_JOB_RUNNER — запускается из scripts/integration_stack.sh')
  return execFileSync('bash', ['-c', `${runner} "$@"`, '_', ...args], { encoding: 'utf8' })
}

/** Нарушения CSP за тест — проверяются после каждого теста. */
const violations: string[] = []

test.afterEach(() => {
  const found = violations.splice(0)
  expect(found, 'нарушения CSP').toEqual([])
})

/** Заполнить форму входа приложения сотрудника (результат проверяет тест). */
export async function submitLogin(page: Page, url: string, account: Account): Promise<void> {
  // Нарушение CSP — с источником; без источника — инъекция самого Playwright (см. web-engineer/e2e/support.ts).
  await page.addInitScript(() => {
    document.addEventListener('securitypolicyviolation', (e) => {
      if (!e.sourceFile) return
      console.error(`CSP-VIOLATION ${e.violatedDirective} blocked=${e.blockedURI} source=${e.sourceFile}:${e.lineNumber}`)
    })
  })
  page.on('console', (message) => {
    if (message.text().startsWith('CSP-VIOLATION')) violations.push(message.text())
  })
  await page.goto(url)
  await page.getByLabel('Телефон').fill(account.phone)
  await page.getByLabel('Пароль').fill(account.password)
  await page.getByRole('button', { name: 'Войти' }).click()
}

export const ENGINEER_HEADING = 'EV-ServiceDesk · Кабинет инженера'
export const ADMIN_HEADING = 'Админ-панель · Дашборд'

export async function signIn(page: Page, url: string, account: Account, heading: string): Promise<void> {
  await submitLogin(page, url, account)
  await expect(page.getByRole('heading', { name: heading })).toBeVisible()
}
