// Глава 21 (ADR 0025): события тикета вживую, конфликт взятия, переназначение, тема, очередь в заголовке.
// Перетаскивание проверяет Playwright в браузере (e2e/): в jsdom у элементов нет размеров.
import { act, render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'
import {
  ApiError,
  ENGINEER_ID,
  OTHER_ENGINEER_ID,
  PrototypeRepository,
  type TicketDetail,
  type TicketLiveHandlers,
} from '@ev-servicedesk/web-shared'
import App from './App.tsx'

const NOW = new Date('2026-10-10T12:00:00Z')
const now = () => NOW

/** Прототип, у которого тест сам присылает события тикета (как сервер по WebSocket). */
class LiveRepository extends PrototypeRepository {
  readonly live = new Map<number, TicketLiveHandlers>()
  claimConflict = false

  watchTicket(ticketId: number, handlers: TicketLiveHandlers): () => void {
    this.live.set(ticketId, handlers)
    queueMicrotask(() => {
      handlers.onState?.('live')
      handlers.onReady()
    })
    return () => this.live.delete(ticketId)
  }

  claimTicket(ticketId: number): Promise<TicketDetail> {
    if (this.claimConflict) {
      return Promise.reject(new ApiError('TICKET_ALREADY_CLAIMED', 'Тикет уже взял в работу другой инженер.', 409))
    }
    return super.claimTicket(ticketId)
  }
}

function setup() {
  const repo = new LiveRepository({ role: 'engineer', now })
  const user = userEvent.setup()
  render(<App repo={repo} now={now} />)
  return { repo, user }
}

const card = (id: number) => screen.findByRole('button', { name: new RegExp(`^Тикет #${id},`) })
const panel = (id: number) => screen.findByRole('complementary', { name: `Карточка тикета #${id}` })

describe('карточка тикета вживую', () => {
  it('сообщение клиента и смена статуса приходят без перезагрузки', async () => {
    const { repo, user } = setup()
    await user.click(await card(1042))
    const aside = await panel(1042)
    expect(await within(aside).findByText('Обновляется вживую')).toBeInTheDocument()
    const handlers = repo.live.get(1042)!
    const ticket = await repo.getTicket(1042)
    await act(async () => {
      handlers.onMessage({
        id: 9001,
        author: { id: 501, phone: null, role: 'client', is_active: true, created_at: NOW.toISOString() },
        body: 'Пробки появились, спасибо',
        attachments: [],
        created_at: NOW.toISOString(),
      })
      handlers.onTicket({ ...ticket, status: 'waiting_vendor' })
    })
    expect(within(aside).getByText('Пробки появились, спасибо')).toBeInTheDocument()
    expect(within(aside).getAllByText('Ожидает вендора').length).toBeGreaterThan(0)
  })

  it('тикет переназначен другому инженеру — плашка, только чтение', async () => {
    const { repo, user } = setup()
    await user.click(await card(1042))
    const aside = await panel(1042)
    await within(aside).findByText('Обновляется вживую')
    const ticket = await repo.getTicket(1042)
    expect(ticket.assigned_engineer_id).toBe(ENGINEER_ID)
    await act(async () => repo.live.get(1042)!.onTicket({ ...ticket, assigned_engineer_id: OTHER_ENGINEER_ID }))
    expect(within(aside).getByRole('alert')).toHaveTextContent('Тикет переназначен другому инженеру.')
    expect(within(aside).getByLabelText('Ответ клиенту')).toBeDisabled()
    expect(within(aside).queryByRole('button', { name: 'Решено' })).toBeNull()
  })

  it('доступ потерян (4403) у тикета из очереди — «уже взял другой инженер»', async () => {
    const { repo, user } = setup()
    await user.click(await card(1056))
    const aside = await panel(1056)
    await within(aside).findByRole('button', { name: 'Взять в работу' })
    await act(async () => repo.live.get(1056)!.onLost())
    expect(within(aside).getByRole('alert')).toHaveTextContent('Тикет уже взял в работу другой инженер.')
    expect(within(aside).queryByRole('button', { name: 'Взять в работу' })).toBeNull()
  })

  it('проигрыш в гонке за тикет (409 TICKET_ALREADY_CLAIMED) — плашка вместо ошибки', async () => {
    const { repo, user } = setup()
    repo.claimConflict = true
    await user.click(await card(1056))
    const aside = await panel(1056)
    await user.click(await within(aside).findByRole('button', { name: 'Взять в работу' }))
    expect(within(aside).getByRole('alert')).toHaveTextContent('Тикет уже взял в работу другой инженер.')
  })
})

describe('доска и оформление', () => {
  it('размер очереди — в заголовке вкладки', async () => {
    setup()
    await card(1056)
    expect(document.title).toBe('(4) Очередь · EV-ServiceDesk · Кабинет инженера')
  })

  it('тема: «Как в системе / Светлая / Тёмная», выбор запоминается', async () => {
    const { user } = setup()
    await card(1042)
    expect(document.documentElement.dataset.theme).toBe('dark')
    await user.selectOptions(screen.getByLabelText('Тема'), 'Светлая')
    expect(document.documentElement.dataset.theme).toBe('light')
    expect(localStorage.getItem('ev-theme')).toBe('light')
    await user.selectOptions(screen.getByLabelText('Тема'), 'Как в системе')
    expect(localStorage.getItem('ev-theme')).toBe('system')
  })
})
