// Проверки главы 21 (MASTER_CHECKLIST, ADR 0025 п. 14) на стеке из образа-кандидата:
// 1) E2E: тикет в работу (перетаскиванием) → ответ из базы знаний → закрытие → у клиента в реальном времени;
// 2) конкурентный доступ: два инженера берут один тикет — один получает его, второй — уведомление о конфликте.
import { expect, test } from '@playwright/test'
import { ClientSide, card, column, dragWithKeyboard, dragWithMouse, loadSeed, signIn, ticketsFor } from './support.ts'

const seed = loadSeed()

test('E2E: в работу → быстрый ответ → «Решено»; клиент получает всё вживую', async ({ page }) => {
  const client = new ClientSide(seed)
  const id = ticketsFor(seed).flow
  await client.watch(id)

  await signIn(page, seed.engineers[0])
  const queued = card(column(page, 'Новые'), id)
  await expect(queued).toBeVisible()

  // Взять в работу перетаскиванием мышью: «Новые» → «В работе».
  let since = Date.now()
  await dragWithMouse(page, queued, column(page, 'В работе'))
  await expect(card(column(page, 'В работе'), id)).toBeVisible()
  await client.received((e) => e.type === 'ticket.updated' && e.data.status === 'in_progress', since)

  // Быстрый ответ из базы знаний — сразу клиенту.
  await card(page, id).click()
  const panel = page.getByRole('complementary', { name: `Карточка тикета #${id}` })
  await expect(panel.getByText('Обновляется вживую')).toBeVisible()
  await panel.getByRole('button', { name: 'Быстрые ответы' }).click()
  await panel.getByLabel('Поиск в базе знаний').fill('пробки')
  since = Date.now()
  await panel.getByRole('button', { name: `Отправить клиенту: ${seed.quick_reply_title}` }).click()
  const reply = await client.received(
    (e) => e.type === 'message.created' && (e.data.body ?? '').startsWith(seed.quick_reply_title),
    since,
  )
  await expect(panel.getByText(seed.quick_reply_title).first()).toBeVisible()

  // Ответ клиента приходит инженеру без перезагрузки.
  await client.api('POST', `/tickets/${id}/messages`, { body: 'Пробки появились, спасибо!' })
  await expect(panel.getByText('Пробки появились, спасибо!')).toBeVisible({ timeout: 2000 })

  // Закрытие — с клавиатуры: «В работе» → «Решено» (через «Ожидает вендора»), с подтверждением.
  await dragWithKeyboard(page, id, 2)
  const dialog = page.getByRole('dialog', { name: `Решить тикет #${id}?` })
  await expect(dialog).toBeVisible()
  since = Date.now()
  await dialog.getByRole('button', { name: 'Решено' }).click()
  await client.received((e) => e.type === 'ticket.updated' && e.data.status === 'resolved', since)
  await expect(card(column(page, 'Решено'), id)).toBeVisible()
  await expect(panel.getByText('Тикет решён — чтобы ответить, верните его в работу')).toBeVisible()

  const ticket = await client.api<{ status: string }>('GET', `/tickets/${id}`)
  expect(ticket.status).toBe('resolved')
  expect(reply.data.id).toBeGreaterThan(0)
  client.close()
})

test('конкурентный доступ: два инженера берут один тикет', async ({ browser }) => {
  const client = new ClientSide(seed)
  const tickets = ticketsFor(seed)
  const first = { id: tickets.race_button }
  const second = { id: tickets.race_drag }

  const a = await (await browser.newContext()).newPage()
  const b = await (await browser.newContext()).newPage()
  await signIn(a, seed.engineers[0])
  await signIn(b, seed.engineers[1])

  // 1) Оба открыли тикет из очереди и одновременно нажали «Взять в работу».
  for (const page of [a, b]) {
    await card(column(page, 'Новые'), first.id).click()
    await expect(page.getByRole('button', { name: 'Взять в работу' })).toBeVisible()
  }
  await Promise.all([a, b].map((page) => page.getByRole('button', { name: 'Взять в работу' }).click()))
  const outcome = async (page: typeof a) => {
    const panel = page.getByRole('complementary', { name: `Карточка тикета #${first.id}` })
    const lost = panel.getByText('Тикет уже взял в работу другой инженер.')
    const won = panel.getByRole('button', { name: 'Решено' })
    await expect(lost.or(won)).toBeVisible()
    return (await won.isVisible()) ? 'won' : 'lost'
  }
  const results = [await outcome(a), await outcome(b)]
  expect(results.sort()).toEqual(['lost', 'won'])
  const loser = results[0] === 'lost' ? a : b
  // Карточка проигравшего закрывается, тикет пропадает с его доски.
  await expect(loser.getByRole('complementary', { name: `Карточка тикета #${first.id}` })).toBeHidden({ timeout: 8000 })
  await expect(card(loser, first.id)).toHaveCount(0, { timeout: 20_000 })

  // 2) A взял тикет, B ещё видит его в очереди (опрос доски B заморожен — как между опросами) и
  //    перетаскивает — 409 TICKET_ALREADY_CLAIMED, уведомление, тикет пропадает с доски B.
  await expect(card(column(b, 'Новые'), second.id)).toBeVisible({ timeout: 20_000 })
  await expect(card(column(a, 'Новые'), second.id)).toBeVisible({ timeout: 20_000 })
  const boardPoll = /\/v1\/tickets\?/
  await b.route(boardPoll, (route) => route.abort())
  await dragWithMouse(a, card(column(a, 'Новые'), second.id), column(a, 'В работе'))
  await expect(card(column(a, 'В работе'), second.id)).toBeVisible()
  await dragWithMouse(b, card(column(b, 'Новые'), second.id), column(b, 'В работе'))
  await expect(b.getByText(`Тикет #${second.id} уже взял в работу другой инженер.`)).toBeVisible()
  await expect(card(b, second.id)).toHaveCount(0)
  await b.unroute(boardPoll)

  const ticket = await client.api<{ assigned_engineer_id: number }>('GET', `/tickets/${second.id}`)
  expect(ticket.assigned_engineer_id).toBeGreaterThan(0)
})
