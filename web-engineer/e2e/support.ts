// Опора E2E главы 21: данные стека (backend/scripts/e2e_engineer.py seed), клиент по API и его
// WebSocket — «синхронизация у клиента в реальном времени» проверяется по событиям, которые получил клиент.
import { readFileSync } from 'node:fs'
import { expect, test, type Locator, type Page } from '@playwright/test'

/** Тикеты одного браузера (клиент создаёт не больше 10 тикетов в час — их заводит seed, а не тест). */
export interface E2ESet {
  flow: number
  race_button: number
  race_drag: number
}

export interface Seed {
  engineers: { phone: string; password: string }[]
  client: { phone: string; access_token: string; refresh_token: string; vehicle_id: number }
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

const API = `${process.env.API_BASE_URL ?? 'http://127.0.0.1:18080'}/v1`

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

  async api<T>(method: string, path: string, body?: unknown): Promise<T> {
    const response = await fetch(`${API}${path}`, {
      method,
      headers: { Authorization: `Bearer ${this.token}`, 'Content-Type': 'application/json' },
      body: body === undefined ? undefined : JSON.stringify(body),
    })
    expect(response.ok, `${method} ${path} → ${response.status} ${await response.clone().text()}`).toBe(true)
    return (await response.json()) as T
  }

  /** Подписка на тикет; resolve — после `ready`. */
  watch(ticketId: number): Promise<void> {
    const ws = new WebSocket(`${API.replace(/^http/, 'ws')}/tickets/${ticketId}/ws`)
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

/** Вход инженера через экран входа; нарушения CSP в консоли — падение теста. */
export async function signIn(page: Page, account: { phone: string; password: string }) {
  page.on('console', (message) => {
    if (/Content[- ]Security[- ]Policy/i.test(message.text())) throw new Error(`CSP: ${message.text()}`)
  })
  await page.goto('/')
  await page.getByLabel('Телефон').fill(account.phone)
  await page.getByLabel('Пароль').fill(account.password)
  await page.getByRole('button', { name: 'Войти' }).click()
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
