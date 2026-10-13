// Опора E2E админ-панели (глава 22, ADR 0026 п. 15): данные стека (backend/scripts/e2e_admin.py seed),
// вход администратора через экран входа и проверки «со стороны» — запросы к API от клиента и сотрудников:
// изменение в админ-панели проверяется по тому, что видит клиент, а не по экрану самой панели.
import { readFileSync } from 'node:fs'
import { expect, type Page } from '@playwright/test'

export interface Staff {
  id: number
  phone: string
  password: string
}

export interface Seed {
  admin: Staff
  engineers: Staff[]
  client: {
    access_token: string
    vehicle_id: number
    model_id: number
    model_label: string
    aggregate: string
    interval_km: number
    mileage: number
  }
  ticket_id: number
}

export function loadSeed(): Seed {
  const path = process.env.E2E_ADMIN_SEED
  if (!path) throw new Error('Нужен E2E_ADMIN_SEED — файл backend/scripts/e2e_admin.py seed')
  return JSON.parse(readFileSync(path, 'utf8')) as Seed
}

const API = `${process.env.API_BASE_URL ?? 'http://127.0.0.1:18080'}/v1`

/** Запрос к API напрямую (не через админ-панель); `expect` — ожидаемый статус. */
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

/** Вход сотрудника по API: код ответа — 200 (вошёл) или 401 (пароль не подходит, заблокирован). */
export async function staffLoginStatus(phone: string, password: string): Promise<number> {
  const response = await fetch(`${API}/auth/staff/login`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ phone, password }),
  })
  return response.status
}

export async function staffToken(staff: Staff): Promise<string> {
  const body = await api<{ access_token: string }>('POST', '/auth/staff/login', null, { phone: staff.phone, password: staff.password })
  return body.access_token
}

/** Статус «светофор» агрегата так, как его видит клиент (как мобильное приложение). */
export async function clientStatus(seed: Seed): Promise<string> {
  const { items } = await api<{ items: { aggregate_type_code: string; status: string }[] }>(
    'GET',
    `/vehicles/${seed.client.vehicle_id}/aggregate-statuses`,
    seed.client.access_token,
  )
  return items.find((s) => s.aggregate_type_code === seed.client.aggregate)!.status
}

export async function signIn(page: Page, staff: Staff): Promise<void> {
  await page.goto('/')
  await page.getByLabel('Телефон').fill(staff.phone)
  await page.getByLabel('Пароль').fill(staff.password)
  await page.getByRole('button', { name: 'Войти' }).click()
}

export async function signInAdmin(page: Page, seed: Seed): Promise<void> {
  await signIn(page, seed.admin)
  await expect(page.getByRole('heading', { name: 'Админ-панель · Дашборд' })).toBeVisible()
}

/** Карточка показателя дашборда по подписи. */
export function kpi(page: Page, label: string) {
  return page.locator('div', { has: page.getByText(label, { exact: true }) }).last()
}
