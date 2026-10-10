// Дерево решений статьи «Устранение неполадок» (ТЗ, блок 2): шаги с вариантами ответа, корень, эскалация в
// тикет; проверка на тупики перед публикацией (validateDecisionTree). Правила проверки — глава 14.
import { useState, type FormEvent } from 'react'
import {
  Badge,
  Button,
  Card,
  ErrorState,
  InlineError,
  LoadingState,
  TextArea,
  TextField,
  useAsync,
  type DecisionTreeNode,
  type DecisionTreeNodeCreateRequest,
  type DecisionTreeValidationResult,
} from '@ev-servicedesk/web-shared'
import { useAdmin } from '../repo.ts'

const PROBLEM_LABELS: Record<NonNullable<DecisionTreeValidationResult['issues'][number]['problem']>, string> = {
  DEAD_END: 'тупик: вариант никуда не ведёт, а шаг не эскалация',
  UNREACHABLE: 'шаг недостижим из корня',
  MULTIPLE_ROOTS: 'несколько корневых шагов',
  BROKEN_REFERENCE: 'вариант ссылается на удалённый шаг',
}

type Option = { label: string; next: string }

export function DecisionTreeEditor({ articleId }: { articleId: number }) {
  const { repo } = useAdmin()
  const [version, setVersion] = useState(0)
  const refresh = () => {
    setVersion((v) => v + 1)
    setResult(null)
  }
  const nodes = useAsync(() => repo.listDecisionTreeNodes(articleId), [repo, articleId, version])
  const [editing, setEditing] = useState<number | 'new' | null>(null)
  const [result, setResult] = useState<DecisionTreeValidationResult | null>(null)
  const [error, setError] = useState<unknown>(null)

  const validate = async () => {
    setError(null)
    try {
      setResult(await repo.validateDecisionTree(articleId))
    } catch (e) {
      setError(e)
    }
  }

  const remove = async (id: number) => {
    setError(null)
    try {
      await repo.deleteDecisionTreeNode(id)
      refresh()
    } catch (e) {
      setError(e)
    }
  }

  const list = nodes.data ?? []
  const issuesFor = (id: number) => result?.issues.filter((i) => i.node_id === id) ?? []

  return (
    <section aria-labelledby="tree-title" className="grid gap-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h2 id="tree-title" className="text-h3">
          Дерево решений
        </h2>
        <span className="flex gap-2">
          <Button variant="secondary" size="sm" onClick={validate}>
            Проверить дерево
          </Button>
          <Button size="sm" onClick={() => setEditing('new')}>
            Добавить шаг
          </Button>
        </span>
      </div>
      <InlineError error={error} />
      {result && (
        <p
          role="status"
          className={`rounded-md p-3 text-body-sm ${result.is_valid ? 'bg-status-green-bg text-status-green-fg' : 'bg-status-red-bg text-status-red-fg'}`}
        >
          {result.is_valid
            ? 'Ошибок нет — статью можно публиковать.'
            : `Найдено ошибок: ${result.issues.length}. Шаги с ошибками отмечены ниже.`}
        </p>
      )}

      {editing === 'new' && (
        <NodeForm
          articleId={articleId}
          nodes={list}
          onDone={(saved) => {
            setEditing(null)
            if (saved) refresh()
          }}
        />
      )}

      {nodes.error ? (
        <ErrorState error={nodes.error} onRetry={nodes.reload} />
      ) : !nodes.data ? (
        <LoadingState />
      ) : list.length === 0 ? (
        <p className="text-body-sm text-fg-muted">Шагов пока нет. Начните с корневого вопроса.</p>
      ) : (
        <ol className="grid grid-cols-2 gap-3">
          {list.map((n) =>
            editing === n.id ? (
              <li key={n.id} className="col-span-2">
                <NodeForm
                  articleId={articleId}
                  nodes={list}
                  node={n}
                  onDone={(saved) => {
                    setEditing(null)
                    if (saved) refresh()
                  }}
                />
              </li>
            ) : (
              <li key={n.id}>
                <Card className={`grid gap-2 ${issuesFor(n.id).length ? 'border-danger-text' : ''}`}>
                  <span className="flex flex-wrap items-center gap-2">
                    <span className="text-label tabular-nums">Шаг #{n.id}</span>
                    {n.is_root && <Badge>Корень</Badge>}
                    {n.is_escalation && <Badge tone="danger">Эскалация → тикет</Badge>}
                    {!n.is_escalation && (n.options ?? []).length === 0 && <Badge tone="success">Решено</Badge>}
                  </span>
                  <p className="text-body-sm">{n.question_text}</p>
                  {(n.options ?? []).length > 0 && (
                    <ul className="grid gap-1 text-body-sm text-fg-muted">
                      {(n.options ?? []).map((o, i) => (
                        <li key={i}>
                          «{o.label}» → {o.next_node_id === null ? 'эскалация' : `шаг #${o.next_node_id}`}
                        </li>
                      ))}
                    </ul>
                  )}
                  {issuesFor(n.id).map((i, k) => (
                    <p key={k} className="text-body-sm text-danger-text">
                      {i.problem ? PROBLEM_LABELS[i.problem] : 'ошибка'}
                    </p>
                  ))}
                  <span className="flex gap-2">
                    <Button size="sm" variant="secondary" onClick={() => setEditing(n.id)} aria-label={`Изменить шаг #${n.id}`}>
                      Изменить
                    </Button>
                    <Button size="sm" variant="ghost" onClick={() => remove(n.id)} aria-label={`Удалить шаг #${n.id}`}>
                      Удалить
                    </Button>
                  </span>
                </Card>
              </li>
            ),
          )}
        </ol>
      )}
    </section>
  )
}

function NodeForm({
  articleId,
  nodes,
  node,
  onDone,
}: {
  articleId: number
  nodes: DecisionTreeNode[]
  node?: DecisionTreeNode
  onDone: (saved: boolean) => void
}) {
  const { repo } = useAdmin()
  const [question, setQuestion] = useState(node?.question_text ?? '')
  const [isRoot, setIsRoot] = useState(node?.is_root ?? nodes.length === 0)
  const [isEscalation, setIsEscalation] = useState(node?.is_escalation ?? false)
  const [options, setOptions] = useState<Option[]>(
    (node?.options ?? []).map((o) => ({ label: o.label, next: o.next_node_id === null ? '' : String(o.next_node_id) })),
  )
  const [error, setError] = useState<unknown>(null)

  const submit = async (e: FormEvent) => {
    e.preventDefault()
    setError(null)
    const body: DecisionTreeNodeCreateRequest = {
      question_text: question,
      is_root: isRoot,
      is_escalation: isEscalation,
      options: options
        .filter((o) => o.label.trim())
        .map((o) => ({ label: o.label.trim(), next_node_id: o.next ? Number(o.next) : null })),
    }
    try {
      if (node) await repo.updateDecisionTreeNode(node.id, body)
      else await repo.createDecisionTreeNode(articleId, body)
      onDone(true)
    } catch (err) {
      setError(err)
    }
  }

  const setOption = (i: number, patch: Partial<Option>) => setOptions((list) => list.map((o, k) => (k === i ? { ...o, ...patch } : o)))

  return (
    <Card className="bg-surface-subtle">
      <form onSubmit={submit} className="grid gap-3" aria-label={node ? `Шаг #${node.id}` : 'Новый шаг'}>
        <p className="text-label">{node ? `Шаг #${node.id}` : 'Новый шаг'}</p>
        <TextArea label="Вопрос или инструкция" rows={2} value={question} onChange={(e) => setQuestion(e.target.value)} />
        <div className="flex gap-6 text-body">
          <label className="flex items-center gap-2">
            <input type="checkbox" className="size-4 accent-(--ev-fg)" checked={isRoot} onChange={(e) => setIsRoot(e.target.checked)} />
            Корневой шаг
          </label>
          <label className="flex items-center gap-2">
            <input
              type="checkbox"
              className="size-4 accent-(--ev-fg)"
              checked={isEscalation}
              onChange={(e) => setIsEscalation(e.target.checked)}
            />
            Эскалация — создать тикет
          </label>
        </div>
        <fieldset className="grid gap-2">
          <legend className="pb-1 text-label">Варианты ответа</legend>
          {options.map((o, i) => (
            <div key={i} className="flex items-end gap-2">
              <TextField label={`Вариант ${i + 1}`} className="flex-1" value={o.label} onChange={(e) => setOption(i, { label: e.target.value })} />
              <label className="flex flex-col gap-1 text-label">
                Ведёт к
                <select
                  className="h-(--size-control-web) rounded-md border border-border-strong bg-surface px-3 text-body"
                  value={o.next}
                  onChange={(e) => setOption(i, { next: e.target.value })}
                >
                  <option value="">— никуда —</option>
                  {nodes
                    .filter((n) => n.id !== node?.id)
                    .map((n) => (
                      <option key={n.id} value={n.id}>
                        Шаг #{n.id}: {n.question_text.slice(0, 40)}
                      </option>
                    ))}
                </select>
              </label>
              <Button variant="ghost" size="sm" onClick={() => setOptions((list) => list.filter((_, k) => k !== i))} aria-label={`Удалить вариант ${i + 1}`}>
                ✕
              </Button>
            </div>
          ))}
          <div>
            <Button variant="secondary" size="sm" onClick={() => setOptions((list) => [...list, { label: '', next: '' }])}>
              Добавить вариант
            </Button>
          </div>
        </fieldset>
        <InlineError error={error} />
        <div className="flex gap-2">
          <Button type="submit" size="sm">
            Сохранить шаг
          </Button>
          <Button size="sm" variant="ghost" onClick={() => onDone(false)}>
            Отмена
          </Button>
        </div>
      </form>
    </Card>
  )
}
