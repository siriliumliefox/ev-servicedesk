// Дерево решений статьи «Устранение неполадок» (ТЗ, блок 2): шаги с вариантами ответа, корень, эскалация в
// тикет; проверка на тупики перед публикацией (validateDecisionTree). Правила проверки — ADR 0018; правила
// сохранения шага — как backend (ADR 0026 п. 9): корень один, вариант ведёт к шагу этого дерева, дерево
// опубликованной статьи не меняется. U-40: шаги — по номеру в дереве и тексту вопроса, а не по id.
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
  type AsyncState,
  type DecisionTreeNode,
  type DecisionTreeNodeCreateRequest,
  type DecisionTreeValidationResult,
} from '@ev-servicedesk/web-shared'
import { useAdmin } from '../repo.ts'

const PROBLEM_LABELS: Record<NonNullable<DecisionTreeValidationResult['issues'][number]['problem']>, string> = {
  DEAD_END: 'тупик: с этого шага не дойти ни до решения, ни до обращения',
  UNREACHABLE: 'шаг недостижим из корня',
  MULTIPLE_ROOTS: 'несколько корневых шагов',
  BROKEN_REFERENCE: 'вариант ссылается на удалённый шаг',
  NO_ROOT: 'нет корневого шага',
  NO_ESCALATION: 'из дерева нельзя создать обращение — нет достижимого шага эскалации',
}

type Option = { label: string; next: string }

/** «Шаг 2» — номер по порядку создания (id растут), понятнее внутреннего id. */
function stepNumbers(nodes: DecisionTreeNode[]): Map<number, number> {
  return new Map([...nodes].sort((a, b) => a.id - b.id).map((n, i) => [n.id, i + 1]))
}

function stepTitle(numbers: Map<number, number>, nodes: DecisionTreeNode[], id: number): string {
  const node = nodes.find((n) => n.id === id)
  return node ? `Шаг ${numbers.get(id)} «${node.question_text}»` : 'удалённый шаг'
}

export function DecisionTreeEditor({
  articleId,
  published,
  nodes,
  onChanged,
}: {
  articleId: number
  /** Опубликованная статья: дерево только для просмотра и проверки. */
  published: boolean
  /** Шаги грузит редактор статьи: их число — на вкладке «Дерево решений · N шагов». */
  nodes: AsyncState<DecisionTreeNode[]>
  onChanged: () => void
}) {
  const { repo } = useAdmin()
  const refresh = () => {
    onChanged()
    setResult(null)
  }
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
  const numbers = stepNumbers(list)
  const issuesFor = (id: number) => result?.issues.filter((i) => i.node_id === id) ?? []

  return (
    <section aria-labelledby="tree-title" className="grid gap-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="grid gap-1">
          <h2 id="tree-title" className="text-h3">
            Дерево решений
          </h2>
          <p className="text-body-sm text-fg-muted">
            Вопросы и варианты ответа, которые клиент проходит в приложении («Поддержка» → «Неполадки»). Шаг-эскалация
            предлагает клиенту создать обращение.
          </p>
        </div>
        <span className="flex gap-2">
          <Button variant="secondary" size="sm" onClick={validate}>
            Проверить дерево
          </Button>
          {!published && (
            <Button size="sm" onClick={() => setEditing('new')}>
              Добавить шаг
            </Button>
          )}
        </span>
      </div>
      {published ? (
        <p className="rounded-md bg-surface-subtle p-3 text-body-sm">
          Дерево опубликованной статьи не меняется. Чтобы изменить шаги, снимите статью с публикации на вкладке «Текст
          статьи»: пока она снята, клиенты её не видят.
        </p>
      ) : (
        <p className="text-caption text-fg-muted">
          Вариант ответа ведёт к существующему шагу: сначала создайте шаги-итоги («Решено», эскалация), затем вопросы, которые
          к ним ведут.
        </p>
      )}
      <InlineError error={error} />
      {result && (
        <p
          role="status"
          className={`rounded-md p-3 text-body-sm ${result.is_valid ? 'bg-status-green-bg text-status-green-fg' : 'bg-status-red-bg text-status-red-fg'}`}
        >
          {result.is_valid
            ? published
              ? 'Ошибок нет.'
              : 'Ошибок нет — статью можно публиковать.'
            : `Найдено ошибок: ${result.issues.length}. Шаги с ошибками отмечены ниже.`}
          {/* Проблемы дерева целиком (без node_id): нет корня, нет достижимой эскалации. */}
          {result.issues
            .filter((i) => i.node_id === undefined && i.problem)
            .map((i) => (
              <span key={i.problem} className="block">
                {PROBLEM_LABELS[i.problem!]}
              </span>
            ))}
        </p>
      )}

      {editing === 'new' && (
        <NodeForm
          articleId={articleId}
          nodes={list}
          numbers={numbers}
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
                  numbers={numbers}
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
                    <span className="text-label tabular-nums">Шаг {numbers.get(n.id)}</span>
                    {n.is_root && <Badge>Корень</Badge>}
                    {n.is_escalation && <Badge tone="danger">Эскалация → тикет</Badge>}
                    {!n.is_escalation && (n.options ?? []).length === 0 && <Badge tone="success">Решено</Badge>}
                  </span>
                  <p className="text-body-sm">{n.question_text}</p>
                  {(n.options ?? []).length > 0 && (
                    <ul className="grid gap-1 text-body-sm text-fg-muted">
                      {(n.options ?? []).map((o, i) => (
                        <li key={i}>
                          «{o.label}» → {o.next_node_id == null ? 'никуда' : stepTitle(numbers, list, o.next_node_id)}
                        </li>
                      ))}
                    </ul>
                  )}
                  {issuesFor(n.id).map((i, k) => (
                    <p key={k} className="text-body-sm text-danger-text">
                      {i.problem ? PROBLEM_LABELS[i.problem] : 'ошибка'}
                    </p>
                  ))}
                  {!published && (
                    <span className="flex gap-2">
                      <Button size="sm" variant="secondary" onClick={() => setEditing(n.id)} aria-label={`Изменить шаг ${numbers.get(n.id)}`}>
                        Изменить
                      </Button>
                      <Button size="sm" variant="ghost" onClick={() => remove(n.id)} aria-label={`Удалить шаг ${numbers.get(n.id)}`}>
                        Удалить
                      </Button>
                    </span>
                  )}
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
  numbers,
  node,
  onDone,
}: {
  articleId: number
  nodes: DecisionTreeNode[]
  numbers: Map<number, number>
  node?: DecisionTreeNode
  onDone: (saved: boolean) => void
}) {
  const { repo } = useAdmin()
  const [question, setQuestion] = useState(node?.question_text ?? '')
  const otherRoot = nodes.find((n) => n.is_root && n.id !== node?.id)
  const [isRoot, setIsRoot] = useState(node?.is_root ?? !otherRoot)
  const [isEscalation, setIsEscalation] = useState(node?.is_escalation ?? false)
  const [options, setOptions] = useState<Option[]>(
    (node?.options ?? []).map((o) => ({ label: o.label, next: o.next_node_id === null ? '' : String(o.next_node_id) })),
  )
  const [error, setError] = useState<unknown>(null)
  const [noTarget, setNoTarget] = useState<string | null>(null)

  const submit = async (e: FormEvent) => {
    e.preventDefault()
    setError(null)
    // Вариант без перехода backend отклоняет (INVALID_NEXT_NODE) — подсказываем до запроса.
    const loose = options.find((o) => o.label.trim() && !o.next)
    setNoTarget(loose ? `Выберите, к какому шагу ведёт вариант «${loose.label.trim()}»` : null)
    if (loose) return
    const body: DecisionTreeNodeCreateRequest = {
      question_text: question,
      is_root: isRoot,
      is_escalation: isEscalation,
      options: options
        .filter((o) => o.label.trim())
        .map((o) => ({ label: o.label.trim(), next_node_id: Number(o.next) })),
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
      <form onSubmit={submit} className="grid gap-3" aria-label={node ? `Шаг ${numbers.get(node.id)}` : 'Новый шаг'}>
        <p className="text-label">{node ? `Шаг ${numbers.get(node.id)}` : 'Новый шаг'}</p>
        <TextArea label="Вопрос или инструкция" rows={2} value={question} onChange={(e) => setQuestion(e.target.value)} />
        <div className="flex gap-6 text-body">
          <label className="flex items-center gap-2">
            <input
              type="checkbox"
              className="size-4 accent-(--ev-fg)"
              checked={isRoot}
              disabled={!!otherRoot && !isRoot}
              onChange={(e) => setIsRoot(e.target.checked)}
            />
            Корневой шаг{otherRoot && !isRoot ? ` (уже есть: шаг ${numbers.get(otherRoot.id)})` : ''}
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
              <label className="flex max-w-80 flex-col gap-1 text-label">
                Ведёт к
                <select
                  className="h-(--size-control-web) rounded-md border border-border-strong bg-surface px-3 text-body"
                  value={o.next}
                  onChange={(e) => setOption(i, { next: e.target.value })}
                >
                  <option value="">— выберите шаг —</option>
                  {nodes
                    .filter((n) => n.id !== node?.id)
                    .map((n) => (
                      <option key={n.id} value={n.id}>
                        Шаг {numbers.get(n.id)}: {n.question_text}
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
        {noTarget && (
          <p role="alert" className="text-body-sm text-danger-text">
            {noTarget}
          </p>
        )}
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
