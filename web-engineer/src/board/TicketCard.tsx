// Карточка тикета на доске: модель авто, начало описания, SLA, исполнитель (OpenAPI 1.4.0, ADR 0012 п. 5).
// Мышью переносится копия (`CardOverlay` в DragOverlay) — оригинал на месте и не обрезается колонкой;
// с клавиатуры — кнопка «Перенести» (ADR 0025 п. 7).
import type { KeyboardEvent } from 'react'
import { useDraggable } from '@dnd-kit/core'
import { TICKET_CATEGORY_LABELS, formatDateTime, type Ticket } from '@ev-servicedesk/web-shared'
import { assigneeLabel } from '../text.ts'
import { SlaBadge } from './SlaBadge.tsx'

const CARD_CLASS = 'grid w-full min-w-0 gap-2 overflow-hidden rounded-md border bg-surface p-3 text-left shadow-sm'

function CardBody({ ticket, now, meId, fresh }: { ticket: Ticket; now: Date; meId: number; fresh: boolean }) {
  return (
    <>
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
    </>
  )
}

/** Копия карточки, которая едет за указателем. */
export function CardOverlay({ ticket, now, meId }: { ticket: Ticket; now: Date; meId: number }) {
  return (
    <div aria-hidden="true" className={`${CARD_CLASS} cursor-grabbing border-primary shadow-lg ring-2 ring-primary`}>
      <CardBody ticket={ticket} now={now} meId={meId} fresh={false} />
    </div>
  )
}

/** Как выделена карточка: переносится с клавиатуры, открыта, новая в очереди. */
type Highlight = 'moving' | 'selected' | 'fresh' | null

const HIGHLIGHT: Record<NonNullable<Highlight>, string> = {
  moving: 'border-primary ring-2 ring-primary',
  selected: 'border-fg ring-2 ring-fg',
  fresh: 'border-primary ring-2 ring-primary',
}

export function TicketCard({
  ticket,
  now,
  meId,
  highlight,
  fresh,
  movable,
  onMoveKey,
  onMoveBlur,
  onSelect,
}: {
  ticket: Ticket
  now: Date
  meId: number
  highlight: Highlight
  fresh: boolean
  movable: boolean
  onMoveKey: (e: KeyboardEvent<HTMLButtonElement>) => void
  onMoveBlur: () => void
  onSelect: () => void
}) {
  const { listeners, setNodeRef, isDragging } = useDraggable({ id: ticket.id, disabled: !movable })
  return (
    <div
      ref={setNodeRef}
      {...listeners}
      className={`relative ${isDragging ? 'opacity-40' : ''} ${movable ? 'cursor-grab' : ''}`}
    >
      <button
        type="button"
        aria-current={highlight === 'selected' ? 'true' : undefined}
        aria-label={`Тикет #${ticket.id}, ${TICKET_CATEGORY_LABELS[ticket.category]}`}
        onClick={onSelect}
        className={`${CARD_CLASS} transition-colors duration-(--duration-fast) hover:border-border-strong ${
          highlight ? HIGHLIGHT[highlight] : 'border-border'
        }`}
      >
        <CardBody ticket={ticket} now={now} meId={meId} fresh={fresh} />
      </button>
      {movable && (
        <button
          type="button"
          onKeyDown={onMoveKey}
          onBlur={onMoveBlur}
          aria-pressed={highlight === 'moving'}
          aria-describedby="board-drag-help"
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
