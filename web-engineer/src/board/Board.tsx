// Канбан-доска тикетов (ТЗ 4.3, E-01): колонки по статусу, фильтры SLA / категория / исполнитель,
// в колонке — сначала самый ранний срок SLA. Фильтрация — на клиенте по полной выборке `listTickets`
// (в прототипе — одна страница; при пагинации в главе 21 status/category/overdue уйдут в запрос).
import { useMemo, useState } from 'react'
import {
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
  formatDateTime,
  matchesSla,
  useAsync,
  type SlaFilter,
  type Ticket,
  type TicketCategory,
} from '@ev-servicedesk/web-shared'
import { useEngineer } from '../repo.ts'
import { assigneeLabel } from '../text.ts'
import { SlaBadge } from './SlaBadge.tsx'

type AssigneeFilter = 'all' | 'mine' | 'unassigned'

const SLA_FILTERS: SlaFilter[] = ['all', 'overdue', 'due_soon', 'ok']

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
  const { data, error, loading, reload } = useAsync(() => repo.listTickets(), [repo, version])
  const [sla, setSla] = useState<SlaFilter>('all')
  const [category, setCategory] = useState<TicketCategory | 'all'>('all')
  const [assignee, setAssignee] = useState<AssigneeFilter>('all')
  const now = clock()

  const base = useMemo(
    () =>
      (data?.items ?? []).filter(
        (t) =>
          (category === 'all' || t.category === category) &&
          (assignee === 'all' ||
            (assignee === 'mine' ? t.assigned_engineer_id === meId : t.assigned_engineer_id == null)),
      ),
    [data, category, assignee, meId],
  )
  const visible = base.filter((t) => matchesSla(t, sla, now))
  const slaCount = (f: SlaFilter) => base.filter((t) => matchesSla(t, f, now)).length

  return (
    <section aria-label="Канбан-доска тикетов" className="flex min-h-0 flex-1 flex-col gap-4 p-6">
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

      {error ? (
        <ErrorState error={error} onRetry={reload} />
      ) : !data && loading ? (
        <LoadingState label="Загрузка тикетов…" />
      ) : data && data.items.length === 0 ? (
        <EmptyState title="Обращений пока нет">Новые тикеты клиентов появятся в колонке «Новые».</EmptyState>
      ) : (
        <div className="grid min-h-0 flex-1 grid-cols-4 gap-3">
          {TICKET_STATUSES.map((status) => {
            const column = visible
              .filter((t) => t.status === status)
              .sort(status === 'resolved' ? byResolvedDesc : bySlaDue)
            return (
              <section
                key={status}
                aria-labelledby={`col-${status}`}
                className="flex min-h-0 min-w-0 flex-col rounded-lg bg-surface-subtle"
              >
                <h2 id={`col-${status}`} className="flex items-center justify-between px-3 pt-3 pb-2 text-label text-fg">
                  {TICKET_STATUS_LABELS[status]}
                  <span className="rounded-full bg-surface px-2 text-caption tabular-nums text-fg-muted">{column.length}</span>
                </h2>
                <ul className="flex min-h-0 flex-1 flex-col gap-2 overflow-y-auto px-2 pb-2">
                  {column.map((t) => (
                    <li key={t.id}>
                      <TicketCard ticket={t} now={now} meId={meId} selected={t.id === selectedId} onSelect={onSelect} />
                    </li>
                  ))}
                  {column.length === 0 && <li className="px-2 py-4 text-center text-body-sm text-fg-muted">Нет тикетов</li>}
                </ul>
              </section>
            )
          })}
        </div>
      )}
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
  onSelect,
}: {
  ticket: Ticket
  now: Date
  meId: number
  selected: boolean
  onSelect: (id: number) => void
}) {
  return (
    <button
      type="button"
      aria-current={selected ? 'true' : undefined}
      aria-label={`Тикет #${ticket.id}, ${TICKET_CATEGORY_LABELS[ticket.category]}`}
      onClick={() => onSelect(ticket.id)}
      className={`grid w-full gap-2 rounded-md border bg-surface p-3 text-left shadow-sm transition-colors duration-(--duration-fast) hover:border-border-strong ${
        selected ? 'border-fg ring-2 ring-fg' : 'border-border'
      }`}
    >
      <span className="flex flex-wrap items-baseline gap-x-2">
        <span className="text-label tabular-nums">#{ticket.id}</span>
        <span className="text-body text-fg">{TICKET_CATEGORY_LABELS[ticket.category]}</span>
      </span>
      <span>
        <SlaBadge ticket={ticket} now={now} />
      </span>
      <span className="flex flex-wrap items-center justify-between gap-x-2 text-caption text-fg-muted">
        <span>{formatDateTime(ticket.created_at)}</span>
        <span>{assigneeLabel(ticket.assigned_engineer_id, meId)}</span>
      </span>
    </button>
  )
}
