// Канбан-доска тикетов (ТЗ 4.3, E-01; глоссарий «Канбан-доска»): колонки — статусы, внутри — по сроку
// SLA, «Решено» — сначала последние решённые. Фильтры SLA / категория / исполнитель — по загруженной
// выборке. Перенос карточки меняет статус (ADR 0025 п. 7) — механика в `useMoves`: подсвечены только
// допустимые колонки, «Новые → В работе» — взять в работу, «→ Решено» — с подтверждением.
import { useEffect, useState, type ReactNode } from 'react'
import { DndContext, DragOverlay, PointerSensor, pointerWithin, useDroppable, useSensor, useSensors } from '@dnd-kit/core'
import {
  Chip,
  ConfirmDialog,
  EmptyState,
  ErrorState,
  LoadingState,
  SLA_LABELS,
  Select,
  TICKET_CATEGORIES,
  TICKET_CATEGORY_LABELS,
  TICKET_STATUSES,
  TICKET_STATUS_LABELS,
  bySlaDue,
  engineerMoves,
  errorText,
  matchesSla,
  type SlaFilter,
  type Ticket,
  type TicketCategory,
  type TicketStatus,
} from '@ev-servicedesk/web-shared'
import { useEngineer } from '../repo.ts'
import { useNotify } from '../ui/notify.ts'
import { CardOverlay, TicketCard } from './TicketCard.tsx'
import { MAX_PAGES, PAGE_SIZE, useBoardData, type Column } from './boardData.ts'
import { DRAG_HELP, useMoves } from './useMoves.ts'

type AssigneeFilter = 'all' | 'mine' | 'unassigned'

const SLA_FILTERS: SlaFilter[] = ['all', 'overdue', 'due_soon', 'ok']
/** «Решено» свёрнута до 20 карточек (ADR 0025 п. 9). */
const RESOLVED_FOLDED = 20

/** Объявления dnd-kit не нужны: перенос объявляет `useMoves` в своей живой области. */
const SILENT = { onDragStart: () => undefined, onDragOver: () => undefined, onDragEnd: () => undefined, onDragCancel: () => undefined }

export function Board({
  version,
  selectedId,
  onSelect,
}: {
  /** Меняется после действий в карточке тикета — доска перечитывает тикеты. */
  version: number
  selectedId: number | null
  onSelect: (ticketId: number) => void
}) {
  const { repo, now: clock, meId } = useEngineer()
  const notify = useNotify()
  const { columns, error, reload, fresh, seen } = useBoardData(repo, clock, version)
  const moves = useMoves({ repo, meId, notify, reload })
  const [sla, setSla] = useState<SlaFilter>('all')
  const [category, setCategory] = useState<TicketCategory | 'all'>('all')
  const [assignee, setAssignee] = useState<AssigneeFilter>('all')
  const [showAllResolved, setShowAllResolved] = useState(false)
  const now = clock()
  const { session } = moves

  const all = moves.view(columns ? TICKET_STATUSES.flatMap((s) => columns[s].items) : [])
  const base = all.filter(
    (t) =>
      (category === 'all' || t.category === category) &&
      (assignee === 'all' || (assignee === 'mine' ? t.assigned_engineer_id === meId : t.assigned_engineer_id == null)),
  )
  const visible = base.filter((t) => matchesSla(t, sla, now))
  const slaCount = (f: SlaFilter) => base.filter((t) => matchesSla(t, f, now)).length
  useTabTitle(columns?.new.total ?? 0)

  // Мышь — dnd-kit: клик по карточке открывает её, перенос начинается после сдвига на 6 px.
  const sensors = useSensors(useSensor(PointerSensor, { activationConstraint: { distance: 6 } }))
  const pointer = moves.pointer((id) => all.find((t) => t.id === id))

  return (
    <section aria-label="Канбан-доска тикетов" className="flex min-h-0 min-w-0 flex-1 flex-col gap-4 p-6">
      <div className="flex flex-wrap items-center gap-x-6 gap-y-3">
        <div role="group" aria-label="Фильтр по SLA" className="flex flex-wrap items-center gap-2">
          <span className="text-label text-fg-muted">SLA</span>
          {SLA_FILTERS.map((f) => (
            <Chip key={f} selected={sla === f} count={slaCount(f)} onClick={() => setSla(f)}>
              {f === 'all' ? 'Все' : SLA_LABELS[f]}
            </Chip>
          ))}
        </div>
        <div role="group" aria-label="Фильтр по исполнителю" className="flex flex-wrap items-center gap-2">
          <span className="text-label text-fg-muted">Исполнитель</span>
          {(
            [
              ['all', 'Все'],
              ['mine', 'Мои'],
              ['unassigned', 'Без исполнителя'],
            ] as const
          ).map(([value, label]) => (
            <Chip key={value} selected={assignee === value} onClick={() => setAssignee(value)}>
              {label}
            </Chip>
          ))}
        </div>
        <Select
          label="Категория"
          inline
          value={category}
          onChange={(e) => setCategory(e.target.value as TicketCategory | 'all')}
        >
          <option value="all">Все категории</option>
          {TICKET_CATEGORIES.map((c) => (
            <option key={c} value={c}>
              {TICKET_CATEGORY_LABELS[c]}
            </option>
          ))}
        </Select>
      </div>

      {error && !columns ? (
        <ErrorState error={error} onRetry={reload} />
      ) : !columns ? (
        <LoadingState label="Загрузка тикетов…" />
      ) : all.length === 0 ? (
        <EmptyState title="Обращений пока нет">Новые тикеты клиентов появятся в колонке «Новые».</EmptyState>
      ) : (
        <>
          {error ? (
            <p role="alert" className="text-body-sm text-danger-text">
              Доска не обновилась: {errorText(error)} Показаны данные последней загрузки.
            </p>
          ) : null}
          <DndContext sensors={sensors} collisionDetection={pointerWithin} accessibility={{ announcements: SILENT }} {...pointer}>
            <div className="grid min-h-0 flex-1 grid-cols-4 gap-3">
              {TICKET_STATUSES.map((status) => {
                const sorted = visible
                  .filter((t) => t.status === status)
                  .sort(status === 'resolved' ? byResolvedDesc : bySlaDue)
                const folded = status === 'resolved' && !showAllResolved && sorted.length > RESOLVED_FOLDED
                const shown = folded ? sorted.slice(0, RESOLVED_FOLDED) : sorted
                return (
                  <BoardColumn
                    key={status}
                    status={status}
                    count={sorted.length}
                    source={columns[status]}
                    target={session ? moves.targets.includes(status) : null}
                    over={session?.over === status}
                    footer={
                      folded ? (
                        <button
                          type="button"
                          className="w-full rounded-md py-2 text-body-sm text-fg underline"
                          onClick={() => setShowAllResolved(true)}
                        >
                          Показать все ({sorted.length})
                        </button>
                      ) : null
                    }
                  >
                    {shown.map((t) => (
                      <li key={t.id} className="min-w-0">
                        <TicketCard
                          ticket={t}
                          now={now}
                          meId={meId}
                          highlight={
                            session?.via === 'keyboard' && session.ticket.id === t.id
                              ? 'moving'
                              : t.id === selectedId
                                ? 'selected'
                                : fresh.has(t.id)
                                  ? 'fresh'
                                  : null
                          }
                          fresh={fresh.has(t.id)}
                          movable={engineerMoves(t, meId).length > 0 && !moves.isPending(t.id)}
                          onMoveKey={(e) => moves.onMoveKey(t, e)}
                          onMoveBlur={() => moves.onMoveBlur(t.id)}
                          onSelect={() => {
                            seen(t.id)
                            onSelect(t.id)
                          }}
                        />
                      </li>
                    ))}
                  </BoardColumn>
                )
              })}
            </div>
            <DragOverlay dropAnimation={null}>
              {session?.via === 'pointer' ? <CardOverlay ticket={session.ticket} now={now} meId={meId} /> : null}
            </DragOverlay>
          </DndContext>
        </>
      )}

      <p id="board-drag-help" className="sr-only">
        {DRAG_HELP}
      </p>
      <p aria-live="assertive" className="sr-only">
        {moves.announcement}
      </p>

      {moves.confirm && (
        <ConfirmDialog
          title={`Решить тикет #${moves.confirm.ticket.id}?`}
          confirmLabel="Решено"
          onCancel={moves.cancelConfirm}
          onConfirm={moves.confirmMove}
        >
          Клиент увидит, что обращение решено, и не сможет писать в чат, пока тикет не вернут в работу.
        </ConfirmDialog>
      )}
    </section>
  )
}

function BoardColumn({
  status,
  count,
  source,
  target,
  over,
  footer,
  children,
}: {
  status: TicketStatus
  count: number
  source: Column
  /** Идёт перенос: true — сюда можно, false — нельзя; null — переноса нет. */
  target: boolean | null
  /** Над колонкой переносимый тикет. */
  over: boolean
  footer: ReactNode
  children: ReactNode
}) {
  const { setNodeRef } = useDroppable({ id: status, disabled: target === false })
  const tone =
    target === null
      ? ''
      : target
        ? over
          ? 'ring-2 ring-primary'
          : 'ring-2 ring-primary/40'
        : 'opacity-50'
  return (
    <section
      ref={setNodeRef}
      aria-labelledby={`col-${status}`}
      data-drop-target={target === null ? undefined : String(target)}
      data-drop-over={over ? 'true' : undefined}
      className={`flex min-h-0 min-w-0 flex-col rounded-lg bg-surface-subtle transition-opacity ${tone}`}
    >
      <h2 id={`col-${status}`} className="flex items-center justify-between px-3 pt-3 pb-2 text-label text-fg">
        {TICKET_STATUS_LABELS[status]}
        <span className="rounded-full bg-surface px-2 text-caption tabular-nums text-fg-muted" title="Тикетов в колонке">
          {count}
          {source.total > count && count === source.items.length ? ` из ${source.total}` : ''}
        </span>
      </h2>
      {source.truncated && (
        <p className="mx-2 mb-2 rounded-md bg-status-yellow-bg px-2 py-1 text-caption text-status-yellow-fg">
          Показаны первые {MAX_PAGES * PAGE_SIZE} из {source.total}, сузьте фильтр.
        </p>
      )}
      <ul className="flex min-h-0 flex-1 flex-col gap-2 overflow-x-hidden overflow-y-auto px-2 pb-2">
        {children}
        {count === 0 && <li className="px-2 py-4 text-center text-body-sm text-fg-muted">Нет тикетов</li>}
      </ul>
      {footer && <div className="px-2 pb-2">{footer}</div>}
    </section>
  )
}

function byResolvedDesc(a: Ticket, b: Ticket): number {
  return (b.resolved_at ?? '').localeCompare(a.resolved_at ?? '')
}

/** Размер очереди в заголовке вкладки (ADR 0025 п. 8): «(3) Очередь · …». */
function useTabTitle(queue: number) {
  const base = 'EV-ServiceDesk · Кабинет инженера'
  useEffect(() => {
    document.title = queue > 0 ? `(${queue}) Очередь · ${base}` : base
    return () => {
      document.title = base
    }
  }, [queue])
}
