// История версий статьи (ADR 0018 п. 1, ADR 0026 п. 9; глоссарий «Версия статьи»): опубликованные редакции,
// новые — первыми; открытая версия — только для чтения (текст и число шагов дерева на момент публикации).
import { useState } from 'react'
import { Button, Card, ErrorState, LoadingState, formatDateTime, useAsync, type KnowledgeArticle } from '@ev-servicedesk/web-shared'
import { useAdmin } from '../repo.ts'

export function Revisions({ article }: { article: KnowledgeArticle }) {
  const { repo } = useAdmin()
  const list = useAsync(() => repo.listKnowledgeArticleRevisions(article.id), [repo, article.id, article.version, article.is_published])
  const [open, setOpen] = useState<number | null>(null)
  const revision = useAsync(
    () => (open === null ? Promise.resolve(null) : repo.getKnowledgeArticleRevision(article.id, open)),
    [repo, article.id, open],
  )

  return (
    <Card className="grid gap-2">
      <h2 className="text-label">История версий</h2>
      {list.error ? (
        <ErrorState error={list.error} onRetry={list.reload} />
      ) : !list.data ? (
        <LoadingState />
      ) : list.data.length === 0 ? (
        <p className="text-body-sm text-fg-muted">Статья ещё не публиковалась — версий нет.</p>
      ) : (
        <ol className="grid gap-1 text-body-sm">
          {list.data.map((r) => (
            <li key={r.version} className="flex items-center justify-between gap-2">
              <span>
                <span className="text-label">v{r.version}</span> · {formatDateTime(r.published_at)}
                {r.version === article.version && article.is_published ? ' · действующая' : ''}
              </span>
              <Button
                size="sm"
                variant="ghost"
                aria-pressed={open === r.version}
                aria-label={`Версия ${r.version}`}
                onClick={() => setOpen(open === r.version ? null : r.version)}
              >
                {open === r.version ? 'Скрыть' : 'Открыть'}
              </Button>
            </li>
          ))}
        </ol>
      )}
      {open !== null &&
        (revision.error ? (
          <ErrorState error={revision.error} onRetry={revision.reload} />
        ) : !revision.data || revision.data.version !== open ? (
          <LoadingState />
        ) : (
          <div className="grid gap-1 rounded-md bg-surface-subtle p-3" aria-label={`Содержание версии ${revision.data.version}`}>
            <p className="text-label">{revision.data.title}</p>
            <p className="max-h-64 overflow-y-auto whitespace-pre-line text-body-sm">{revision.data.content}</p>
            {revision.data.decision_tree.length > 0 && (
              <p className="text-caption text-fg-muted">Дерево решений: шагов — {revision.data.decision_tree.length}</p>
            )}
          </div>
        ))}
    </Card>
  )
}
