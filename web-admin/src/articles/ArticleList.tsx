// База знаний: список статей с поиском и фильтрами (ТЗ 4.4). Админ видит и черновики.
import { useState } from 'react'
import {
  ARTICLE_TYPE_LABELS,
  Badge,
  Button,
  Card,
  Chip,
  EmptyState,
  ErrorState,
  LoadingState,
  TextField,
  useAsync,
  type ArticleType,
} from '@ev-servicedesk/web-shared'
import { modelName, useAdmin } from '../repo.ts'

type PublishFilter = 'all' | 'published' | 'draft'

export function ArticleList({ onOpen, onCreate }: { onOpen: (id: number) => void; onCreate: () => void }) {
  const { repo, models } = useAdmin()
  const [search, setSearch] = useState('')
  const [type, setType] = useState<ArticleType | 'all'>('all')
  const [publish, setPublish] = useState<PublishFilter>('all')
  const data = useAsync(
    () =>
      repo.listKnowledgeArticles({
        ...(search.trim() ? { search: search.trim() } : {}),
        ...(type === 'all' ? {} : { article_type: type }),
      }),
    [repo, search, type],
  )
  const items = (data.data?.items ?? []).filter(
    (a) => publish === 'all' || (publish === 'published' ? a.is_published : !a.is_published),
  )

  return (
    <div className="grid gap-4">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <TextField
          label="Поиск по статьям"
          type="search"
          className="w-96"
          placeholder="Заголовок или текст"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
        />
        <Button onClick={onCreate}>Новая статья</Button>
      </div>
      <div className="flex flex-wrap items-center gap-x-6 gap-y-2">
        <div role="group" aria-label="Тип статьи" className="flex items-center gap-2">
          <span className="text-label text-fg-muted">Тип</span>
          {(['all', 'guide', 'troubleshooting'] as const).map((t) => (
            <Chip key={t} selected={type === t} onClick={() => setType(t)}>
              {t === 'all' ? 'Все' : ARTICLE_TYPE_LABELS[t]}
            </Chip>
          ))}
        </div>
        <div role="group" aria-label="Статус публикации" className="flex items-center gap-2">
          <span className="text-label text-fg-muted">Статус</span>
          {(
            [
              ['all', 'Все'],
              ['published', 'Опубликованы'],
              ['draft', 'Черновики'],
            ] as const
          ).map(([value, label]) => (
            <Chip key={value} selected={publish === value} onClick={() => setPublish(value)}>
              {label}
            </Chip>
          ))}
        </div>
      </div>

      {data.error ? (
        <ErrorState error={data.error} onRetry={data.reload} />
      ) : !data.data ? (
        <LoadingState />
      ) : items.length === 0 ? (
        <EmptyState title="Статей нет" action={<Button variant="secondary" onClick={onCreate}>Создать статью</Button>}>
          Измените фильтры или создайте первую статью.
        </EmptyState>
      ) : (
        <Card className="p-0">
          <table className="w-full text-body-sm">
            <thead className="text-left text-fg-muted">
              <tr className="border-b border-border">
                <th className="px-4 py-3 font-semibold">Заголовок</th>
                <th className="px-4 py-3 font-semibold">Тип</th>
                <th className="px-4 py-3 font-semibold">Модель</th>
                <th className="px-4 py-3 text-right font-semibold">Версия</th>
                <th className="px-4 py-3 font-semibold">Статус</th>
              </tr>
            </thead>
            <tbody>
              {items.map((a) => (
                <tr key={a.id} className="border-b border-border last:border-b-0 hover:bg-surface-subtle">
                  <th scope="row" className="px-4 py-3 text-left font-normal">
                    <a
                      href={`#/articles/${a.id}`}
                      onClick={(e) => {
                        e.preventDefault()
                        onOpen(a.id)
                      }}
                      className="text-label text-fg"
                    >
                      {a.title}
                    </a>
                  </th>
                  <td className="px-4 py-3">{ARTICLE_TYPE_LABELS[a.article_type]}</td>
                  <td className="px-4 py-3">{modelName(models, a.vehicle_model_id)}</td>
                  <td className="px-4 py-3 text-right tabular-nums">v{a.version}</td>
                  <td className="px-4 py-3">
                    <Badge tone={a.is_published ? 'success' : 'neutral'}>{a.is_published ? 'Опубликована' : 'Черновик'}</Badge>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </Card>
      )}
    </div>
  )
}
