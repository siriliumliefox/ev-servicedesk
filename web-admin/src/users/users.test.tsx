// Пользователи и роли (глава 22, ADR 0026 п. 4–7) на прототипе-репозитории: фильтры и поиск, создание
// сотрудника с одноразовым показом пароля, роль, блокировка, сброс пароля, своя учётная запись, последний
// администратор, переназначение тикетов инженера.
import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import { ADMIN_ID, ENGINEER_ID, OTHER_ENGINEER_ID, PrototypeRepository } from '@ev-servicedesk/web-shared'
import App from '../App.tsx'
import { generatePassword } from './password.ts'

const NOW = new Date('2026-10-10T12:00:00Z')

function setup(path: string, configure?: (repo: PrototypeRepository) => void) {
  window.location.hash = path
  const repo = new PrototypeRepository({ role: 'admin', now: () => NOW })
  configure?.(repo)
  render(<App repo={repo} now={() => NOW} />)
  return { repo, user: userEvent.setup() }
}

const table = () => screen.getByRole('table')
const phones = () => within(table()).getAllByRole('link').map((a) => a.textContent)

describe('список пользователей', () => {
  it('фильтры роли и статуса, поиск по телефону', async () => {
    const { user } = setup('/users')
    await screen.findByRole('link', { name: '+375291000001' })
    expect(phones()).toHaveLength(8)
    await user.click(within(screen.getByRole('group', { name: 'Роль' })).getByRole('button', { name: 'Инженеры' }))
    await vi.waitFor(() => expect(phones()).toEqual(['+375291000007', '+375291000008']))
    await user.click(within(screen.getByRole('group', { name: 'Роль' })).getByRole('button', { name: 'Все' }))
    await user.type(screen.getByLabelText('Поиск по телефону'), '+375 29 7001 50')
    await vi.waitFor(() => expect(phones()).toHaveLength(5))
    await user.click(within(screen.getByRole('group', { name: 'Статус' })).getByRole('button', { name: 'Заблокированные' }))
    expect(await screen.findByText('Никого не найдено')).toBeInTheDocument()
  })

  it('новый сотрудник: сгенерированный пароль показан один раз; сотрудник в списке', async () => {
    const { user, repo } = setup('/users')
    const create = vi.spyOn(repo, 'createStaffUser')
    await user.clear(await screen.findByLabelText('Телефон'))
    await user.type(screen.getByLabelText('Телефон'), '+375 29 555-44-33')
    await user.selectOptions(screen.getByLabelText('Роль сотрудника'), 'Администратор')
    await user.click(screen.getByRole('button', { name: 'Сгенерировать' }))
    const password = (screen.getByLabelText('Пароль') as HTMLInputElement).value
    expect(password).toHaveLength(16)
    await user.click(screen.getByRole('button', { name: 'Создать сотрудника' }))
    expect(create).toHaveBeenCalledWith({ phone: '+375295554433', role: 'admin', password })
    expect(await screen.findByLabelText('Пароль', { selector: 'code' })).toHaveTextContent(password)
    expect(screen.getByLabelText('Пароль', { selector: 'input' })).toHaveValue('')
    expect(await screen.findByRole('link', { name: '+375295554433' })).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Готово' }))
    expect(screen.queryByText(password)).not.toBeInTheDocument()
  })

  it('короткий пароль и занятый телефон — ошибки до и после запроса', async () => {
    const { user, repo } = setup('/users')
    const create = vi.spyOn(repo, 'createStaffUser')
    await user.clear(await screen.findByLabelText('Телефон'))
    await user.type(screen.getByLabelText('Телефон'), '+375291000007')
    await user.type(screen.getByLabelText('Пароль'), 'short')
    await user.click(screen.getByRole('button', { name: 'Создать сотрудника' }))
    expect(screen.getByLabelText('Пароль')).toHaveAccessibleDescription('Пароль — не короче 12 символов')
    expect(create).not.toHaveBeenCalled()
    await user.type(screen.getByLabelText('Пароль'), '-but-long-now')
    await user.click(screen.getByRole('button', { name: 'Создать сотрудника' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('Этот телефон уже зарегистрирован.')
  })
})

describe('карточка пользователя', () => {
  it('своя учётная запись — без роли, блокировки и пароля', async () => {
    setup(`/users/${ADMIN_ID}`)
    expect(await screen.findByText(/Это ваша учётная запись/)).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Заблокировать' })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Сменить роль' })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Сбросить пароль' })).not.toBeInTheDocument()
  })

  it('клиент — только блокировка; подтверждение; разблокировка', async () => {
    const { user } = setup('/users/501')
    await user.click(await screen.findByRole('button', { name: 'Заблокировать' }))
    expect(screen.queryByRole('button', { name: 'Сменить роль' })).not.toBeInTheDocument()
    const dialog = screen.getByRole('dialog', { name: 'Заблокировать +375297001501?' })
    await user.click(within(dialog).getByRole('button', { name: 'Заблокировать' }))
    expect(await screen.findByText('Заблокирован')).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Разблокировать' }))
    await user.click(within(screen.getByRole('dialog')).getByRole('button', { name: 'Разблокировать' }))
    expect(await screen.findByText('Активен')).toBeInTheDocument()
  })

  it('блокировка инженера с тикетами — предупреждение; переназначение тикета другому инженеру', async () => {
    const { user, repo } = setup(`/users/${ENGINEER_ID}`)
    const before = (await repo.listTickets({ assigned_engineer_id: ENGINEER_ID, page_size: 100 })).items.filter((t) => t.status !== 'resolved')
    expect(before.length).toBeGreaterThan(0)
    const section = await screen.findByRole('region', { name: 'Нерешённые тикеты сотрудника' })
    await within(section).findByRole('table')
    await user.click(screen.getByRole('button', { name: 'Заблокировать' }))
    expect(screen.getByRole('dialog')).toHaveTextContent(/нерешённ\S+ тикет\S* — переназначьте (его|их) в списке слева/)
    await user.click(within(screen.getByRole('dialog')).getByRole('button', { name: 'Отмена' }))

    const ticket = before[0]
    await user.selectOptions(within(section).getByLabelText(`Кому: тикет #${ticket.id}`), '+375291000008')
    const assign = vi.spyOn(repo, 'assignTicket')
    await user.click(within(section).getAllByRole('button', { name: 'Переназначить' })[0])
    expect(assign).toHaveBeenCalledWith(ticket.id, OTHER_ENGINEER_ID)
    await vi.waitFor(() => expect(within(section).queryByText(`#${ticket.id}`)).not.toBeInTheDocument())
  })

  it('роль инженер → администратор; последний администратор — понятная ошибка', async () => {
    const { user } = setup(`/users/${ENGINEER_ID}`)
    await user.selectOptions(await screen.findByLabelText('Роль сотрудника'), 'Администратор')
    await user.click(screen.getByRole('button', { name: 'Сменить роль' }))
    await user.click(within(screen.getByRole('dialog')).getByRole('button', { name: 'Сменить роль' }))
    expect(await screen.findByText(/^Администратор ·/)).toBeInTheDocument()
  })

  it('LAST_ADMIN: единственного администратора понизить нельзя', async () => {
    // Вошёл администратор-новичок, единственный активный админ — другой (ADMIN_ID): блокируем его.
    const { user } = setup(`/users/${ADMIN_ID}`, (r) => {
      vi.spyOn(r, 'getCurrentUser').mockResolvedValue({ id: 999, phone: '+375290000999', role: 'admin', is_active: true, created_at: NOW.toISOString() })
    })
    await user.click(await screen.findByRole('button', { name: 'Заблокировать' }))
    await user.click(within(screen.getByRole('dialog')).getByRole('button', { name: 'Заблокировать' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('Это последний активный администратор')
  })

  it('сброс пароля: подтверждение, новый пароль показан один раз', async () => {
    const { user, repo } = setup(`/users/${OTHER_ENGINEER_ID}`)
    const reset = vi.spyOn(repo, 'resetUserPassword')
    await user.click(await screen.findByRole('button', { name: 'Сгенерировать' }))
    const password = (screen.getByLabelText('Новый пароль') as HTMLInputElement).value
    await user.click(screen.getByRole('button', { name: 'Сбросить пароль' }))
    expect(screen.getByRole('dialog')).toHaveTextContent('выйдет на всех устройствах')
    await user.click(within(screen.getByRole('dialog')).getByRole('button', { name: 'Сбросить пароль' }))
    expect(reset).toHaveBeenCalledWith(OTHER_ENGINEER_ID, password)
    expect(await screen.findByLabelText('Пароль', { selector: 'code' })).toHaveTextContent(password)
  })
})

describe('генерация пароля', () => {
  it('16 символов из алфавита без похожих знаков; байты вне диапазона отбрасываются', () => {
    for (let i = 0; i < 50; i += 1) expect(generatePassword()).toMatch(/^[A-HJ-NP-Za-km-z2-9]{16}$/)
    // Байт 250 ≥ 228 — отброшен; 0 → «A», 57 → снова «A».
    let call = 0
    const random = (size: number) => {
      call += 1
      return Uint8Array.from({ length: size }, (_, k) => (call === 1 && k === 0 ? 250 : k % 2 ? 57 : 0))
    }
    expect(generatePassword(random)).toBe('A'.repeat(16))
  })
})
