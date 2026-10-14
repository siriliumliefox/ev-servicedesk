// Межролевые P0 главы 23 (ADR 0027 п. 8, 15) на одном стеке: кабинет инженера и админ-панель — через интерфейс,
// клиент — по API, как мобильное приложение (его интерфейс проверяют Flutter-тесты тех же сценариев, матрица —
// docs/specs/e2e_matrix.yaml). E2E-08 — замена агрегата, E2E-11 — прошивка по модели, E2E-15 — вход по ролям,
// E2E-16 — главный сценарий «клиент → инженер → клиент → администратор».
import { expect, test, type Page } from '@playwright/test'
import { ADMIN_URL, ENGINEER_URL } from './apps.ts'
import {
  ADMIN_HEADING,
  ENGINEER_HEADING,
  api,
  carFor,
  clientStatus,
  feed,
  loadSeed,
  runJob,
  signIn,
  staffToken,
  submitLogin,
  todayInMinsk,
} from './support.ts'

const seed = loadSeed()
const x = seed.client_x
const y = seed.client_y

interface Ticket {
  id: number
  status: string
}

async function clientTicket(vehicleId: number, description: string): Promise<Ticket> {
  const body = { vehicle_id: vehicleId, category: 'maintenance', description }
  return api<Ticket>('POST', '/tickets', x.access_token, body, 201)
}

/** Инженер открывает тикет с доски и берёт его в работу. */
async function takeTicket(page: Page, id: number) {
  await page.getByRole('button', { name: new RegExp(`^Тикет #${id},`) }).click()
  const panel = page.getByRole('complementary', { name: `Карточка тикета #${id}` })
  await panel.getByRole('button', { name: 'Взять в работу' }).click()
  await expect(panel.getByRole('button', { name: 'Решено' })).toBeVisible()
  return panel
}

/** Замена агрегата из карточки авто — пробег по умолчанию текущий, дата — сегодня. */
async function replaceFromPanel(panel: ReturnType<Page['getByRole']>, name: string) {
  await panel.getByRole('button', { name: `Замена или работа: ${name}` }).click()
  const form = panel.getByRole('form', { name: `Замена или работа: ${name}` })
  await expect(form.getByRole('radio', { name: /Замена/ })).toBeChecked()
  await form.getByRole('button', { name: 'Сохранить' }).click()
  await expect(panel.getByRole('status').filter({ hasText: `Замена сохранена: ${name}` })).toBeVisible()
  const row = panel.getByRole('region', { name: 'Статусы агрегатов' }).getByRole('listitem').filter({ hasText: name })
  await expect(row).toContainText('Заменено')
}

test('вход по ролям: кабинет инженера — только инженер, админ-панель — только администратор', async ({ page }) => {
  await submitLogin(page, ENGINEER_URL, seed.admin)
  await expect(page.getByRole('alert')).toHaveText('Кабинет инженера — только для инженеров. Администратор работает в админ-панели.')
  await submitLogin(page, ADMIN_URL, seed.engineer)
  await expect(page.getByRole('alert')).toHaveText('Админ-панель — только для администраторов. Инженер работает в кабинете инженера.')
  // У клиента нет пароля — вход в приложение сотрудника отклоняет backend. Одна попытка на браузер: неудачные
  // входы по номеру ограничены (5 за 15 минут).
  await submitLogin(page, ENGINEER_URL, { phone: x.phone, password: 'у-клиента-нет-пароля' })
  await expect(page.getByRole('alert')).toHaveText('Неверный номер телефона или пароль.')
  // Токен клиента не открывает операции сотрудников (RBAC deny by default).
  await api('GET', '/users', x.access_token, undefined, 403)
  await api('GET', '/analytics/ticket-resolution', x.access_token, undefined, 403)
  // Свои роли входят.
  await signIn(page, ENGINEER_URL, seed.engineer, ENGINEER_HEADING)
  await signIn(page, ADMIN_URL, seed.admin, ADMIN_HEADING)
})

test('замена агрегата из карточки тикета → у клиента «Заменено» и запись в истории ТО', async ({ page }) => {
  const car = carFor(seed)
  const code = car.aggregates.replace
  const name = car.aggregate_names.replace
  expect(await clientStatus(x, car.id, code)).toBe('red')
  const ticket = await clientTicket(car.id, `E2E-08 (${test.info().project.name}): пора менять ${name.toLowerCase()}.`)

  await signIn(page, ENGINEER_URL, seed.engineer, ENGINEER_HEADING)
  const panel = await takeTicket(page, ticket.id)
  await replaceFromPanel(panel, name)

  // Клиент видит результат сразу — без перезапуска и деплоя.
  expect(await clientStatus(x, car.id, code)).toBe('green')
  const history = await api<{ items: { kind: string; mileage_at_service: number }[] }>(
    'GET',
    `/vehicles/${car.id}/maintenance-records?aggregate_type_code=${code}`,
    x.access_token,
  )
  expect(history.items[0]).toMatchObject({ kind: 'replacement', mileage_at_service: 16_000 })
})

test('прошивка на модель X → уведомление и push владельцу X, владельцу Y — нет', async ({ page }) => {
  const version = `E2E-${test.info().project.name}-${Date.now() % 1_000_000}`
  await signIn(page, ADMIN_URL, seed.admin, ADMIN_HEADING)
  await page.getByRole('link', { name: 'Публикации' }).click()
  await page.getByRole('radio', { name: 'Прошивка' }).check()
  await page.getByLabel('Модель', { exact: true }).selectOption({ label: seed.model_label })
  await page.getByLabel('Версия').fill(version)
  await page.getByRole('button', { name: 'Опубликовать…' }).click()
  const dialog = page.getByRole('dialog', { name: 'Опубликовать релиз прошивки?' })
  await dialog.getByRole('button', { name: 'Опубликовать' }).click()
  await expect(page.getByText(`Релиз опубликован: ${seed.model_label}, ${version}.`)).toBeVisible()

  // Лента: владелец модели X получил уведомление о прошивке, владелец другой модели — нет.
  await expect
    .poll(async () => (await feed(x)).some((n) => n.type === 'firmware' && n.message.includes(version)))
    .toBe(true)
  expect((await feed(y)).some((n) => n.message.includes(version))).toBe(false)

  // Push: worker уведомлений отправил его через транспорт стека (фейковый FCM, ADR 0021 п. 6) — доставка
  // в статистике публикации; на iPhone — глава 27 (ADR 0027 п. 17).
  const admin = await staffToken(seed.admin)
  type Published = { items: { message: string; stats: { recipients: number; delivered: number } }[] }
  const delivered = async () => {
    const list = await api<Published>('GET', '/notifications/published?type=firmware&page_size=50', admin)
    return list.items.find((n) => n.message.includes(version))?.stats.delivered ?? 0
  }
  await expect.poll(delivered, { timeout: 30_000 }).toBeGreaterThanOrEqual(1)
  await page.reload()
  await expect(page.getByRole('region', { name: 'Опубликовано' }).getByRole('listitem').filter({ hasText: version })).toBeVisible()
})

test('главный сценарий: тикет клиента → ответ и замена инженером → у клиента ответ и «Заменено» → дашборд +1', async ({
  browser,
}) => {
  const car = carFor(seed)
  const code = car.aggregates.golden
  const name = car.aggregate_names.golden
  const today = todayInMinsk()
  const admin = await staffToken(seed.admin)
  type Resolution = { tickets_resolved: number }
  const resolved = async () => {
    runJob('python', '-m', 'app.workers.analytics', '--once')
    const period = `date_from=${today}&date_to=${today}`
    return (await api<Resolution>('GET', `/analytics/ticket-resolution?${period}`, admin)).tickets_resolved
  }
  const before = await resolved()

  // 1. Клиент создаёт тикет по авто, у которого агрегат требует замены.
  expect(await clientStatus(x, car.id, code)).toBe('red')
  const ticket = await clientTicket(car.id, `E2E-16 (${test.info().project.name}): ${name.toLowerCase()} — нужна замена.`)

  // 2. Инженер: в работу → ответ клиенту → замена агрегата → «Решено».
  const engineer = await (await browser.newContext()).newPage()
  await signIn(engineer, ENGINEER_URL, seed.engineer, ENGINEER_HEADING)
  const panel = await takeTicket(engineer, ticket.id)
  const reply = `Заменили: ${name}. Счётчик выработки сброшен.`
  await panel.getByLabel('Ответ клиенту').fill(reply)
  await panel.getByRole('button', { name: 'Отправить' }).click()
  await expect(panel.getByText(reply)).toBeVisible()
  await replaceFromPanel(panel, name)
  await panel.getByRole('button', { name: 'Решено' }).click()
  await expect(panel.getByText('Тикет решён — чтобы ответить, верните его в работу')).toBeVisible()

  // 3. Клиент: ответ инженера в чате, тикет решён, агрегат «Заменено».
  const messages = await api<{ items: { body: string }[] }>('GET', `/tickets/${ticket.id}/messages`, x.access_token)
  expect(messages.items.map((m) => m.body)).toContain(reply)
  expect((await api<Ticket>('GET', `/tickets/${ticket.id}`, x.access_token)).status).toBe('resolved')
  expect(await clientStatus(x, car.id, code)).toBe('green')

  // 4. Администратор: витрина обновлена — на дашборде за сегодня решено на один тикет больше.
  const after = await resolved()
  expect(after).toBe(before + 1)
  const adminPage = await (await browser.newContext()).newPage()
  await signIn(adminPage, ADMIN_URL, seed.admin, ADMIN_HEADING)
  await adminPage.getByRole('button', { name: 'Свой период' }).click()
  await adminPage.getByLabel('С', { exact: true }).fill(today)
  await adminPage.getByLabel('По', { exact: true }).fill(today)
  const kpi = adminPage.locator('div', { has: adminPage.getByText('Решено', { exact: true }) }).last()
  await expect(kpi).toHaveText(new RegExp(`^Решено${after}`))
})
