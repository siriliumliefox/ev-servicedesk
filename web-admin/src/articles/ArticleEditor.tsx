// Конструктор статьи базы знаний (ТЗ 4.4): тип, модель, прошивка (C-06), заголовок, текст; черновик →
// публикация. Тип, модель и прошивка задаются при создании — в KnowledgeArticleUpdateRequest их нет.
// Для «Устранения неполадок» — дерево решений (публикация только без ошибок дерева).
import { useState, type FormEvent } from 'react'
import {
  ARTICLE_TYPE_LABELS,
  Badge,
  Button,
  Card,
  ErrorState,
  InlineError,
  LoadingState,
  Select,
  TextArea,
  TextField,
  useAsync,
  type ArticleType,
  type KnowledgeArticle,
} from '@ev-servicedesk/web-shared'
import { modelName, useAdmin } from '../repo.ts'
import { DecisionTreeEditor } from './DecisionTreeEditor.tsx'

const TITLE_MAX = 200

export function ArticleEditor({
  articleId,
  onSaved,
  onBack,
}: {
  /** null — новая статья. */
  articleId: number | null
  onSaved: (id: number) => void
  onBack: () => void
}) {
  const { repo } = useAdmin()
  const [version, setVersion] = useState(0)
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
          onSaved={(id) => (id === articleId ? setVersion((v) => v + 1) : onSaved(id))}
        />
      )}
    </div>
  )
}

function ArticleForm({ article, onSaved }: { article: KnowledgeArticle | null; onSaved: (id: number) => void }) {
  const { repo, models } = useAdmin()
  const isNew = article === null
  const [type, setType] = useState<ArticleType>(article?.article_type ?? 'guide')
  const [modelId, setModelId] = useState<string>(article?.vehicle_model_id?.toString() ?? '')
  const [firmwareId, setFirmwareId] = useState<string>(article?.firmware_release_id?.toString() ?? '')
  const [title, setTitle] = useState(article?.title ?? '')
  const [content, setContent] = useState(article?.content ?? '')
  const [error, setError] = useState<unknown>(null)
  const [busy, setBusy] = useState(false)
  const firmware = useAsync(
    () => (modelId ? repo.listFirmwareReleases({ vehicle_model_id: Number(modelId) }) : Promise.resolve([])),
    [repo, modelId],
  )
  const dirty = !isNew && (title !== article.title || content !== (article.content ?? ''))

  const run = async (action: () => Promise<number>) => {
    setBusy(true)
    setError(null)
    try {
      onSaved(await action())
    } catch (e) {
      setError(e)
      setBusy(false)
    }
  }

  const save = (e?: FormEvent) => {
    e?.preventDefault()
    return run(async () =>
      isNew
        ? (
            await repo.createKnowledgeArticle({
              article_type: type,
              title,
              content,
              vehicle_model_id: modelId ? Number(modelId) : null,
              firmware_release_id: firmwareId ? Number(firmwareId) : null,
            })
          ).id
        : (await repo.updateKnowledgeArticle(article.id, { title, content })).id,
    )
  }

  const togglePublish = () =>
    run(async () => {
      if (article!.is_published) {
        await repo.unpublishKnowledgeArticle(article!.id)
      } else {
        await repo.updateKnowledgeArticle(article!.id, { title, content, is_published: true })
      }
      return article!.id
    })

  return (
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
            <div className="grid grid-cols-3 gap-4">
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
            </div>
          ) : (
            <p className="text-body-sm text-fg-muted">
              {ARTICLE_TYPE_LABELS[article.article_type]} · {modelName(models, article.vehicle_model_id)}
              {article.firmware_release_id ? ` · прошивка #${article.firmware_release_id}` : ''}
            </p>
          )}

          <TextField
            label="Заголовок"
            maxLength={TITLE_MAX}
            hint={`${title.length} / ${TITLE_MAX}`}
            value={title}
            onChange={(e) => setTitle(e.target.value)}
          />
          <TextArea
            label="Текст статьи"
            rows={12}
            hint="Шаги — с новой строки, пути в меню — через «→». Фото и видео к статье — после решения по вложениям (глава 14)."
            value={content}
            onChange={(e) => setContent(e.target.value)}
          />
          <InlineError error={error} />
          <div className="flex flex-wrap gap-2">
            <Button type="submit" variant={isNew ? 'primary' : 'secondary'} disabled={busy || (!isNew && !dirty)}>
              {isNew ? 'Сохранить черновик' : 'Сохранить изменения'}
            </Button>
            {!isNew && (
              <Button variant={article.is_published ? 'secondary' : 'primary'} disabled={busy} onClick={togglePublish}>
                {article.is_published ? 'Снять с публикации' : 'Опубликовать'}
              </Button>
            )}
          </div>
        </form>
      </Card>

      <aside className="grid gap-4">
        <Card className="grid gap-2">
          <h2 className="text-label">Так статью увидит клиент</h2>
          <p className="text-h3">{title || 'Заголовок статьи'}</p>
          <p className="whitespace-pre-line text-body-sm text-fg-muted">{content || 'Текст статьи'}</p>
        </Card>
      </aside>

      {!isNew && article.article_type === 'troubleshooting' && (
        <div className="col-span-2">
          <DecisionTreeEditor articleId={article.id} />
        </div>
      )}
    </div>
  )
}
