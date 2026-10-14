// Фиксация замены агрегата и работы по нему из карточки тикета (E-05, глава 23, ADR 0027 п. 14):
// замена сбрасывает «светофор» и пишет историю ТО, работа без замены статус не меняет, ошибки контракта — у поля.
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'
import { PrototypeRepository } from '@ev-servicedesk/web-shared'
import App from '../App.tsx'

const NOW = new Date('2026-10-10T12:00:00Z')
const now = () => NOW

function setup() {
  const repo = new PrototypeRepository({ role: 'engineer', now })
  const user = userEvent.setup()
  let clicks = 0
  const click = async (element: Element) => {
    clicks += 1
    await user.click(element)
  }
  render(<App repo={repo} now={now} demo={repo} />)
  return { repo, user, click, clicks: () => clicks }
}

async function openTicket(click: (e: Element) => Promise<void>, id: number) {
  await click(await screen.findByRole('button', { name: new RegExp(`^Тикет #${id},`) }))
  return screen.findByRole('complementary', { name: `Карточка тикета #${id}` })
}

const aggregateRow = (panel: HTMLElement, name: string) =>
  within(within(panel).getByRole('region', { name: 'Статусы агрегатов' })).getByText(name).closest('li') as HTMLElement

describe('замена агрегата и работы (E-05)', () => {
  it('замена из карточки своего тикета — 3 клика: статус 🟢, запись в истории ТО', async () => {
    const { click, clicks } = setup()
    const panel = await openTicket(click, 1042)
    expect(aggregateRow(panel, 'Масло двигателя')).toHaveTextContent('Требуется замена')

    await click(within(panel).getByRole('button', { name: 'Замена или работа: Масло двигателя' }))
    const form = within(panel).getByRole('form', { name: 'Замена или работа: Масло двигателя' })
    expect(within(form).getByRole('radio', { name: /Замена/ })).toBeChecked()
    expect(within(form).getByLabelText('Дата замены')).toHaveValue('2026-10-10')
    expect(within(form).getByLabelText('Пробег, км')).toHaveValue(41250)
    await click(within(form).getByRole('button', { name: 'Сохранить' }))

    expect(await within(panel).findByRole('status')).toHaveTextContent('Замена сохранена: Масло двигателя')
    await waitFor(() => expect(aggregateRow(panel, 'Масло двигателя')).toHaveTextContent('Заменено'))
    const history = within(panel).getByRole('region', { name: 'История ТО' })
    expect(await within(history).findByText(/10 окт\. 2026 г\. · 41\s250 км/)).toBeInTheDocument()
    expect(clicks()).toBe(3)
  })

  it('пробег замены больше пробега авто — ошибка у поля, форма остаётся', async () => {
    const { user, click } = setup()
    const panel = await openTicket(click, 1042)
    await click(within(panel).getByRole('button', { name: 'Замена или работа: Масляный фильтр' }))
    const form = within(panel).getByRole('form', { name: 'Замена или работа: Масляный фильтр' })
    const mileage = within(form).getByLabelText('Пробег, км')
    await user.clear(mileage)
    await user.type(mileage, '50000')
    await click(within(form).getByRole('button', { name: 'Сохранить' }))
    expect(await within(form).findByText(/больше текущего пробега авто/)).toBeInTheDocument()
    expect(mileage).toHaveAttribute('aria-invalid', 'true')
    expect(aggregateRow(panel, 'Масляный фильтр')).toHaveTextContent('Скоро менять')
  })

  it('работа без замены — статус не меняется, запись в истории', async () => {
    const { user, click } = setup()
    const panel = await openTicket(click, 1042)
    await click(within(panel).getByRole('button', { name: 'Замена или работа: Салонный фильтр' }))
    const form = within(panel).getByRole('form', { name: 'Замена или работа: Салонный фильтр' })
    await click(within(form).getByRole('radio', { name: /Работа без замены/ }))
    expect(within(form).getByLabelText('Дата работы')).toBeInTheDocument()
    await user.type(within(form).getByLabelText('Комментарий'), 'Осмотр, продувка')
    await click(within(form).getByRole('button', { name: 'Сохранить' }))
    expect(await within(panel).findByRole('status')).toHaveTextContent('Работа сохранена: Салонный фильтр')
    expect(aggregateRow(panel, 'Салонный фильтр')).toHaveTextContent('Скоро менять')
    expect(await within(panel).findByText(/Осмотр, продувка/)).toBeInTheDocument()
  })

  it('другая работа без агрегата — без описания не сохранить', async () => {
    const { user, click } = setup()
    const panel = await openTicket(click, 1042)
    await click(within(panel).getByRole('button', { name: 'Другая работа' }))
    const form = within(panel).getByRole('form', { name: 'Другая работа: другая работа' })
    expect(within(form).queryByRole('radio')).toBeNull()
    const save = within(form).getByRole('button', { name: 'Сохранить' })
    expect(save).toBeDisabled()
    await user.type(within(form).getByLabelText('Что сделано'), 'Обновление карт навигации')
    await click(save)
    expect(await within(panel).findByRole('status')).toHaveTextContent('Работа сохранена: другая работа')
    expect(await within(panel).findByText(/Общие работы/)).toBeInTheDocument()
  })

  it('чужой и решённый тикет — фиксации нет', async () => {
    const { click } = setup()
    const foreign = await openTicket(click, 1050)
    await within(foreign).findByRole('region', { name: 'Статусы агрегатов' })
    expect(within(foreign).queryByRole('button', { name: /^Замена или работа/ })).toBeNull()
    expect(within(foreign).queryByRole('button', { name: 'Другая работа' })).toBeNull()
    const resolved = await openTicket(click, 1031)
    await within(resolved).findByRole('region', { name: 'Статусы агрегатов' })
    expect(within(resolved).queryByRole('button', { name: /^Замена или работа/ })).toBeNull()
  })
})
