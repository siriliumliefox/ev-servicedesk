// Прототип админ-панели (Глава 8, ADR 0012): конструктор регламентов ТО, конструктор статей и дерево
// решений, лента публикаций, дашборд; клики — для таблицы в docs/design/WEB_PROTOTYPE.md.
import { act, render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import { PrototypeRepository } from '@ev-servicedesk/web-shared'
import App from './App.tsx'

const NOW = new Date('2026-10-10T12:00:00Z')
const now = () => NOW

function setup(path = '/', configure?: (repo: PrototypeRepository) => void) {
  window.location.hash = path
  const repo = new PrototypeRepository({ role: 'admin', now })
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

const kpi = (label: string) => screen.getByText(label).parentElement!

/** Переход по адресу мимо кнопок приложения — как «Назад»/«Вперёд» браузера или ручной ввод URL. */
async function goTo(path: string) {
  await act(async () => {
    window.location.hash = path
    window.dispatchEvent(new HashChangeEvent('hashchange'))
  })
}

describe('навигация и тема', () => {
  it('светлая тема по умолчанию; разделы — ссылки с aria-current', async () => {
    const { click } = setup()
    await screen.findByText('Тикеты')
    expect(document.documentElement.dataset.theme).toBe('light')
    const nav = screen.getByRole('navigation', { name: 'Разделы админ-панели' })
    expect(within(nav).getByRole('link', { name: 'Дашборд' })).toHaveAttribute('aria-current', 'page')
    await click(within(nav).getByRole('link', { name: 'Регламенты ТО' }))
    expect(await screen.findByRole('heading', { name: 'Админ-панель · Регламенты ТО' })).toBeInTheDocument()
  })

  it('пункты меню — с пояснением (U-08); имя ссылки — название раздела, пояснение — описание', async () => {
    setup('/publications')
    await screen.findByLabelText('Тема')
    const nav = screen.getByRole('navigation', { name: 'Разделы админ-панели' })
    expect(within(nav).getByRole('link', { name: 'Дашборд' })).toHaveAccessibleDescription('показатели поддержки')
    expect(within(nav).getByRole('link', { name: 'Регламенты ТО' })).toHaveAccessibleDescription('интервалы замены и пороги')
    expect(within(nav).getByRole('link', { name: 'База знаний' })).toHaveAccessibleDescription('статьи и деревья неполадок')
    const current = within(nav).getByRole('link', { name: 'Публикации' })
    expect(current).toHaveAccessibleDescription('рассылки: новости, акции, прошивки')
    expect(current).toHaveAttribute('aria-current', 'page')
  })

  it('нет сети — ошибка с «Повторить»', async () => {
    setup('/', (repo) => repo.setOffline(true))
    expect(await screen.findByRole('alert')).toHaveTextContent('Нет соединения')
  })
})

describe('дашборд', () => {
  it('показатели тикетов, проблемные модели, конверсия; период меняет значения', async () => {
    const { click } = setup()
    await screen.findByText('Тикеты')
    expect(kpi('Создано')).toHaveTextContent('129')
    expect(kpi('Закрытие, в среднем')).toHaveTextContent('18,6 ч')
    const models = screen.getByRole('table')
    expect(within(models).getAllByRole('row')[1]).toHaveTextContent('Li Auto L7')
    expect(screen.getByText('Обращение → запись на ТО').parentElement).toHaveTextContent('18 %')
    await click(screen.getByRole('button', { name: '7 дней' }))
    await screen.findByRole('button', { name: '7 дней', pressed: true })
    expect(await screen.findByText('Создано')).toBeInTheDocument()
    await expect.poll(() => kpi('Создано').textContent).toBe('Создано30')
  })

  it('пустая система — без моделей и с прочерками', async () => {
    setup('/', (repo) => repo.setScenario('empty'))
    expect(await screen.findByText('Обращений за период нет')).toBeInTheDocument()
    expect(kpi('Закрытие, в среднем')).toHaveTextContent('—')
  })
})

describe('конструктор регламентов ТО', () => {
  it('изменить интервал — 2 клика; прошлая версия в истории', async () => {
    const { user, click, clicks } = setup('/regulations')
    await click(await screen.findByRole('button', { name: 'Изменить интервал: Масло двигателя' }))
    const form = screen.getByRole('form', { name: 'Интервал: Масло двигателя' })
    await user.clear(within(form).getByLabelText('Интервал, км'))
    await user.type(within(form).getByLabelText('Интервал, км'), '12000')
    await click(within(form).getByRole('button', { name: 'Сохранить' }))
    const row = (await screen.findByRole('rowheader', { name: 'Масло двигателя' })).closest('tr')!
    expect(row).toHaveTextContent('12 000')
    expect(clicks()).toBe(2)
    await click(screen.getByLabelText('Показать историю версий'))
    expect(await screen.findByText(/в архиве/)).toBeInTheDocument()
  })

  it.each([
    ['обычный пробел', '12 000'],
    ['неразрывный пробел', '12\u00A0000'],
    ['узкий неразрывный пробел', '12\u202F000'],
  ])('разряды через %s: «12 000» сохраняется числом 12000 (U-04)', async (_, value) => {
    const { user, click, repo } = setup('/regulations')
    await click(await screen.findByRole('button', { name: 'Изменить интервал: Масло двигателя' }))
    const form = screen.getByRole('form', { name: 'Интервал: Масло двигателя' })
    await user.clear(within(form).getByLabelText('Интервал, км'))
    await user.type(within(form).getByLabelText('Интервал, км'), value)
    await click(within(form).getByRole('button', { name: 'Сохранить' }))
    expect((await screen.findByRole('rowheader', { name: 'Масло двигателя' })).closest('tr')).toHaveTextContent('12 000')
    expect(screen.queryByText(/целое число/)).not.toBeInTheDocument()
    const regs = await repo.listMaintenanceRegulations({ vehicle_model_id: 1 })
    expect(regs.find((r) => r.aggregate_type_code === 'engine_oil' && !r.is_archived)?.interval_km).toBe(12000)
  })

  it('разряды через пробел — и в «Интервал, мес.» (U-04)', async () => {
    const { user, click, repo } = setup('/regulations')
    await click(await screen.findByRole('button', { name: 'Изменить интервал: Масло двигателя' }))
    const form = screen.getByRole('form', { name: 'Интервал: Масло двигателя' })
    await user.clear(within(form).getByLabelText('Интервал, мес.'))
    await user.type(within(form).getByLabelText('Интервал, мес.'), '1\u00A020')
    await click(within(form).getByRole('button', { name: 'Сохранить' }))
    expect(await screen.findByText(/^Сохранено:/)).toHaveTextContent('Сохранено: Масло двигателя — 10 000 км, 120 мес.')
    expect(screen.queryByText(/целое число/)).not.toBeInTheDocument()
    const regs = await repo.listMaintenanceRegulations({ vehicle_model_id: 1 })
    expect(regs.find((r) => r.aggregate_type_code === 'engine_oil' && !r.is_archived)?.interval_months).toBe(120)
  })

  it('разряды через пробел — и в порогах «светофора» (U-04)', async () => {
    const { user, click, repo } = setup('/regulations')
    const yellow = await screen.findByLabelText('Жёлтый с, %')
    await user.clear(yellow)
    await user.type(yellow, '1 00')
    await user.clear(screen.getByLabelText('Красный выше, %'))
    await user.type(screen.getByLabelText('Красный выше, %'), '1\u202F50')
    await click(screen.getByRole('button', { name: 'Сохранить пороги' }))
    expect(await screen.findByText(/Пороги сохранены/)).toBeInTheDocument()
    expect(await repo.getAggregateStatusThresholds()).toMatchObject({ yellow_from_percent: 100, red_above_percent: 150 })
  })

  it('после сохранения — прежнее значение и «Показать историю версий» (A2)', async () => {
    const { user, click } = setup('/regulations')
    await click(await screen.findByRole('button', { name: 'Изменить интервал: Масло двигателя' }))
    const form = screen.getByRole('form', { name: 'Интервал: Масло двигателя' })
    await user.clear(within(form).getByLabelText('Интервал, км'))
    await user.type(within(form).getByLabelText('Интервал, км'), '12 000')
    await click(within(form).getByRole('button', { name: 'Сохранить' }))
    expect(await screen.findByText(/^Сохранено:/)).toHaveTextContent(
      'Сохранено: Масло двигателя — 12 000 км, 12 мес. (было 10 000 км, 12 мес.)',
    )
    expect(screen.queryByText(/в архиве/)).not.toBeInTheDocument()
    await click(screen.getByRole('button', { name: 'Показать историю версий' }))
    expect(screen.getByLabelText('Показать историю версий')).toBeChecked()
    expect((await screen.findByText(/в архиве/)).closest('tr')).toHaveTextContent('10 000')
    expect(screen.queryByRole('button', { name: 'Показать историю версий' })).not.toBeInTheDocument()
  })

  it('подтверждение пересмотра снимается архивированием и новым пересмотром — не противоречит таблице (A2)', async () => {
    const { user, click } = setup('/regulations')
    const revise = async (name: string, km: string) => {
      await click(await screen.findByRole('button', { name: `Изменить интервал: ${name}` }))
      const form = screen.getByRole('form', { name: `Интервал: ${name}` })
      await user.clear(within(form).getByLabelText('Интервал, км'))
      await user.type(within(form).getByLabelText('Интервал, км'), km)
      await click(within(form).getByRole('button', { name: 'Сохранить' }))
      expect(await screen.findByText(/^Сохранено:/)).toHaveTextContent(`Сохранено: ${name}`)
    }

    await revise('Масло двигателя', '12 000')
    await click(screen.getByRole('button', { name: 'Изменить интервал: Салонный фильтр' }))
    expect(screen.queryByText(/^Сохранено:/)).not.toBeInTheDocument()
    await click(within(screen.getByRole('form', { name: 'Интервал: Салонный фильтр' })).getByRole('button', { name: 'Отмена' }))

    await revise('Масло двигателя', '12 000')
    await click(screen.getByRole('button', { name: 'Архивировать регламент: Масло двигателя' }))
    await click(screen.getByRole('button', { name: 'Да, архивировать' }))
    expect((await screen.findByRole('rowheader', { name: 'Масло двигателя' })).closest('tr')).toHaveTextContent('Не отслеживается')
    expect(screen.queryByText(/^Сохранено:/)).not.toBeInTheDocument()
  })

  it('без интервалов — ошибка валидации у формы', async () => {
    const { user, click } = setup('/regulations')
    await click(await screen.findByRole('button', { name: 'Изменить интервал: Салонный фильтр' }))
    const form = screen.getByRole('form', { name: 'Интервал: Салонный фильтр' })
    await user.clear(within(form).getByLabelText('Интервал, км'))
    await user.clear(within(form).getByLabelText('Интервал, мес.'))
    await click(within(form).getByRole('button', { name: 'Сохранить' }))
    expect(await within(form).findByRole('alert')).toHaveTextContent('Укажите интервал')
  })

  it('модель без ДВС: агрегат не отслеживается → добавить регламент', async () => {
    const { user, click } = setup('/regulations')
    await click(await screen.findByRole('button', { name: 'Zeekr 001' }))
    const row = (await screen.findByRole('rowheader', { name: 'Масло двигателя' })).closest('tr')!
    expect(row).toHaveTextContent('Не отслеживается')
    await click(within(row).getByRole('button', { name: 'Добавить интервал: Масло двигателя' }))
    const form = screen.getByRole('form', { name: 'Интервал: Масло двигателя' })
    await user.type(within(form).getByLabelText('Интервал, мес.'), '24')
    await click(within(form).getByRole('button', { name: 'Сохранить' }))
    expect((await screen.findByRole('rowheader', { name: 'Масло двигателя' })).closest('tr')).toHaveTextContent('24')
    expect(screen.getByText(/^Сохранено:/)).toHaveTextContent('Сохранено: Масло двигателя — 24 мес. (раньше не отслеживался)')
    expect(screen.queryByRole('button', { name: 'Показать историю версий' })).not.toBeInTheDocument()
  })

  it('архивировать регламент — с подтверждением', async () => {
    const { click } = setup('/regulations')
    await click(await screen.findByRole('button', { name: 'Архивировать регламент: Фреон кондиционера' }))
    await click(screen.getByRole('button', { name: 'Да, архивировать' }))
    expect((await screen.findByRole('rowheader', { name: 'Фреон кондиционера' })).closest('tr')).toHaveTextContent('Не отслеживается')
  })

  it('пороги «светофора»: жёлтый ≥ красного — ошибка, корректные — сохраняются', async () => {
    const { user, click } = setup('/regulations')
    const yellow = await screen.findByLabelText('Жёлтый с, %')
    await user.clear(yellow)
    await user.type(yellow, '120')
    await click(screen.getByRole('button', { name: 'Сохранить пороги' }))
    expect(await screen.findByText(/жёлтый с.*красный выше/i)).toBeInTheDocument()
    await user.clear(screen.getByLabelText('Жёлтый с, %'))
    await user.type(screen.getByLabelText('Жёлтый с, %'), '75')
    await click(screen.getByRole('button', { name: 'Сохранить пороги' }))
    expect(await screen.findByText(/Пороги сохранены/)).toBeInTheDocument()
  })

  it('новый агрегат появляется в таблице', async () => {
    const { user, click } = setup('/regulations')
    await user.type(await screen.findByLabelText('Название'), 'Тормозная жидкость')
    await user.type(screen.getByLabelText('Код'), 'brake_fluid')
    await click(screen.getByRole('button', { name: 'Добавить агрегат' }))
    expect(await screen.findByRole('rowheader', { name: 'Тормозная жидкость' })).toBeInTheDocument()
  })
})

describe('конструктор статей базы знаний', () => {
  it('создать черновик и опубликовать', async () => {
    const { user, click } = setup('/articles')
    await click(await screen.findByRole('button', { name: 'Новая статья' }))
    await user.selectOptions(await screen.findByLabelText('Модель'), 'Li Auto L7')
    await user.selectOptions(screen.getByLabelText('Прошивка'), 'RU 2.4.1')
    await user.type(screen.getByLabelText('Заголовок'), 'Li Auto L7: пробки после RU 2.4.1')
    await user.type(screen.getByLabelText('Текст статьи'), 'Включите «Пробки» в настройках карты.')
    await click(screen.getByRole('button', { name: 'Сохранить черновик' }))
    expect(await screen.findByText('Черновик')).toBeInTheDocument()
    expect(window.location.hash).toMatch(/^#\/articles\/\d+$/)
    await click(screen.getByRole('button', { name: 'Опубликовать' }))
    expect(await screen.findByText('Опубликована')).toBeInTheDocument()
    await click(screen.getByRole('button', { name: '← К списку статей' }))
    const row = (await screen.findByRole('link', { name: 'Li Auto L7: пробки после RU 2.4.1' })).closest('tr')!
    expect(row).toHaveTextContent('Опубликована')
  })

  it('опубликовать черновик — 2 клика', async () => {
    const { click, clicks } = setup('/articles')
    await click(await screen.findByRole('link', { name: 'Voyah Free: сброс навигации к заводским настройкам' }))
    await click(await screen.findByRole('button', { name: 'Опубликовать' }))
    expect(await screen.findByText('Опубликована')).toBeInTheDocument()
    expect(clicks()).toBe(2)
  })

  it('после «Опубликовать» — где статью увидит клиент (U-08)', async () => {
    const { click } = setup('/articles/6')
    await click(await screen.findByRole('button', { name: 'Опубликовать' }))
    expect(await screen.findByText(/^Статья опубликована/)).toHaveTextContent(
      'Статья опубликована в базе знаний — владельцы Voyah Free увидят её в приложении: «Обучение».',
    )
    await click(screen.getByRole('button', { name: 'Снять с публикации' }))
    expect(await screen.findByText(/снята с публикации/)).toBeInTheDocument()
    expect(screen.queryByText(/^Статья опубликована/)).not.toBeInTheDocument()
  })

  it('итог публикации не переносится на другую статью и на новую форму («Назад»/«Вперёд», URL)', async () => {
    const { click } = setup('/articles/6')
    await click(await screen.findByRole('button', { name: 'Опубликовать' }))
    expect(await screen.findByText(/^Статья опубликована/)).toBeInTheDocument()

    await goTo('/articles/1')
    expect(await screen.findByDisplayValue('Мультимедиа после русификации: первые шаги')).toBeInTheDocument()
    expect(screen.queryByText(/^Статья опубликована/)).not.toBeInTheDocument()

    await goTo('/articles/6')
    expect(await screen.findByRole('button', { name: 'Снять с публикации' })).toBeInTheDocument()
    expect(screen.queryByText(/^Статья опубликована/)).not.toBeInTheDocument()
  })

  it('новая статья: «Опубликовать» → «Назад» на /articles/new — пустая форма без итога публикации', async () => {
    const { user, click } = setup('/articles/new')
    await user.type(await screen.findByLabelText('Заголовок'), 'Как подключить телефон по Bluetooth')
    await user.type(screen.getByLabelText('Текст статьи'), 'Откройте «Настройки» → Bluetooth.')
    await click(screen.getByRole('button', { name: 'Сохранить черновик' }))
    await click(await screen.findByRole('button', { name: 'Опубликовать' }))
    expect(await screen.findByText(/^Статья опубликована/)).toBeInTheDocument()

    await goTo('/articles/new')
    expect(await screen.findByRole('heading', { name: 'Новая статья' })).toBeInTheDocument()
    expect(screen.getByLabelText('Заголовок')).toHaveValue('')
    expect(screen.queryByText(/^Статья опубликована/)).not.toBeInTheDocument()
  })

  it('неполадки после публикации — «Поддержка» → «Неполадки»', async () => {
    const { click } = setup('/articles/11')
    await click(await screen.findByRole('button', { name: 'Снять с публикации' }))
    await click(await screen.findByRole('button', { name: 'Опубликовать' }))
    expect(await screen.findByText(/^Статья опубликована/)).toHaveTextContent(
      'Статья опубликована в базе знаний — клиенты всех моделей увидят её в приложении: «Поддержка» → «Неполадки».',
    )
  })

  it('«Устранение неполадок»: дерево решений — вкладка вверху редактора с числом шагов; текст — вступление (U-09)', async () => {
    const { user, click } = setup('/articles/11')
    const tabs = await screen.findByRole('tablist', { name: 'Разделы статьи' })
    const textTab = within(tabs).getByRole('tab', { name: 'Текст статьи' })
    const treeTab = await within(tabs).findByRole('tab', { name: 'Дерево решений · 3 шага' })
    expect(textTab).toHaveAttribute('aria-selected', 'true')
    // Вкладки — первыми в редакторе, до формы: видны без прокрутки.
    const intro = screen.getByLabelText('Вступление')
    expect(tabs.compareDocumentPosition(intro) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy()
    expect(tabs.compareDocumentPosition(screen.getByLabelText('Заголовок')) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy()
    expect(intro).toHaveAccessibleDescription(/Вопросы и варианты ответа клиента настраиваются в дереве решений/)
    expect(screen.queryByRole('textbox', { name: 'Текст статьи' })).not.toBeInTheDocument()
    expect(screen.getByText(/Дальше — вопросы дерева решений: 3 шага/)).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Добавить шаг' })).not.toBeInTheDocument()

    await click(treeTab)
    expect(treeTab).toHaveAttribute('aria-selected', 'true')
    expect(screen.getByRole('tabpanel', { name: 'Дерево решений · 3 шага' })).toBeVisible()
    expect(screen.getByRole('button', { name: 'Добавить шаг' })).toBeInTheDocument()
    expect(intro).not.toBeVisible()

    // Клавиатура: стрелки переключают вкладки (WAI-ARIA Tabs).
    await user.keyboard('{ArrowLeft}')
    expect(textTab).toHaveAttribute('aria-selected', 'true')
    expect(textTab).toHaveFocus()
    expect(intro).toBeVisible()
  })

  it('новая статья «Устранение неполадок»: поле — вступление, дерево — после сохранения черновика', async () => {
    const { user } = setup('/articles/new')
    await user.selectOptions(await screen.findByLabelText('Тип'), 'Устранение неполадок')
    expect(screen.getByLabelText('Вступление')).toHaveAccessibleDescription(/в дереве решений — после сохранения черновика/)
    expect(screen.queryByRole('tablist')).not.toBeInTheDocument()
  })

  it('инструкция — без вкладок: поле «Текст статьи», как раньше', async () => {
    setup('/articles/1')
    expect(await screen.findByLabelText('Текст статьи')).toBeInTheDocument()
    expect(screen.queryByRole('tablist')).not.toBeInTheDocument()
    expect(screen.queryByRole('heading', { name: 'Дерево решений' })).not.toBeInTheDocument()
  })

  it('заголовок обязателен', async () => {
    const { click } = setup('/articles/new')
    await click(await screen.findByRole('button', { name: 'Сохранить черновик' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('Введите заголовок')
  })

  it('фильтр «Черновики» и поиск', async () => {
    const { user, click } = setup('/articles')
    await screen.findByRole('link', { name: 'Завис экран мультимедиа' })
    await click(screen.getByRole('button', { name: 'Черновики' }))
    expect(screen.getAllByRole('link').filter((a) => a.closest('table'))).toHaveLength(1)
    await click(within(screen.getByRole('group', { name: 'Статус публикации' })).getByRole('button', { name: 'Все' }))
    await user.type(screen.getByLabelText('Поиск по статьям'), 'голосовой')
    expect(await screen.findByRole('link', { name: 'Zeekr 001: голосовой помощник на русском' })).toBeInTheDocument()
  })

  it('дерево решений: проверка без ошибок; шаг-тупик — ошибка и запрет публикации', async () => {
    const { user, click } = setup('/articles/10')
    await click(await screen.findByRole('tab', { name: 'Дерево решений · 6 шагов' }))
    await click(screen.getByRole('button', { name: 'Проверить дерево' }))
    expect(await screen.findByText(/Ошибок нет/)).toBeInTheDocument()

    await click(screen.getByRole('button', { name: 'Добавить шаг' }))
    const form = screen.getByRole('form', { name: 'Новый шаг' })
    await user.type(within(form).getByLabelText('Вопрос или инструкция'), 'Проверьте предохранитель')
    await click(within(form).getByRole('button', { name: 'Добавить вариант' }))
    await user.type(within(form).getByLabelText('Вариант 1'), 'Не помогло')
    await click(within(form).getByRole('button', { name: 'Сохранить шаг' }))
    await click(await screen.findByRole('button', { name: 'Проверить дерево' }))
    expect(await screen.findByText(/Найдено ошибок: 2/)).toBeInTheDocument()
    expect(screen.getByText(/тупик/)).toBeInTheDocument()
    expect(screen.getByText(/недостижим/)).toBeInTheDocument()
    expect(screen.getByRole('tab', { name: 'Дерево решений · 7 шагов' })).toBeInTheDocument()

    await click(screen.getByRole('tab', { name: 'Текст статьи' }))
    await click(screen.getByRole('button', { name: 'Снять с публикации' }))
    await click(await screen.findByRole('button', { name: 'Опубликовать' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('В дереве решений есть ошибки')
  })
})

describe('лента публикаций', () => {
  it('новость для всех моделей — 1 клик после ввода темы и текста; первая в ленте', async () => {
    const { user, click, clicks } = setup('/publications')
    await user.type(await screen.findByLabelText('Тема'), 'Зимний режим')
    await user.type(screen.getByLabelText('Текст уведомления'), 'С 1 ноября — зимний режим работы сервиса.')
    expect(screen.getByText('Предпросмотр push-уведомления').parentElement).toHaveTextContent('зимний режим')
    await click(screen.getByRole('button', { name: 'Опубликовать' }))
    expect(await screen.findByText(/поставлено в очередь/)).toBeInTheDocument()
    const feed = screen.getByRole('region', { name: 'Опубликовано' })
    expect(within(feed).getAllByRole('listitem')[0]).toHaveTextContent('зимний режим')
    expect(clicks()).toBe(1)
  })

  it('выпустить прошивку — 2 клика (выбор модели и версия — ввод)', async () => {
    const { user, click, clicks } = setup('/publications')
    await click(await screen.findByLabelText('Прошивка'))
    await user.selectOptions(screen.getByLabelText('Модель'), 'Zeekr 001')
    await user.type(screen.getByLabelText('Версия'), 'RU 5.2.0')
    await click(screen.getByRole('button', { name: 'Опубликовать' }))
    expect(await screen.findByText(/Релиз опубликован/)).toBeInTheDocument()
    expect(clicks()).toBe(2)
  })

  it('пояснение раздела: здесь рассылки, статьи — в базе знаний (переход по ссылке) (U-08)', async () => {
    const { click } = setup('/publications')
    await screen.findByLabelText('Тема')
    expect(screen.getByText(/рассылка уведомлений клиентам: push и лента «Новости» в приложении/)).toBeInTheDocument()
    await click(screen.getByRole('link', { name: '«База знаний»' }))
    expect(await screen.findByRole('heading', { name: 'Админ-панель · База знаний' })).toBeInTheDocument()
  })

  it('тема обязательна: без темы — ошибка у поля, ничего не отправлено (U-08)', async () => {
    const { user, click, repo } = setup('/publications')
    await user.type(await screen.findByLabelText('Текст уведомления'), 'Откройте «Настройки» → Bluetooth.')
    await click(screen.getByRole('button', { name: 'Опубликовать' }))
    const subject = screen.getByLabelText('Тема')
    expect(subject).toHaveAttribute('aria-invalid', 'true')
    expect(subject).toHaveAccessibleDescription('Укажите тему')
    expect(screen.queryByText(/поставлено в очередь/)).not.toBeInTheDocument()
    expect(await repo.listPublishedNotifications()).toHaveLength(4)
  })

  it('тема — первой строкой message; предпросмотр и лента — тема заголовком, текст ниже; счётчик — тема + текст', async () => {
    const { user, click, repo } = setup('/publications')
    const subject = 'Зимний режим'
    const text = 'С 1 ноября сервис работает до 18:00.'
    await user.type(await screen.findByLabelText('Тема'), subject)
    await user.type(screen.getByLabelText('Текст уведомления'), text)
    expect(screen.getByLabelText('Текст уведомления')).toHaveAccessibleDescription(
      `Тема и текст: ${subject.length + 1 + text.length} / 500`,
    )
    const preview = screen.getByText('Предпросмотр push-уведомления').parentElement!
    expect(within(preview).getByText(subject).nextElementSibling).toHaveTextContent(text)

    await click(screen.getByRole('button', { name: 'Опубликовать' }))
    expect(await screen.findByText(/поставлено в очередь/)).toHaveTextContent('все клиенты')
    expect((await repo.listPublishedNotifications())[0].message).toBe(`${subject}\n${text}`)
    const item = within(screen.getByRole('region', { name: 'Опубликовано' })).getAllByRole('listitem')[0]
    expect(within(item).getByText(subject).nextElementSibling).toHaveTextContent(text)
  })

  it('тема и текст вместе длиннее 500 — ошибка, публикация не уходит', async () => {
    const { user, click, repo } = setup('/publications')
    await user.type(await screen.findByLabelText('Тема'), 'Тема')
    await user.click(screen.getByLabelText('Текст уведомления'))
    await user.paste('а'.repeat(496))
    expect(screen.getByLabelText('Текст уведомления')).toHaveAccessibleDescription(/не длиннее 500 символов: 501 \/ 500/)
    // Лимит держит форма: в контракте у message нет maxLength — запрос не должен уйти вовсе.
    const create = vi.spyOn(repo, 'createNotification')
    await click(screen.getByRole('button', { name: 'Опубликовать' }))
    expect(create).not.toHaveBeenCalled()
    expect(screen.queryByText(/поставлено в очередь/)).not.toBeInTheDocument()
    expect(await repo.listPublishedNotifications()).toHaveLength(4)
  })

  it('прошивка: тему формирует система; версия — пример в подсказке, не в placeholder (A7)', async () => {
    const { click } = setup('/publications')
    await click(await screen.findByLabelText('Прошивка'))
    expect(screen.queryByLabelText('Тема')).not.toBeInTheDocument()
    expect(screen.getByText(/Тему уведомления о прошивке формирует система/)).toBeInTheDocument()
    const version = screen.getByLabelText('Версия')
    expect(version).not.toHaveAttribute('placeholder')
    expect(version).toHaveAccessibleDescription('Например: RU 2.6.0')
  })

  it('после публикации форма — в исходном состоянии: релиз для L7 → новость уходит всем моделям (U-03)', async () => {
    const { user, click, repo } = setup('/publications')
    await click(await screen.findByLabelText('Прошивка'))
    await user.selectOptions(screen.getByLabelText('Модель'), 'Li Auto L7')
    await user.type(screen.getByLabelText('Версия'), 'RU 2.5.0')
    await user.clear(screen.getByLabelText('Дата выпуска'))
    await user.type(screen.getByLabelText('Дата выпуска'), '2026-10-01')
    expect(screen.getByLabelText('Дата выпуска')).toHaveValue('2026-10-01')
    await click(screen.getByRole('button', { name: 'Опубликовать' }))
    expect(await screen.findByText(/Релиз опубликован/)).toBeInTheDocument()
    expect(await repo.listFirmwareReleases({ vehicle_model_id: 1 })).toContainEqual(
      expect.objectContaining({ version: 'RU 2.5.0', released_at: '2026-10-01' }),
    )

    expect(screen.getByLabelText('Новость')).toBeChecked()
    expect(screen.getByLabelText('Аудитория')).toHaveValue('')
    expect(screen.getByLabelText('Тема')).toHaveValue('')
    expect(screen.getByLabelText('Текст уведомления')).toHaveValue('')
    expect(screen.getByText(/Релиз опубликован/)).toBeInTheDocument()
    await click(screen.getByLabelText('Прошивка'))
    expect(screen.getByLabelText('Модель')).toHaveValue('')
    expect(screen.getByLabelText('Версия')).toHaveValue('')
    expect(screen.getByLabelText('Дата выпуска')).toHaveValue('2026-10-10')
    // Раунд 2: сообщение о прошлой публикации скрывается, как только начата новая.
    expect(screen.queryByText(/Релиз опубликован/)).not.toBeInTheDocument()

    await click(screen.getByLabelText('Новость'))
    await user.type(screen.getByLabelText('Тема'), 'Зимний режим')
    await user.type(screen.getByLabelText('Текст уведомления'), 'С 1 ноября — зимний режим работы сервиса.')
    await click(screen.getByRole('button', { name: 'Опубликовать' }))
    expect(await screen.findByText(/поставлено в очередь/)).toHaveTextContent('все клиенты')
    const feed = screen.getByRole('region', { name: 'Опубликовано' })
    expect(within(feed).getAllByRole('listitem')[0]).toHaveTextContent('Аудитория: Все модели')
    expect((await repo.listPublishedNotifications())[0].target_vehicle_model_id).toBeNull()
  })

  it('прошивка: без модели — ошибка; с моделью — релиз и уведомление с таргетингом', async () => {
    const { user, click } = setup('/publications')
    await click(await screen.findByLabelText('Прошивка'))
    await user.type(screen.getByLabelText('Версия'), 'RU 1.9.0')
    await click(screen.getByRole('button', { name: 'Опубликовать' }))
    expect(await screen.findByText('Выберите модель')).toBeInTheDocument()
    await user.selectOptions(screen.getByLabelText('Модель'), 'Voyah Free')
    await click(screen.getByRole('button', { name: 'Опубликовать' }))
    expect(await screen.findByText(/Релиз опубликован/)).toBeInTheDocument()
    const feed = screen.getByRole('region', { name: 'Опубликовано' })
    expect(within(feed).getAllByRole('listitem')[0]).toHaveTextContent('Аудитория: Voyah Free')
    expect(within(screen.getByRole('region', { name: 'Релизы прошивок' })).getByText('RU 1.9.0')).toBeInTheDocument()
  })
})
