// Опора E2E админ-панели (глава 22, ADR 0026 п. 15): данные стека (backend/scripts/e2e_admin.py seed),
// вход администратора через экран входа и проверки «со стороны» — запросы к API от клиента и сотрудников:
// изменение в админ-панели проверяется по тому, что видит клиент, а не по экрану самой панели.
import { readFileSync } from 'node:fs'
import { expect, type Page } from '@playwright/test'
import { aggregateStatus, submitLogin } from '@ev-servicedesk/web-shared/e2e'

export { api, staffLoginStatus, staffToken } from '@ev-servicedesk/web-shared/e2e'

export interface Staff {
  id: number
  phone: string
  password: string
}

export interface Seed {
  admin: Staff
  client: {
    access_token: string
    vehicle_id: number
    model_id: number
    model_label: string
    aggregate: string
    interval_km: number
    mileage: number
  }
  /** Наборы сценария «пользователи» по браузеру — `forBrowser` (seed --sets 3). */
  user_sets: { engineers: [Staff, Staff]; ticket_id: number }[]
}

export function loadSeed(): Seed {
  const path = process.env.E2E_ADMIN_SEED
  if (!path) throw new Error('Нужен E2E_ADMIN_SEED — файл backend/scripts/e2e_admin.py seed')
  return JSON.parse(readFileSync(path, 'utf8')) as Seed
}

/** Статус «светофор» агрегата клиента сценария так, как его видит клиент (как мобильное приложение). */
export function clientStatus(seed: Seed): Promise<string> {
  return aggregateStatus(seed.client.access_token, seed.client.vehicle_id, seed.client.aggregate)
}

export function signIn(page: Page, staff: Staff): Promise<void> {
  return submitLogin(page, '/', staff)
}

export async function signInAdmin(page: Page, seed: Seed): Promise<void> {
  await signIn(page, seed.admin)
  await expect(page.getByRole('heading', { name: 'Админ-панель · Дашборд' })).toBeVisible()
}

/** Карточка показателя дашборда по подписи. */
export function kpi(page: Page, label: string) {
  return page.locator('div', { has: page.getByText(label, { exact: true }) }).last()
}
