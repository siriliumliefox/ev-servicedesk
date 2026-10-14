// Опора E2E главы 21: данные стека (backend/scripts/e2e_engineer.py seed), клиент по API и его
// WebSocket — «синхронизация у клиента в реальном времени» проверяется по событиям, которые получил клиент.
import { readFileSync } from 'node:fs'
import { expect, test, type Locator, type Page } from '@playwright/test'
import { api, guardCsp, submitLogin, type Account } from '@ev-servicedesk/web-shared/e2e'

/** Тикеты одного браузера (клиент создаёт не больше 10 тикетов в час — их заводит seed, а не тест). */
export interface E2ESet {
  flow: number
  race_button: number
  race_drag: number
}

export interface Seed {
  engineers: Account[]
  client: {
    phone: string
    access_token: string
    refresh_token: string
    vehicle_id: number
    /** Контекст авто в карточке тикета (глава 23, E2E-07): модель, прошивка релиза E2E, агрегат с регламентом. */
    model_label: string
    firmware_version: string
    aggregate_name: string
  }
  quick_reply_title: string
  tickets: number[]
  e2e_sets: E2ESet[]
}

const PROJECTS = ['chromium', 'firefox', 'webkit']

/** Набор тикетов текущего браузера: chromium — 0, firefox — 1, webkit — 2 (seed --e2e-sets 3). */
export function ticketsFor(seed: Seed): E2ESet {
  const index = PROJECTS.indexOf(test.info().project.name)
  const set = seed.e2e_sets[index]
  if (!set) throw new Error(`Нет набора тикетов для ${test.info().project.name}: seed --e2e-sets ${index + 1}`)
  return set
}

export function loadSeed(): Seed {
  const path = process.env.E2E_ENGINEER_SEED
  if (!path) throw new Error('Нужен E2E_ENGINEER_SEED — файл backend/scripts/e2e_engineer.py seed')
  return JSON.parse(readFileSync(path, 'utf8')) as Seed
}

/** WebSocket стека — тот же адрес, что у REST (`web-shared/e2e.ts`). */
const WS = `${(process.env.API_BASE_URL ?? 'http://127.0.0.1:18080').replace(/^http/, 'ws')}/v1`

export interface ClientEvent {
  type: string
  data: { id: number; status?: string; body?: string; assigned_engineer_id?: number | null }
  at: number
}

/** Клиент тикета: REST с его токеном и подписка WebSocket (как мобильное приложение). */
export class ClientSide {
  readonly events: ClientEvent[] = []
  private socket: WebSocket | null = null
  private readonly token: string

  constructor(seed: Seed) {
    this.token = seed.client.access_token
  }

  api<T>(method: string, path: string, body?: unknown, expected = 200): Promise<T> {
    return api<T>(method, path, this.token, body, expected)
  }

  /** Подписка на тикет; resolve — после `ready`. */
  watch(ticketId: number): Promise<void> {
    const ws = new WebSocket(`${WS}/tickets/${ticketId}/ws`)
    this.socket = ws
    return new Promise((resolve, reject) => {
      ws.onopen = () => ws.send(JSON.stringify({ type: 'auth', access_token: this.token }))
      ws.onerror = () => reject(new Error('WebSocket клиента не подключился'))
      ws.onclose = (e) => reject(new Error(`WebSocket клиента закрыт ${e.code}`))
      ws.onmessage = (e) => {
        const frame = JSON.parse(String(e.data)) as ClientEvent
        if (frame.type === 'ready') return resolve()
        this.events.push({ ...frame, at: Date.now() })
      }
    })
  }

  /** Событие пришло клиенту не позже чем через `withinMs` после `since`. */
  async received(match: (e: ClientEvent) => boolean, since: number, withinMs = 2000): Promise<ClientEvent> {
    await expect
      .poll(() => this.events.find((e) => e.at >= since && match(e)), { timeout: withinMs + 3000 })
      .toBeTruthy()
    const event = this.events.find((e) => e.at >= since && match(e))!
    expect(event.at - since, 'задержка доставки клиенту, мс').toBeLessThanOrEqual(withinMs)
    return event
  }

  close() {
    this.socket?.close()
  }
}

/** Вход инженера через экран входа; нарушения CSP собираются и валят тест в конце. */
export async function signIn(page: Page, account: Account) {
  await guardCsp(page)
  await submitLogin(page, '/', account)
  await expect(page.getByRole('heading', { name: 'EV-ServiceDesk · Кабинет инженера' })).toBeVisible()
}

export const column = (page: Page, name: string) =>
  page.getByRole('region', { name: new RegExp(`^${name}`) })

export const card = (scope: Page | Locator, id: number) =>
  scope.getByRole('button', { name: new RegExp(`^Тикет #${id},`) })

/** Перенос мышью: нажать, сдвинуть плавно (датчик dnd-kit срабатывает после 6 px), отпустить в колонке. */
export async function dragWithMouse(page: Page, from: Locator, to: Locator) {
  const a = (await from.boundingBox())!
  const b = (await to.boundingBox())!
  await page.mouse.move(a.x + a.width / 2, a.y + a.height / 2)
  await page.mouse.down()
  await page.mouse.move(a.x + a.width / 2 + 10, a.y + a.height / 2, { steps: 5 })
  await page.mouse.move(b.x + b.width / 2, b.y + 120, { steps: 20 })
  await page.mouse.up()
}

/** Перенос с клавиатуры: Пробел — взять, стрелки — колонка, Пробел — положить. */
export async function dragWithKeyboard(page: Page, ticketId: number, steps: number) {
  await page.getByRole('button', { name: `Перенести тикет #${ticketId}` }).focus()
  await page.keyboard.press('Space')
  for (let i = 0; i < Math.abs(steps); i++) await page.keyboard.press(steps > 0 ? 'ArrowRight' : 'ArrowLeft')
  await page.keyboard.press('Space')
}
