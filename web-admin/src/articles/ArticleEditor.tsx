// Конструктор статьи базы знаний (ТЗ 4.4): тип, модель, прошивка (C-06), заголовок, текст; черновик →
// публикация. Тип, модель и прошивка задаются при создании — в KnowledgeArticleUpdateRequest их нет.
// Для «Устранения неполадок» — дерево решений (публикация только без ошибок дерева) на отдельной вкладке
// вверху редактора: на юзабилити-тесте (U-09) блок дерева под формой не нашли — вопрос дописали в текст.
// Глава 22 (ADR 0026 п. 9): «Сохранить и опубликовать» — и у новой статьи, и при несохранённых правках
// (U-05, U-43); правка опубликованной сразу выпускает новую версию — кнопка так и называется; история
// версий — только для чтения. Фото и видео — ссылками в тексте (ADR 0018).
import { useId, useState, type FormEvent, type KeyboardEvent } from 'react'
import {
  ARTICLE_TYPE_LABELS,
  Badge,
  Button,
  Card,
  ErrorState,
  InlineError,
  LoadingState,
  Select,
  TICKET_CATEGORIES,
  TICKET_CATEGORY_LABELS,
  TextArea,
  TextField,
  errorText,
  plural,
  useAsync,
  type ArticleType,
  type DecisionTreeNode,
  type KnowledgeArticle,
  type TicketCategory,
  type VehicleModel,
} from '@ev-servicedesk/web-shared'
import { modelName, useAdmin } from '../repo.ts'
import { DecisionTreeEditor } from './DecisionTreeEditor.tsx'
import { Revisions } from './Revisions.tsx'

const TITLE_MAX = 200

const stepsOf = (n: number) => plural(n, 'шаг', 'шага', 'шагов')

/** Где опубликованную статью увидит клиент (U-08: статью после публикации искали в «Публикациях»). */
function publishedNotice(article: KnowledgeArticle, models: VehicleModel[]): string {
  const who = article.vehicle_model_id == null ? 'клиенты всех моделей' : `владельцы ${modelName(models, article.vehicle_model_id)}`
  const where = article.article_type === 'guide' ? '«Обучение»' : '«Поддержка» → «Неполадки»'
  return `Статья опубликована в базе знаний — ${who} увидят её в приложении: ${where}.`
}

/** Итог публикации или снятия с публикации и состояние статьи, о котором он сообщает; failed — не удалось. */
export type Notice = { text: string; published: boolean; failed?: boolean }

type Tab = 'text' | 'tree'
const TABS: Tab[] = ['text', 'tree']

export function ArticleEditor({
  articleId,
  initialNotice = null,
  onSaved,
  onBack,
}: {
  /** null — новая статья. */
  articleId: number | null
  /** Итог действия, начатого на другом адресе («Сохранить и опубликовать» новой статьи, U-05). */
  initialNotice?: Notice | null
  /** Статья сохранена под другим адресом (новая) — перейти к ней, передав итог. */
  onSaved: (id: number, notice?: Notice) => void
  onBack: () => void
}) {
  const { repo } = useAdmin()
  const [version, setVersion] = useState(0)
  /**
   * Итог публикации — здесь, а не в форме: после публикации форма монтируется заново (key). Относится только к
   * этой статье: при смене articleId редактор монтируется заново (key в App), и сообщение пропадает.
   * Показывается только вместе с перечитанной статьёй: пока ответ не пришёл, на экране прежняя форма
   * («Черновик», «Опубликовать») — итог рядом с ней противоречил бы бейджу и пропал бы с её перемонтированием.
   */
  const [notice, setNotice] = useState<Notice | null>(initialNotice)
  const article = useAsync(
    () => (articleId === null ? Promise.resolve(null) : repo.getKnowledgeArticle(articleId)),
    [repo, articleId, version],
  )

  return (
    <div className="grid gap-4">
      <div>
        <Button variant="ghost" size="sm" onClick={onBack}>
          ← К списку статей
        </Button>
      </div>
      {article.error ? (
        <ErrorState error={article.error} onRetry={article.reload} />
      ) : article.data === undefined ? (
        <LoadingState />
      ) : (
        <ArticleForm
          key={`${articleId}-${article.data?.version}-${article.data?.is_published}`}
          article={article.data}
          notice={notice && notice.published === article.data?.is_published ? notice : null}
          onSaved={(id, next) => {
            setNotice(next ?? null)
            if (id === articleId) setVersion((v) => v + 1)
            else onSaved(id, next)
          }}
        />
      )}
    </div>
  )
}

function ArticleForm({
  article,
  notice,
  onSaved,
}: {
  article: KnowledgeArticle | null
  notice: Notice | null
  /** next — итог действия (публикация, снятие с публикации). */
  onSaved: (id: number, next?: Notice) => void
}) {
  const { repo, models } = useAdmin()
  const isNew = article === null
  const [type, setType] = useState<ArticleType>(article?.article_type ?? 'guide')
  const [modelId, setModelId] = useState<string>(article?.vehicle_model_id?.toString() ?? '')
  const [firmwareId, setFirmwareId] = useState<string>(article?.firmware_release_id?.toString() ?? '')
  const [title, setTitle] = useState(article?.title ?? '')
  const [content, setContent] = useState(article?.content ?? '')
  // Категория ошибки = категория тикета; у «Устранения неполадок» обязательна (CATEGORY_REQUIRED).
  const [category, setCategory] = useState<TicketCategory | ''>(article?.category ?? '')
  const [noCategory, setNoCategory] = useState(false)
  const [error, setError] = useState<unknown>(null)
  const [busy, setBusy] = useState(false)
  const firmware = useAsync(
    () => (modelId ? repo.listFirmwareReleases({ vehicle_model_id: Number(modelId) }) : Promise.resolve([])),
    [repo, modelId],
  )
  const troubleshooting = (article?.article_type ?? type) === 'troubleshooting'
  const dirty =
    !isNew &&
    (title !== article.title || content !== (article.content ?? '') || (troubleshooting && category !== (article.category ?? '')))
  /** Поля правки: категория — только у «Устранения неполадок». */
  const changes = () => ({ title, content, ...(troubleshooting && category ? { category } : {}) })
  const hasTree = !isNew && troubleshooting
  const [tab, setTab] = useState<Tab>('text')
  const [treeVersion, setTreeVersion] = useState(0)
  const tree = useAsync(
    () => (article && hasTree ? repo.listDecisionTreeNodes(article.id) : Promise.resolve<DecisionTreeNode[]>([])),
    [repo, article?.id, hasTree, treeVersion],
  )
  const tabsId = useId()

  /** Категория не выбрана — подсказка у поля, запрос не уходит. */
  const missingCategory = () => {
    const missing = troubleshooting && !category
    setNoCategory(missing)
    return missing
  }

  const run = async (action: () => Promise<number>, next?: Notice) => {
    if (missingCategory()) return
    setBusy(true)
    setError(null)
    try {
      onSaved(await action(), next)
    } catch (e) {
      setError(e)
      setBusy(false)
    }
  }

  const create = () =>
    repo.createKnowledgeArticle({
      article_type: type,
      title,
      content,
      vehicle_model_id: modelId ? Number(modelId) : null,
      firmware_release_id: firmwareId ? Number(firmwareId) : null,
      ...(troubleshooting && category ? { category } : {}),
    })

  const save = (e?: FormEvent) => {
    e?.preventDefault()
    return run(async () => (isNew ? (await create()).id : (await repo.updateKnowledgeArticle(article.id, changes())).id))
  }

  /**
   * U-05: новая инструкция — сохранить и опубликовать одним действием. Черновик создан, а публикация
   * не прошла — открываем черновик с причиной (созданное не теряется).
   */
  const createAndPublish = async () => {
    if (missingCategory()) return
    setBusy(true)
    setError(null)
    let created: KnowledgeArticle
    try {
      created = await create()
    } catch (e) {
      setError(e)
      setBusy(false)
      return
    }
    try {
      const published = await repo.updateKnowledgeArticle(created.id, { is_published: true })
      onSaved(created.id, { text: publishedNotice(published, models), published: true })
    } catch (e) {
      onSaved(created.id, { text: `Черновик сохранён, но не опубликован: ${errorText(e)}`, published: false, failed: true })
    }
  }

  const togglePublish = () =>
    run(
      async () => {
        if (article!.is_published) {
          await repo.unpublishKnowledgeArticle(article!.id)
        } else {
          await repo.updateKnowledgeArticle(article!.id, { ...changes(), is_published: true })
        }
        return article!.id
      },
      article!.is_published
        ? { text: 'Статья снята с публикации — клиенты её больше не видят.', published: false }
        : { text: publishedNotice(article!, models), published: true },
    )

  const published = !isNew && article.is_published

  const categorySelect = (
    <Select
      label="Категория ошибки"
      hint="Как категория тикета: по ней клиент находит статью в «Неполадках»"
      error={noCategory ? 'Выберите категорию ошибки' : undefined}
      value={category}
      onChange={(e) => {
        setCategory(e.target.value as TicketCategory | '')
        setNoCategory(false)
      }}
    >
      <option value="">— выберите —</option>
      {TICKET_CATEGORIES.map((c) => (
        <option key={c} value={c}>
          {TICKET_CATEGORY_LABELS[c]}
        </option>
      ))}
    </Select>
  )

  /** Вкладки — по шаблону WAI-ARIA Tabs: стрелки, Home/End. */
  const onTabKey = (e: KeyboardEvent) => {
    const i = TABS.indexOf(tab)
    const keys: Record<string, Tab> = {
      ArrowRight: TABS[(i + 1) % TABS.length],
      ArrowLeft: TABS[(i - 1 + TABS.length) % TABS.length],
      Home: TABS[0],
      End: TABS[TABS.length - 1],
    }
    const next = keys[e.key]
    if (!next) return
    e.preventDefault()
    setTab(next)
    document.getElementById(`${tabsId}-tab-${next}`)?.focus()
  }

  const editor = (
    <div className="grid grid-cols-[minmax(0,1fr)_22rem] items-start gap-6">
      <Card>
        <form onSubmit={save} className="grid gap-4" aria-label={isNew ? 'Новая статья' : `Статья: ${article.title}`}>
          <div className="flex items-center justify-between gap-3">
            <h2 className="text-h3">{isNew ? 'Новая статья' : 'Редактирование статьи'}</h2>
            {!isNew && (
              <span className="flex items-center gap-2">
                <Badge tone={article.is_published ? 'success' : 'neutral'}>{article.is_published ? 'Опубликована' : 'Черновик'}</Badge>
                <Badge>v{article.version}</Badge>
              </span>
            )}
          </div>

          {isNew ? (
            <div className={`grid gap-4 ${troubleshooting ? 'grid-cols-4' : 'grid-cols-3'}`}>
              <Select label="Тип" value={type} onChange={(e) => setType(e.target.value as ArticleType)}>
                {(['guide', 'troubleshooting'] as const).map((t) => (
                  <option key={t} value={t}>
                    {ARTICLE_TYPE_LABELS[t]}
                  </option>
                ))}
              </Select>
              <Select
                label="Модель"
                value={modelId}
                onChange={(e) => {
                  setModelId(e.target.value)
                  setFirmwareId('')
                }}
              >
                <option value="">Все модели</option>
                {models.map((m) => (
                  <option key={m.id} value={m.id}>
                    {m.brand} {m.model}
                  </option>
                ))}
              </Select>
              <Select
                label="Прошивка"
                hint={modelId ? undefined : 'Сначала выберите модель'}
                disabled={!modelId}
                value={firmwareId}
                onChange={(e) => setFirmwareId(e.target.value)}
              >
                <option value="">Любая</option>
                {(firmware.data ?? []).map((f) => (
                  <option key={f.id} value={f.id}>
                    {f.version}
                  </option>
                ))}
              </Select>
              {troubleshooting && categorySelect}
            </div>
          ) : (
            <p className="text-body-sm text-fg-muted">
              {ARTICLE_TYPE_LABELS[article.article_type]} · {modelName(models, article.vehicle_model_id)}
              {article.firmware_release_id
                ? ` · прошивка ${(firmware.data ?? []).find((f) => f.id === article.firmware_release_id)?.version ?? ''}`
                : ''}
            </p>
          )}
          {!isNew && troubleshooting && <div className="max-w-xs">{categorySelect}</div>}

          <TextField
            label="Заголовок"
            maxLength={TITLE_MAX}
            hint={`${title.length} / ${TITLE_MAX}`}
            value={title}
            onChange={(e) => setTitle(e.target.value)}
          />
          {troubleshooting ? (
            <TextArea
              label="Вступление"
              rows={4}
              hint={`Коротко о проблеме — клиент видит это перед вопросами. Вопросы и варианты ответа клиента настраиваются в дереве решений${
                isNew ? ' — после сохранения черновика' : ''
              }.`}
              value={content}
              onChange={(e) => setContent(e.target.value)}
            />
          ) : (
            <TextArea
              label="Текст статьи"
              rows={12}
              hint="Шаги — с новой строки, пути в меню — через «→». Фото и видео — ссылкой на файл: ![подпись](https://…)."
              value={content}
              onChange={(e) => setContent(e.target.value)}
            />
          )}
          <InlineError error={error} />
          {notice && !error && (
            <p role="status" className={`text-body-sm ${notice.failed ? 'text-danger-text' : 'text-status-green-fg'}`}>
              {notice.text}
            </p>
          )}
          {published && dirty && (
            <p className="text-caption text-fg-muted">
              Статья опубликована: сохранение выпустит версию {article.version + 1} — клиенты увидят её сразу.
            </p>
          )}
          <div className="flex flex-wrap gap-2">
            <Button type="submit" variant={isNew || published ? 'primary' : 'secondary'} disabled={busy || (!isNew && !dirty)}>
              {isNew ? 'Сохранить черновик' : published ? 'Опубликовать изменения' : 'Сохранить черновик'}
            </Button>
            {/* U-05: дерево решений появляется после сохранения — новую статью «неполадок» сразу не опубликовать. */}
            {isNew && !troubleshooting && (
              <Button variant="secondary" disabled={busy} onClick={createAndPublish}>
                Сохранить и опубликовать
              </Button>
            )}
            {!isNew && (
              <Button variant={article.is_published ? 'secondary' : 'primary'} disabled={busy} onClick={togglePublish}>
                {article.is_published ? 'Снять с публикации' : dirty ? 'Сохранить и опубликовать' : 'Опубликовать'}
              </Button>
            )}
          </div>
        </form>
      </Card>

      <aside className="grid gap-4">
        <Card className="grid gap-2">
          <h2 className="text-label">Так статью увидит клиент</h2>
          <p className="text-h3">{title || 'Заголовок статьи'}</p>
          <p className="whitespace-pre-line text-body-sm text-fg-muted">{content || (troubleshooting ? 'Вступление' : 'Текст статьи')}</p>
          {troubleshooting && (
            <p className="text-caption text-fg-muted">
              Дальше — вопросы дерева решений{hasTree && tree.data ? `: ${stepsOf(tree.data.length)}` : ''}.
            </p>
          )}
        </Card>
        {!isNew && <Revisions article={article} />}
      </aside>
    </div>
  )

  if (!hasTree) return editor

  const tabLabel = (t: Tab) => (t === 'text' ? 'Текст статьи' : `Дерево решений${tree.data ? ` · ${stepsOf(tree.data.length)}` : ''}`)
  return (
    <div className="grid gap-4">
      <div role="tablist" aria-label="Разделы статьи" className="flex gap-1 border-b border-border" onKeyDown={onTabKey}>
        {TABS.map((t) => (
          <button
            key={t}
            type="button"
            role="tab"
            id={`${tabsId}-tab-${t}`}
            aria-selected={tab === t}
            aria-controls={`${tabsId}-panel-${t}`}
            tabIndex={tab === t ? 0 : -1}
            onClick={() => setTab(t)}
            className={`-mb-px border-b-2 px-3 py-2 text-label transition-colors duration-(--duration-fast) ${
              tab === t ? 'border-fg text-fg' : 'border-transparent text-fg-muted hover:text-fg'
            }`}
          >
            {tabLabel(t)}
          </button>
        ))}
      </div>
      <div role="tabpanel" id={`${tabsId}-panel-text`} aria-labelledby={`${tabsId}-tab-text`} hidden={tab !== 'text'}>
        {editor}
      </div>
      {/* Обе панели смонтированы: при переключении не теряются ввод в форме и незавершённый шаг дерева. */}
      <div role="tabpanel" id={`${tabsId}-panel-tree`} aria-labelledby={`${tabsId}-tab-tree`} hidden={tab !== 'tree'}>
        <DecisionTreeEditor
          articleId={article.id}
          published={article.is_published}
          nodes={tree}
          onChanged={() => setTreeVersion((v) => v + 1)}
        />
      </div>
    </div>
  )
}
