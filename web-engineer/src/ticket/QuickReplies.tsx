// Быстрые ответы из базы знаний (ТЗ 4.3, ADR 0012 п. 3): поиск по опубликованным статьям
// (`listKnowledgeArticles`, search) → «Вставить» в ответ или «Отправить» клиенту сразу.
import { useState } from 'react'
import {
  ARTICLE_TYPE_LABELS,
  Badge,
  Button,
  ErrorState,
  LoadingState,
  TextField,
  useAsync,
  type KnowledgeArticle,
} from '@ev-servicedesk/web-shared'
import { useEngineer } from '../repo.ts'
import { articleMessage } from '../text.ts'

export function QuickReplies({
  modelName,
  disabled,
  onInsert,
  onSend,
}: {
  /** «Li Auto L7» — статьи этой модели выше в списке. */
  modelName: string | null
  disabled: boolean
  onInsert: (text: string) => void
  onSend: (text: string) => void
}) {
  const { repo } = useEngineer()
  const [search, setSearch] = useState('')
  const { data, error, reload } = useAsync(
    () => repo.listKnowledgeArticles(search.trim() ? { search: search.trim() } : {}),
    [repo, search],
  )

  const items = (data?.items ?? [])
    .filter((a) => a.is_published)
    .sort((a, b) => relevance(b, modelName) - relevance(a, modelName))

  return (
    <section aria-label="Быстрые ответы из базы знаний" className="grid gap-3 rounded-lg border border-border bg-surface-subtle p-3">
      <TextField
        label="Поиск в базе знаний"
        type="search"
        autoFocus
        placeholder="Например: пробки, APN, перезагрузка"
        value={search}
        onChange={(e) => setSearch(e.target.value)}
      />
      {error ? (
        <ErrorState error={error} onRetry={reload} />
      ) : !data ? (
        <LoadingState />
      ) : items.length === 0 ? (
        <p className="text-body-sm text-fg-muted">Ничего не найдено.</p>
      ) : (
        <ul className="grid max-h-72 gap-2 overflow-y-auto">
          {items.map((a) => (
            <li key={a.id} className="grid gap-2 rounded-md border border-border bg-surface p-3">
              <span className="flex items-start justify-between gap-2">
                <span className="text-label">{a.title}</span>
                <Badge>{ARTICLE_TYPE_LABELS[a.article_type]}</Badge>
              </span>
              <span className="line-clamp-2 text-body-sm text-fg-muted">{a.content}</span>
              <span className="flex gap-2">
                <Button
                  size="sm"
                  disabled={disabled}
                  aria-label={`Отправить клиенту: ${a.title}`}
                  onClick={() => onSend(articleMessage(a))}
                >
                  Отправить
                </Button>
                <Button
                  size="sm"
                  variant="secondary"
                  disabled={disabled}
                  aria-label={`Вставить в ответ: ${a.title}`}
                  onClick={() => onInsert(articleMessage(a))}
                >
                  Вставить в ответ
                </Button>
              </span>
            </li>
          ))}
        </ul>
      )}
    </section>
  )
}

function relevance(article: KnowledgeArticle, modelName: string | null): number {
  return modelName && article.title.includes(modelName) ? 1 : 0
}
