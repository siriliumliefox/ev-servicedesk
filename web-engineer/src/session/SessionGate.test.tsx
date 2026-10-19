// Вход инженера (глава 21, ADR 0025 п. 1, 3): роль engineer, отказ client/admin, «Сессия завершена»,
// восстановление после перезагрузки. Сервер — подменённый fetch.
import { act, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'
import { ApiSession, HttpEngineerRepository, memoryTokenStore } from '@ev-servicedesk/web-shared'
import { SessionGate } from './SessionGate.tsx'

const BASE = 'http://api.test/v1'
const PASSWORD = 'correct horse battery staple'

const json = (status: number, body: unknown) =>
  new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })

function backend(role: 'engineer' | 'admin') {
  const user = { id: 7, phone: '+375291112233', role, is_active: true, created_at: '2026-10-01T00:00:00Z' }
  const state = { refreshOk: true, refreshes: 0, phones: [] as string[] }
  const empty = { items: [], meta: { page: 1, page_size: 100, total_items: 0, total_pages: 0 } }
  const fetch = async (input: RequestInfo | URL, init?: RequestInit) => {
    const request = input instanceof Request ? input : new Request(input, init)
    const path = new URL(request.url).pathname.replace('/v1', '')
    if (path === '/auth/staff/login') {
      const body = (await request.json()) as { phone: string; password: string }
      state.phones.push(body.phone)
      if (body.password !== PASSWORD) return json(401, { error: { code: 'UNAUTHORIZED', message: 'x' } })
      return json(200, { access_token: 'a1', refresh_token: 'r1', expires_in: 900, user })
    }
    if (path === '/auth/refresh') {
      state.refreshes += 1
      if (!state.refreshOk) return json(401, { error: { code: 'UNAUTHORIZED', message: 'x' } })
      return json(200, { access_token: 'a2', refresh_token: 'r2', expires_in: 900 })
    }
    if (path === '/auth/logout') return new Response(null, { status: 204 })
    if (path === '/me') return json(200, user)
    if (path === '/tickets') return json(200, empty)
    return json(404, { error: { code: 'NOT_FOUND', message: 'x' } })
  }
  return { fetch, state }
}

function setup(role: 'engineer' | 'admin', store = memoryTokenStore()) {
  const server = backend(role)
  const session = new ApiSession({ baseUrl: BASE, store, fetch: server.fetch })
  render(<SessionGate session={session} repo={new HttpEngineerRepository(session)} />)
  return { session, server, store, user: userEvent.setup() }
}

async function login(user: ReturnType<typeof userEvent.setup>, password = PASSWORD) {
  await user.clear(screen.getByLabelText('Телефон'))
  await user.type(screen.getByLabelText('Телефон'), '+375291112233')
  await user.type(screen.getByLabelText('Пароль'), password)
  await user.click(screen.getByRole('button', { name: 'Войти' }))
}

describe('вход инженера', () => {
  it('неверный пароль — понятная ошибка, кабинет не открывается', async () => {
    const { user } = setup('engineer')
    await login(user, 'wrong')
    expect(await screen.findByRole('alert')).toHaveTextContent('Неверный номер телефона или пароль.')
    expect(screen.queryByText('EV-ServiceDesk · Кабинет инженера')).toBeNull()
  })

  // #114 (X2): поле начинается с «+375» — номер, вставленный целиком, не превращается в +375+375….
  it('номер, вставленный поверх префикса +375, уходит одним номером', async () => {
    const { user, server } = setup('engineer')
    const phone = screen.getByLabelText('Телефон')
    expect(phone).toHaveValue('+375')
    await user.click(phone)
    await user.paste('+375 29 111-22-33')
    await user.type(screen.getByLabelText('Пароль'), PASSWORD)
    await user.click(screen.getByRole('button', { name: 'Войти' }))
    expect(await screen.findByText('Обращений пока нет')).toBeInTheDocument()
    expect(server.state.phones).toEqual(['+375291112233'])
  })

  it('инженер входит — доска; «Выйти» возвращает ко входу', async () => {
    const { user, store } = setup('engineer')
    await login(user)
    expect(await screen.findByText('Обращений пока нет')).toBeInTheDocument()
    expect(screen.getByText('Инженер +375291112233')).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Выйти' }))
    expect(await screen.findByRole('button', { name: 'Войти' })).toBeInTheDocument()
    expect(store.get()).toBeNull()
  })

  it('администратор — отказ: кабинет только для инженеров, сессия не сохраняется', async () => {
    const { user, store } = setup('admin')
    await login(user)
    expect(await screen.findByRole('alert')).toHaveTextContent('Администратор работает в админ-панели')
    expect(store.get()).toBeNull()
  })

  it('refresh отклонён (сессия истекла, сотрудник заблокирован) — вход с «Сессия завершена»', async () => {
    const { user, session, server } = setup('engineer')
    await login(user)
    await screen.findByText('Обращений пока нет')
    server.state.refreshOk = false
    await act(async () => {
      await session.refresh().catch(() => undefined)
    })
    expect(await screen.findByRole('status')).toHaveTextContent('Сессия завершена, войдите снова.')
  })

  it('перезагрузка вкладки — сессия восстанавливается по refresh-токену без входа', async () => {
    const store = memoryTokenStore()
    store.set('r1')
    const { server } = setup('engineer', store)
    expect(await screen.findByText('Обращений пока нет')).toBeInTheDocument()
    expect(server.state.refreshes).toBe(1)
  })
})
