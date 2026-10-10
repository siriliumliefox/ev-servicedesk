// Прототип админ-панели (Глава 8, ADR 0012): конструктор регламентов ТО, конструктор статей и дерево
// решений, лента публикаций, дашборд; клики — для таблицы в docs/design/WEB_PROTOTYPE.md.
import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'
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
    await click(await screen.findByRole('button', { name: 'Проверить дерево' }))
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

    await click(screen.getByRole('button', { name: 'Снять с публикации' }))
    await click(await screen.findByRole('button', { name: 'Опубликовать' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('В дереве решений есть ошибки')
  })
})

describe('лента публикаций', () => {
  it('новость для всех моделей — 1 клик после ввода текста; первая в ленте', async () => {
    const { user, click, clicks } = setup('/publications')
    await user.type(await screen.findByLabelText('Текст уведомления'), 'С 1 ноября — зимний режим работы сервиса.')
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
