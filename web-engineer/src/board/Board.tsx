// Канбан-доска тикетов (ТЗ 4.3, E-01; глоссарий «Канбан-доска»): колонки — статусы, внутри — по сроку
// SLA, «Решено» — сначала последние решённые. Фильтры SLA / категория / исполнитель — по загруженной
// выборке. Перенос карточки меняет статус (ADR 0025 п. 7): мышью или с клавиатуры (Пробел — взять,
// ←/→ — колонка, Пробел — положить, Esc — отмена); подсвечены только допустимые колонки. «Новые → В работе»
// — взять в работу, «→ Решено» — с подтверждением. Перенос оптимистичный: при ошибке карточка
// возвращается, причина — в уведомлении (конфликт взятия — ADR 0025 п. 10).
import {
  useEffect,
  useMemo,
  useState,
  type KeyboardEventHandler,
  type PointerEventHandler,
  type ReactNode,
} from 'react'
import {
  DndContext,
  KeyboardSensor,
  PointerSensor,
  pointerWithin,
  rectIntersection,
  useDraggable,
  useDroppable,
  useSensor,
  useSensors,
  type Announcements,
  type CollisionDetection,
  type DragEndEvent,
  type DragStartEvent,
  type KeyboardCoordinateGetter,
} from '@dnd-kit/core'
import {
  ApiError,
  Chip,
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
  errorText,
  formatDateTime,
  matchesSla,
  type SlaFilter,
  type Ticket,
  type TicketCategory,
  type TicketStatus,
} from '@ev-servicedesk/web-shared'
import { useEngineer } from '../repo.ts'
import { assigneeLabel } from '../text.ts'
import { ConfirmDialog } from '../ui/Notices.tsx'
import { useNotify } from '../ui/notify.ts'
import { SlaBadge } from './SlaBadge.tsx'
import { MAX_PAGES, PAGE_SIZE, allowedTargets, useBoardData, type Column } from './boardData.ts'

type AssigneeFilter = 'all' | 'mine' | 'unassigned'

const SLA_FILTERS: SlaFilter[] = ['all', 'overdue', 'due_soon', 'ok']
/** «Решено» свёрнута до 20 карточек (ADR 0025 п. 9). */
const RESOLVED_FOLDED = 20

interface PendingMove {
  ticket: Ticket
  to: TicketStatus
}

export function Board({
  version,
  selectedId,
  onSelect,
  onChanged,
}: {
  /** Меняется после действий в карточке тикета — доска перечитывает тикеты. */
  version: number
  selectedId: number | null
  onSelect: (ticketId: number) => void
  /** Тикет изменён переносом — карточка тикета перечитывает данные. */
  onChanged: () => void
}) {
  const { repo, now: clock, meId } = useEngineer()
  const notify = useNotify()
  const { columns, error, reload, fresh, seen } = useBoardData(repo, clock, version)
  const [sla, setSla] = useState<SlaFilter>('all')
  const [category, setCategory] = useState<TicketCategory | 'all'>('all')
  const [assignee, setAssignee] = useState<AssigneeFilter>('all')
  const [showAllResolved, setShowAllResolved] = useState(false)
  // Оптимистичные переносы до ответа сервера; убранные — проигранный claim (тикет ушёл к другому).
  const [moving, setMoving] = useState<ReadonlyMap<number, TicketStatus>>(new Map())
  const [hidden, setHidden] = useState<ReadonlySet<number>>(new Set())
  const [dragging, setDragging] = useState<Ticket | null>(null)
  const [confirm, setConfirm] = useState<PendingMove | null>(null)
  const now = clock()

  const all = useMemo(() => {
    const list = columns ? TICKET_STATUSES.flatMap((s) => columns[s].items) : []
    return list
      .filter((t) => !hidden.has(t.id))
      .map((t) => {
        const to = moving.get(t.id)
        if (!to) return t
        return { ...t, status: to, assigned_engineer_id: t.status === 'new' ? meId : t.assigned_engineer_id }
      })
  }, [columns, hidden, moving, meId])

  const base = all.filter(
    (t) =>
      (category === 'all' || t.category === category) &&
      (assignee === 'all' || (assignee === 'mine' ? t.assigned_engineer_id === meId : t.assigned_engineer_id == null)),
  )
  const visible = base.filter((t) => matchesSla(t, sla, now))
  const slaCount = (f: SlaFilter) => base.filter((t) => matchesSla(t, f, now)).length
  const queueSize = columns?.new.total ?? 0
  useTabTitle(queueSize)

  const move = async ({ ticket, to }: PendingMove) => {
    setMoving((m) => new Map(m).set(ticket.id, to))
    try {
      if (ticket.status === 'new') await repo.claimTicket(ticket.id)
      else await repo.updateTicketStatus(ticket.id, to)
      onChanged()
    } catch (e) {
      if (e instanceof ApiError && e.code === 'TICKET_ALREADY_CLAIMED') {
        setHidden((h) => new Set(h).add(ticket.id))
        notify(`Тикет #${ticket.id} уже взял в работу другой инженер.`)
      } else {
        notify(`Тикет #${ticket.id} не перенесён: ${errorText(e)}`, 'error')
      }
    } finally {
      setMoving((m) => {
        const next = new Map(m)
        next.delete(ticket.id)
        return next
      })
      reload()
    }
  }

  const sensors = useSensors(
    // Клик по карточке открывает её; перенос начинается после сдвига на 6 px.
    useSensor(PointerSensor, { activationConstraint: { distance: 6 } }),
    useSensor(KeyboardSensor, {
      coordinateGetter: columnKeys,
      keyboardCodes: { start: ['Space'], cancel: ['Escape'], end: ['Space', 'Enter'] },
    }),
  )

  const targets = dragging ? allowedTargets(dragging, meId) : []

  const onDragStart = ({ active }: DragStartEvent) => {
    setDragging(all.find((t) => t.id === active.id) ?? null)
  }

  const onDragEnd = ({ active, over }: DragEndEvent) => {
    setDragging(null)
    const ticket = all.find((t) => t.id === active.id)
    const to = over?.id as TicketStatus | undefined
    if (!ticket || !to || to === ticket.status || !allowedTargets(ticket, meId).includes(to)) return
    if (to === 'resolved') setConfirm({ ticket, to })
    else void move({ ticket, to })
  }

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
          <DndContext
            sensors={sensors}
            collisionDetection={collision}
            onDragStart={onDragStart}
            onDragEnd={onDragEnd}
            onDragCancel={() => setDragging(null)}
            accessibility={{ announcements: ANNOUNCEMENTS, screenReaderInstructions: { draggable: DRAG_HELP } }}
          >
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
                    target={dragging ? targets.includes(status) : null}
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
                      <li key={t.id}>
                        <TicketCard
                          ticket={t}
                          now={now}
                          meId={meId}
                          selected={t.id === selectedId}
                          fresh={fresh.has(t.id)}
                          movable={allowedTargets(t, meId).length > 0 && !moving.has(t.id)}
                          onSelect={(id) => {
                            seen(id)
                            onSelect(id)
                          }}
                        />
                      </li>
                    ))}
                  </BoardColumn>
                )
              })}
            </div>
          </DndContext>
        </>
      )}

      {confirm && (
        <ConfirmDialog
          title={`Решить тикет #${confirm.ticket.id}?`}
          confirmLabel="Решено"
          onCancel={() => setConfirm(null)}
          onConfirm={() => {
            void move(confirm)
            setConfirm(null)
          }}
        >
          Клиент увидит, что обращение решено, и не сможет писать в чат, пока тикет не вернут в работу.
        </ConfirmDialog>
      )}
    </section>
  )
}

const DRAG_HELP =
  'Чтобы перенести тикет, нажмите Пробел, выберите колонку стрелками влево и вправо и нажмите Пробел ещё раз. Esc — отмена.'

const columnName = (id: string | number | undefined) =>
  id ? `колонка «${TICKET_STATUS_LABELS[id as TicketStatus]}»` : 'вне колонок'

const ANNOUNCEMENTS: Announcements = {
  onDragStart: ({ active }) => `Тикет #${active.id} взят для переноса.`,
  onDragOver: ({ active, over }) => `Тикет #${active.id}: ${columnName(over?.id)}.`,
  onDragEnd: ({ active, over }) => `Тикет #${active.id} отпущен: ${columnName(over?.id)}.`,
  onDragCancel: ({ active }) => `Перенос тикета #${active.id} отменён.`,
}

/** Мышь — колонка под указателем; клавиатура (указателя нет) — пересечение с карточкой. */
const collision: CollisionDetection = (args) => (args.pointerCoordinates ? pointerWithin(args) : rectIntersection(args))

/** ←/→ — карточка встаёт в середину соседней колонки; ↑/↓ не двигают (порядок в колонке — по SLA). */
const columnKeys: KeyboardCoordinateGetter = (event, { context: { collisionRect, droppableRects } }) => {
  if (!collisionRect || (event.code !== 'ArrowRight' && event.code !== 'ArrowLeft')) return undefined
  event.preventDefault()
  const center = collisionRect.left + collisionRect.width / 2
  const rects = [...droppableRects.values()].sort((a, b) => a.left - b.left)
  const target =
    event.code === 'ArrowRight'
      ? rects.find((r) => r.left > center)
      : rects.filter((r) => r.left + r.width < center).at(-1)
  if (!target) return undefined
  return { x: target.left + target.width / 2 - collisionRect.width / 2, y: collisionRect.top }
}

function BoardColumn({
  status,
  count,
  source,
  target,
  footer,
  children,
}: {
  status: TicketStatus
  count: number
  source: Column
  /** Идёт перенос: true — сюда можно, false — нельзя; null — переноса нет. */
  target: boolean | null
  footer: ReactNode
  children: ReactNode
}) {
  const { setNodeRef, isOver } = useDroppable({ id: status, disabled: target === false })
  const tone =
    target === null
      ? ''
      : target
        ? isOver
          ? 'ring-2 ring-primary'
          : 'ring-2 ring-primary/40'
        : 'opacity-50'
  return (
    <section
      ref={setNodeRef}
      aria-labelledby={`col-${status}`}
      data-drop-target={target === null ? undefined : String(target)}
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
      <ul className="flex min-h-0 flex-1 flex-col gap-2 overflow-y-auto px-2 pb-2">
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

function TicketCard({
  ticket,
  now,
  meId,
  selected,
  fresh,
  movable,
  onSelect,
}: {
  ticket: Ticket
  now: Date
  meId: number
  selected: boolean
  fresh: boolean
  movable: boolean
  onSelect: (id: number) => void
}) {
  const { attributes, listeners, setNodeRef, setActivatorNodeRef, transform, isDragging } = useDraggable({
    id: ticket.id,
    disabled: !movable,
  })
  const style = transform ? { transform: `translate3d(${transform.x}px, ${transform.y}px, 0)` } : undefined
  return (
    <div
      ref={setNodeRef}
      style={style}
      onPointerDown={listeners?.onPointerDown as PointerEventHandler<HTMLDivElement> | undefined}
      className={`relative ${isDragging ? 'z-10 opacity-90 shadow-lg' : ''} ${movable ? 'cursor-grab' : ''}`}
    >
      <button
        type="button"
        aria-current={selected ? 'true' : undefined}
        aria-label={`Тикет #${ticket.id}, ${TICKET_CATEGORY_LABELS[ticket.category]}`}
        onClick={() => onSelect(ticket.id)}
        className={`grid w-full gap-2 rounded-md border bg-surface p-3 text-left shadow-sm transition-colors duration-(--duration-fast) hover:border-border-strong ${
          selected ? 'border-fg ring-2 ring-fg' : fresh ? 'border-primary ring-2 ring-primary' : 'border-border'
        }`}
      >
        <span className="flex flex-wrap items-baseline gap-x-2 pr-8">
          <span className="text-label tabular-nums">#{ticket.id}</span>
          <span className="text-body text-fg">{TICKET_CATEGORY_LABELS[ticket.category]}</span>
          {fresh && <span className="text-caption text-primary-text">Новый</span>}
        </span>
        <span className="grid gap-0.5">
          <span className="text-caption text-fg-muted">
            {ticket.vehicle_model.brand} {ticket.vehicle_model.model}
          </span>
          <span className="line-clamp-2 text-body-sm text-fg">{ticket.summary}</span>
        </span>
        <span>
          <SlaBadge ticket={ticket} now={now} />
        </span>
        <span className="flex flex-wrap items-center justify-between gap-x-2 text-caption text-fg-muted">
          <span>{formatDateTime(ticket.created_at)}</span>
          <span>{assigneeLabel(ticket.assigned_engineer_id, meId)}</span>
        </span>
      </button>
      {movable && (
        <button
          type="button"
          ref={setActivatorNodeRef}
          {...attributes}
          onKeyDown={listeners?.onKeyDown as KeyboardEventHandler<HTMLButtonElement> | undefined}
          aria-label={`Перенести тикет #${ticket.id}`}
          className="absolute top-2 right-2 grid size-7 place-items-center rounded-md text-fg-muted hover:bg-surface-subtle hover:text-fg"
        >
          <svg viewBox="0 0 16 16" className="size-4" fill="currentColor" aria-hidden="true">
            <circle cx="5.5" cy="3.5" r="1.25" />
            <circle cx="10.5" cy="3.5" r="1.25" />
            <circle cx="5.5" cy="8" r="1.25" />
            <circle cx="10.5" cy="8" r="1.25" />
            <circle cx="5.5" cy="12.5" r="1.25" />
            <circle cx="10.5" cy="12.5" r="1.25" />
          </svg>
        </button>
      )}
    </div>
  )
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
