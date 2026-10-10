// Прототип кабинета инженера (Глава 8, ADR 0012): ключевые сценарии и подсчёт кликов для типовых операций
// (MASTER_CHECKLIST, «Подсчёт кликов для типовых операций инженера»). Клик = одно нажатие мыши; ввод
// текста кликом не считается. Таблица — docs/design/WEB_PROTOTYPE.md.
import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'
import { PrototypeRepository } from '@ev-servicedesk/web-shared'
import App from './App.tsx'

const NOW = new Date('2026-10-10T12:00:00Z')
const now = () => NOW

function setup(configure?: (repo: PrototypeRepository) => void) {
  const repo = new PrototypeRepository({ role: 'engineer', now })
  configure?.(repo)
  const user = userEvent.setup()
  let clicks = 0
  const click = async (element: Element) => {
    clicks += 1
    await user.click(element)
  }
  render(<App repo={repo} now={now} demo={repo} />)
  return { repo, user, click, clicks: () => clicks }
}

const column = (name: string) => screen.getByRole('region', { name: new RegExp(`^${name}`) })
const card = (id: number) => screen.findByRole('button', { name: new RegExp(`^Тикет #${id},`) })
const cardIds = (name: string) =>
  within(column(name))
    .queryAllByRole('button', { name: /^Тикет #/ })
    .map((b) => Number(/#(\d+)/.exec(b.getAttribute('aria-label') ?? '')?.[1]))

describe('канбан-доска', () => {
  it('четыре колонки по статусам, тёмная тема по умолчанию', async () => {
    setup()
    await card(1042)
    expect(document.documentElement.dataset.theme).toBe('dark')
    expect(cardIds('Новые')).toEqual([1058, 1057, 1056, 1055])
    expect(cardIds('В работе')).toEqual([1042, 1050, 1049])
    expect(cardIds('Ожидает вендора')).toEqual([1038, 1044])
    expect(cardIds('Решено')).toEqual([1031, 1029])
  })

  it('в колонке — сначала самый ранний срок SLA; SLA подписан текстом', async () => {
    setup()
    const first = await card(1058)
    expect(first).toHaveTextContent('Просрочен на 1 ч')
    expect(await card(1057)).toHaveTextContent('Осталось 40 мин')
  })

  it('фильтр по категории и «Без исполнителя»', async () => {
    const { user, click } = setup()
    await card(1042)
    await user.selectOptions(screen.getByLabelText('Категория'), 'Навигация')
    expect([...cardIds('Новые'), ...cardIds('В работе'), ...cardIds('Ожидает вендора')]).toEqual([1056, 1042, 1044])
    await user.selectOptions(screen.getByLabelText('Категория'), 'Все категории')
    await click(screen.getByRole('button', { name: 'Без исполнителя' }))
    expect(cardIds('В работе')).toEqual([])
    expect(cardIds('Новые')).toHaveLength(4)
  })

  it('пустая система — пустое состояние', async () => {
    setup((repo) => repo.setScenario('empty'))
    expect(await screen.findByText('Обращений пока нет')).toBeInTheDocument()
  })

  it('нет сети — ошибка с «Повторить», после восстановления доска загружается', async () => {
    const { repo, click } = setup((r) => r.setOffline(true))
    expect(await screen.findByRole('alert')).toHaveTextContent('Нет соединения')
    repo.setOffline(false)
    await click(screen.getByRole('button', { name: 'Повторить' }))
    expect(await card(1042)).toBeInTheDocument()
  })
})

describe('карточка тикета', () => {
  it('чужой тикет — действий нет, ответ недоступен', async () => {
    const { click } = setup()
    await click(await card(1050))
    const panel = await screen.findByRole('complementary', { name: 'Карточка тикета #1050' })
    expect(await within(panel).findByText(/Тикет ведёт Инженер #8/)).toBeInTheDocument()
    expect(within(panel).queryByRole('button', { name: 'Взять в работу' })).toBeNull()
    expect(within(panel).getByLabelText('Ответ клиенту')).toBeDisabled()
  })

  it('выбранный тикет — в адресе; Escape закрывает карточку', async () => {
    const { user, click } = setup()
    await click(await card(1042))
    expect(window.location.hash).toBe('#/tickets/1042')
    await screen.findByRole('complementary', { name: 'Карточка тикета #1042' })
    await user.keyboard('{Escape}')
    expect(screen.queryByRole('complementary', { name: /Карточка тикета/ })).toBeNull()
  })
})

describe('подсчёт кликов: типовые операции инженера', () => {
  it('найти просроченные тикеты — 1 клик', async () => {
    const { click, clicks } = setup()
    await card(1042)
    await click(screen.getByRole('button', { name: /^Просрочен/ }))
    expect([...cardIds('Новые'), ...cardIds('В работе'), ...cardIds('Ожидает вендора'), ...cardIds('Решено')]).toEqual([
      1058, 1042, 1038,
    ])
    expect(clicks()).toBe(1)
  })

  it('взять новый тикет в работу — 2 клика', async () => {
    const { click, clicks } = setup()
    await click(await card(1056))
    await click(await screen.findByRole('button', { name: 'Взять в работу' }))
    await screen.findByRole('button', { name: 'Решено' })
    expect(cardIds('В работе')).toContain(1056)
    expect(await card(1056)).toHaveTextContent('Вы')
    expect(clicks()).toBe(2)
  })

  it('отправить клиенту инструкцию из базы знаний — 3 клика', async () => {
    const { click, clicks } = setup()
    await click(await card(1042))
    await click(await screen.findByRole('button', { name: 'Быстрые ответы' }))
    await click(await screen.findByRole('button', { name: 'Отправить клиенту: Li Auto L7: Яндекс Навигатор на штатном экране' }))
    const chat = screen.getByRole('region', { name: 'Переписка' })
    expect(await within(chat).findByText(/Навигатор установлен при русификации/)).toBeInTheDocument()
    expect(clicks()).toBe(3)
  })

  it('ответ с поиском по базе знаний: вставить и дописать — 4 клика', async () => {
    const { user, click, clicks } = setup()
    await click(await card(1057))
    await click(await screen.findByRole('button', { name: 'Взять в работу' }))
    await click(await screen.findByRole('button', { name: 'Быстрые ответы' }))
    await user.keyboard('APN')
    await click(await screen.findByRole('button', { name: 'Вставить в ответ: Настройка APN для SIM-карты автомобиля' }))
    expect((screen.getByLabelText('Ответ клиенту') as HTMLTextAreaElement).value).toContain('APN — internet')
    await user.type(screen.getByLabelText('Ответ клиенту'), ' Напишите, если не поможет.')
    await click(screen.getByRole('button', { name: 'Отправить' }))
    expect(await screen.findByText(/Напишите, если не поможет/)).toBeInTheDocument()
    expect(clicks()).toBe(5) // с «Взять в работу»; сам ответ — 4: тикет, «Быстрые ответы», «Вставить», «Отправить»
  })

  it('сменить статус на «Ожидает вендора» — 2 клика', async () => {
    const { click, clicks } = setup()
    await click(await card(1042))
    await click(await screen.findByRole('button', { name: 'Ожидает вендора' }))
    await screen.findByRole('button', { name: 'Вернуть в работу' })
    expect(cardIds('Ожидает вендора')).toContain(1042)
    expect(clicks()).toBe(2)
  })

  it('закрыть тикет («Решено») — 2 клика', async () => {
    const { click, clicks } = setup()
    await click(await card(1049))
    await click(await screen.findByRole('button', { name: 'Решено' }))
    await screen.findByRole('button', { name: 'Вернуть в работу' })
    expect(cardIds('Решено')).toContain(1049)
    expect(clicks()).toBe(2)
  })

  it('статусы агрегатов и история ТО авто клиента — 1 клик', async () => {
    const { click, clicks } = setup()
    await click(await card(1042))
    const panel = await screen.findByRole('complementary', { name: 'Карточка тикета #1042' })
    const aggregates = await within(panel).findByRole('region', { name: 'Статусы агрегатов' })
    expect(within(aggregates).getByText('Масло двигателя').closest('li')).toHaveTextContent('Требуется замена')
    expect(within(panel).getByText('LLXAB3CF7SA067890')).toBeInTheDocument()
    expect(await within(panel).findByText(/Плановое ТО-2/)).toBeInTheDocument()
    expect(clicks()).toBe(1)
  })
})
