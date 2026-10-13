// E2E админ-панели на стеке backend (глава 22, ADR 0026 п. 13–15). Тест чек-листа — «изменение регламента ТО
// отражается на статусах клиента без нового деплоя»: администратор пересматривает регламент на экране, статус
// «светофор» у клиента (API, как мобильное приложение) меняется на том же стеке без перезапуска. Сверка
// дашборда — с ручным расчётом контрольного набора (docs/ANALYTICS_CONTROL.md, март 2026). Пользователи,
// публикация и статья проверяются по API со стороны сотрудника и клиента.
import { expect, test, type Page } from '@playwright/test'
import { api, clientStatus, kpi, loadSeed, signIn, signInAdmin, staffLoginStatus, staffToken } from './support.ts'

const seed = loadSeed()

/** Показатель целиком — подпись и значение, без совпадения по подстроке («8» в «18»). */
async function expectKpi(page: Page, label: string, value: string) {
  await expect(kpi(page, label)).toHaveText(new RegExp(`^${label}${value}`))
}

test.describe.configure({ mode: 'serial' })

async function revise(page: Page, km: number) {
  await page.getByRole('button', { name: 'Изменить интервал: Салонный фильтр' }).click()
  const form = page.getByRole('form', { name: 'Интервал: Салонный фильтр' })
  await form.getByLabel('Интервал, км').fill(String(km))
  await form.getByLabel('Интервал, мес.').fill('')
  await form.getByRole('button', { name: 'Сохранить' }).click()
  await expect(page.getByRole('status').filter({ hasText: /^Сохранено: Салонный фильтр/ })).toBeVisible()
}

test('вход: инженеру — отказ, администратору — админ-панель', async ({ page }) => {
  await signIn(page, seed.engineers[1])
  await expect(page.getByRole('alert')).toHaveText('Админ-панель — только для администраторов. Инженер работает в кабинете инженера.')
  await signInAdmin(page, seed)
  await expect(page.getByText(`Администратор ${seed.admin.phone}`)).toBeVisible()
})

test('регламент ТО → статус клиента меняется без деплоя', async ({ page }) => {
  // 10 000 км при интервале 20 000 — износ 50 %.
  expect(await clientStatus(seed)).toBe('green')
  await signInAdmin(page, seed)
  await page.getByRole('link', { name: 'Регламенты ТО' }).click()
  await page.getByRole('button', { name: seed.client.model_label }).click()
  await expect(page.getByRole('rowheader', { name: 'Салонный фильтр' })).toBeVisible()

  await revise(page, 12_000) // 83 % — от «жёлтого с» 70 % до «красного выше» 100 %
  expect(await clientStatus(seed)).toBe('yellow')
  await revise(page, 9_000) // 111 %
  expect(await clientStatus(seed)).toBe('red')
  await revise(page, seed.client.interval_km)
  expect(await clientStatus(seed)).toBe('green')

  // Три пересмотра — три прежние версии в истории (у модели могли быть и более ранние).
  await page.getByLabel('Показать историю версий').check()
  await expect.poll(() => page.getByRole('row').filter({ hasText: 'в архиве' }).count()).toBeGreaterThanOrEqual(3)
})

test('дашборд совпадает с ручным расчётом контрольного набора (март 2026)', async ({ page }) => {
  await signInAdmin(page, seed)
  await page.getByRole('button', { name: 'Свой период' }).click()
  await page.getByLabel('С', { exact: true }).fill('2026-03-01')
  await page.getByLabel('По', { exact: true }).fill('2026-03-31')
  // A1 — время реакции и решения без фильтров.
  await expectKpi(page, 'Создано', '8')
  await expectKpi(page, 'Решено', '6')
  await expectKpi(page, 'Решено с просрочкой SLA', '2')
  await expectKpi(page, 'Первый ответ, в среднем', '0,93 ч')
  await expectKpi(page, 'Закрытие, в среднем', '11 ч')
  await expectKpi(page, 'Закрытие, медиана', '8 ч')
  // P3/P1 — модели по числу тикетов: Альфа 4 / 2, Бета 2 / 1, Гамма 2 / 2.
  const rows = page.getByRole('region', { name: 'Модели по числу тикетов' }).getByRole('row')
  await expect(rows.nth(1)).toContainText(/Контроль Альфа\s*4\s*2/)
  await expect(rows.nth(2)).toContainText(/Контроль Бета\s*2\s*1/)
  await expect(rows.nth(3)).toContainText(/Контроль Гамма\s*2\s*2/)
  // C1 — конверсия: тикеты 2 / 8 = 25 %, напоминания 3 / 5 = 60 %.
  await expect(page.getByText('Обращение → работа ТО').locator('..')).toContainText('25 %')
  await expect(page.getByText('Напоминание о ТО → работа ТО за 30 дней').locator('..')).toContainText('60 %')
  // A3 — модель Бета: 2 создано, 1 решён с просрочкой, среднее 9 ч.
  await page.getByLabel('Модель').selectOption({ label: 'Контроль Бета' })
  await expectKpi(page, 'Создано', '2')
  await expectKpi(page, 'Решено', '1')
  await expectKpi(page, 'Закрытие, в среднем', '9 ч')
})

test('пользователи: новый инженер входит; переназначение тикета; сброс пароля и блокировка', async ({ page }) => {
  const [first, second] = seed.engineers
  await signInAdmin(page, seed)
  await page.getByRole('link', { name: 'Пользователи' }).click()

  // Новый инженер: пароль показан один раз — с ним сотрудник входит.
  const phone = `+37529996${String(Date.now()).slice(-4)}`
  await page.getByLabel('Телефон', { exact: true }).fill(phone)
  await page.getByRole('button', { name: 'Сгенерировать' }).click()
  await page.getByRole('button', { name: 'Создать сотрудника' }).click()
  const created = (await page.getByLabel('Пароль', { exact: true }).and(page.locator('code')).textContent())!
  expect(await staffLoginStatus(phone, created)).toBe(200)

  // Карточка первого инженера: его тикет — второму инженеру.
  await page.getByLabel('Поиск по телефону').fill(first.phone)
  await page.getByRole('link', { name: first.phone }).click()
  const tickets = page.getByRole('region', { name: 'Нерешённые тикеты сотрудника' })
  await tickets.getByLabel(`Кому: тикет #${seed.ticket_id}`).selectOption({ label: second.phone })
  await tickets.getByRole('button', { name: 'Переназначить' }).click()
  await expect(tickets.getByText('Нерешённых тикетов нет')).toBeVisible()
  const admin = await staffToken(seed.admin)
  const ticket = await api<{ assigned_engineer_id: number }>('GET', `/tickets/${seed.ticket_id}`, admin)
  expect(ticket.assigned_engineer_id).toBe(second.id)

  // Сброс пароля: прежний не подходит, новый — да.
  await page.getByRole('button', { name: 'Сгенерировать' }).click()
  await page.getByRole('button', { name: 'Сбросить пароль' }).click()
  await page.getByRole('dialog').getByRole('button', { name: 'Сбросить пароль' }).click()
  const reset = (await page.getByLabel('Пароль', { exact: true }).and(page.locator('code')).textContent())!
  expect(await staffLoginStatus(first.phone, first.password)).toBe(401)
  expect(await staffLoginStatus(first.phone, reset)).toBe(200)

  // Блокировка: вход запрещён.
  await page.getByRole('button', { name: 'Заблокировать' }).click()
  await page.getByRole('dialog').getByRole('button', { name: 'Заблокировать' }).click()
  await expect(page.getByText('Заблокирован', { exact: true })).toBeVisible()
  expect(await staffLoginStatus(first.phone, reset)).toBe(401)
})

test('публикация: число получателей в подтверждении = получатели в ленте', async ({ page }) => {
  await signInAdmin(page, seed)
  await page.getByRole('link', { name: 'Публикации' }).click()
  const subject = `E2E ${Date.now()}`
  await page.getByLabel('Аудитория').selectOption({ label: seed.client.model_label })
  await page.getByLabel('Тема', { exact: true }).fill(subject)
  await page.getByLabel('Текст уведомления').fill('Сервис работает в субботу.')
  await page.getByRole('button', { name: 'Опубликовать…' }).click()
  const dialog = page.getByRole('dialog', { name: 'Опубликовать уведомление?' })
  const recipients = Number((await dialog.textContent())!.match(/Получат (\d+)/)![1])
  expect(recipients).toBeGreaterThanOrEqual(1) // клиент сценария — владелец модели
  await dialog.getByRole('button', { name: 'Опубликовать' }).click()
  await expect(page.getByText(/поставлено в очередь/)).toBeVisible()
  const item = page.getByRole('region', { name: 'Опубликовано' }).getByRole('listitem').filter({ hasText: subject })
  await expect(item).toContainText(`Получателей ${recipients}`)
  // Клиент видит новость в своей ленте.
  const feed = await api<{ items: { message: string }[] }>('GET', '/notifications', seed.client.access_token)
  expect(feed.items.some((n) => n.message.startsWith(subject))).toBe(true)
})

test('статья: «Сохранить и опубликовать» — клиент видит её в базе знаний', async ({ page }) => {
  await signInAdmin(page, seed)
  await page.getByRole('link', { name: 'База знаний' }).click()
  await page.getByRole('button', { name: 'Новая статья' }).click()
  const title = `E2E: подключение Bluetooth ${Date.now()}`
  await page.getByLabel('Заголовок').fill(title)
  await page.getByLabel('Текст статьи').fill('Откройте «Настройки» → Bluetooth и выберите телефон.')
  await page.getByRole('button', { name: 'Сохранить и опубликовать' }).click()
  await expect(page.getByText(/^Статья опубликована в базе знаний/)).toBeVisible()
  const found = await api<{ items: { title: string }[] }>(
    'GET',
    `/knowledge-articles?search=${encodeURIComponent('Bluetooth')}`,
    seed.client.access_token,
  )
  expect(found.items.map((a) => a.title)).toContain(title)
})

test('статья «Устранение неполадок»: категория ошибки обязательна, черновик открывает дерево решений', async ({ page }) => {
  await signInAdmin(page, seed)
  await page.getByRole('link', { name: 'База знаний' }).click()
  await page.getByRole('button', { name: 'Новая статья' }).click()
  await page.getByLabel('Тип').selectOption({ label: 'Устранение неполадок' })
  await page.getByLabel('Заголовок').fill(`E2E: пропал звук ${Date.now()}`)
  await page.getByLabel('Вступление').fill('Нет звука в музыке и навигации.')
  await page.getByRole('button', { name: 'Сохранить черновик' }).click()
  await expect(page.getByText('Выберите категорию ошибки', { exact: true })).toBeVisible()
  await page.getByLabel('Категория ошибки').selectOption({ label: 'Аудио' })
  await page.getByRole('button', { name: 'Сохранить черновик' }).click()
  await expect(page.getByRole('tab', { name: /^Дерево решений/ })).toBeVisible()
  await expect(page.getByLabel('Категория ошибки')).toHaveValue('audio')
})
