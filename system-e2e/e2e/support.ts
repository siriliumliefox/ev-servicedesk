// Опора межролевых E2E (глава 23, ADR 0027 п. 8): данные стека (backend/scripts/e2e_system.py seed), авто браузера,
// лента клиента, вход в приложения сотрудников и разовые задачи в контейнере API; общее — web-shared/e2e.ts.
import { execFileSync } from 'node:child_process'
import { readFileSync } from 'node:fs'
import { expect, test, type Page } from '@playwright/test'
import { aggregateStatus, api, guardCsp, submitLogin, type Account } from '@ev-servicedesk/web-shared/e2e'

export { api, staffToken, submitLogin, todayInMinsk } from '@ev-servicedesk/web-shared/e2e'

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

export interface FeedItem {
  type: string
  message: string
}

export async function feed(client: ClientAccount): Promise<FeedItem[]> {
  return (await api<{ items: FeedItem[] }>('GET', '/notifications?page_size=100', client.access_token)).items
}

/** Разовая задача в контейнере API стека (E2E_JOB_RUNNER — shlex-строка docker compose … exec -T backend). */
export function runJob(...args: string[]): string {
  const runner = process.env.E2E_JOB_RUNNER
  if (!runner) throw new Error('Нужен E2E_JOB_RUNNER — запускается из scripts/integration_stack.sh')
  return execFileSync('bash', ['-c', `${runner} "$@"`, '_', ...args], { encoding: 'utf8' })
}

export const ENGINEER_HEADING = 'EV-ServiceDesk · Кабинет инженера'
export const ADMIN_HEADING = 'Админ-панель · Дашборд'

/** Вход сотрудника с проверкой CSP страницы; `heading` — заголовок приложения после входа. */
export async function signIn(page: Page, url: string, account: Account, heading: string): Promise<void> {
  await guardCsp(page)
  await submitLogin(page, url, account)
  await expect(page.getByRole('heading', { name: heading })).toBeVisible()
}

/** Статус «светофор» агрегата так, как его видит клиент. */
export function clientStatus(client: ClientAccount, vehicleId: number, code: string): Promise<string> {
  return aggregateStatus(client.access_token, vehicleId, code)
}
