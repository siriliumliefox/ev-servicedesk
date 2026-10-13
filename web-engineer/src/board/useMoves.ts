// Перенос тикетов по доске (ADR 0025 п. 7, 10): одно состояние переноса для мыши (dnd-kit) и клавиатуры
// (кнопка «Перенести»), подтверждение «Решено», оптимистичный перенос с откатом и конфликт взятия.
import { useMemo, useState, type KeyboardEvent } from 'react'
import type { DragEndEvent, DragOverEvent, DragStartEvent } from '@dnd-kit/core'
import {
  ApiError,
  TICKET_STATUSES,
  TICKET_STATUS_LABELS,
  engineerMoves,
  errorText,
  type EngineerRepository,
  type Ticket,
  type TicketStatus,
} from '@ev-servicedesk/web-shared'

/** Идёт перенос: тикет, колонка под ним (или вне колонок) и чем переносят. */
export interface MoveSession {
  ticket: Ticket
  over: TicketStatus | null
  via: 'pointer' | 'keyboard'
}

export const DRAG_HELP =
  'Чтобы перенести тикет, нажмите Пробел, выберите колонку стрелками влево и вправо и нажмите Пробел ещё раз. Esc — отмена.'

export const columnName = (status: TicketStatus | null) =>
  status ? `колонка «${TICKET_STATUS_LABELS[status]}»` : 'вне колонок'

interface Options {
  repo: EngineerRepository
  meId: number
  notify: (text: string, tone?: 'info' | 'error') => void
  /** Перечитать доску после ответа сервера. */
  reload: () => void
}

export function useMoves({ repo, meId, notify, reload }: Options) {
  const [session, setSession] = useState<MoveSession | null>(null)
  const [confirm, setConfirm] = useState<{ ticket: Ticket; to: TicketStatus } | null>(null)
  // Оптимистичные переносы до ответа сервера; скрытые — проигранный claim (тикет ушёл к другому).
  const [pending, setPending] = useState<ReadonlyMap<number, TicketStatus>>(new Map())
  const [hidden, setHidden] = useState<ReadonlySet<number>>(new Set())
  const [announcement, setAnnouncement] = useState('')

  const commit = async (ticket: Ticket, to: TicketStatus) => {
    setPending((m) => new Map(m).set(ticket.id, to))
    try {
      if (ticket.status === 'new') await repo.claimTicket(ticket.id)
      else await repo.updateTicketStatus(ticket.id, to)
    } catch (e) {
      if (e instanceof ApiError && e.code === 'TICKET_ALREADY_CLAIMED') {
        setHidden((h) => new Set(h).add(ticket.id))
        notify(`Тикет #${ticket.id} уже взял в работу другой инженер.`)
      } else {
        notify(`Тикет #${ticket.id} не перенесён: ${errorText(e)}`, 'error')
      }
    } finally {
      setPending((m) => {
        const next = new Map(m)
        next.delete(ticket.id)
        return next
      })
      reload()
    }
  }

  /** Отпустили над колонкой: недопустимое — ничего, «Решено» — через подтверждение. */
  const drop = ({ ticket, over }: MoveSession) => {
    setSession(null)
    setAnnouncement(`Тикет #${ticket.id} отпущен: ${columnName(over)}.`)
    if (!over || over === ticket.status || !engineerMoves(ticket, meId).includes(over)) return
    if (over === 'resolved') setConfirm({ ticket, to: over })
    else void commit(ticket, over)
  }

  const cancel = () => {
    if (session) setAnnouncement(`Перенос тикета #${session.ticket.id} отменён.`)
    setSession(null)
  }

  /** Тикеты доски с учётом переносов в полёте и проигранных claim. */
  const view = (tickets: Ticket[]): Ticket[] =>
    tickets
      .filter((t) => !hidden.has(t.id))
      .map((t) => {
        const to = pending.get(t.id)
        return to ? { ...t, status: to, assigned_engineer_id: t.status === 'new' ? meId : t.assigned_engineer_id } : t
      })

  const pointer = (find: (id: number) => Ticket | undefined) => ({
    onDragStart: ({ active }: DragStartEvent) => {
      const ticket = find(Number(active.id))
      if (ticket) setSession({ ticket, over: ticket.status, via: 'pointer' })
    },
    onDragOver: ({ over }: DragOverEvent) =>
      setSession((s) => s && { ...s, over: (over?.id as TicketStatus | undefined) ?? null }),
    onDragEnd: ({ over }: DragEndEvent) =>
      session && drop({ ...session, over: (over?.id as TicketStatus | undefined) ?? null }),
    onDragCancel: cancel,
  })

  /**
   * Клавиатура — по номерам колонок, без геометрии (карточка шире узкой колонки — датчик клавиатуры
   * dnd-kit прокручивал бы список): Пробел/Enter — взять и положить, ←/→ — соседняя допустимая колонка.
   */
  const onMoveKey = (ticket: Ticket, e: KeyboardEvent<HTMLButtonElement>) => {
    const picking = e.key === ' ' || e.key === 'Enter'
    if (session?.ticket.id !== ticket.id) {
      if (!picking) return
      e.preventDefault()
      setSession({ ticket, over: ticket.status, via: 'keyboard' })
      setAnnouncement(`Тикет #${ticket.id} взят для переноса. ${DRAG_HELP}`)
    } else if (picking) {
      e.preventDefault()
      drop(session)
    } else if (e.key === 'Escape') {
      e.preventDefault()
      e.stopPropagation()
      cancel()
    } else if (e.key === 'ArrowRight' || e.key === 'ArrowLeft') {
      e.preventDefault()
      const allowed = [ticket.status, ...engineerMoves(ticket, meId)]
      const step = e.key === 'ArrowRight' ? 1 : -1
      const from = TICKET_STATUSES.indexOf(session.over ?? ticket.status)
      const next = TICKET_STATUSES.filter((_, i) => (step > 0 ? i > from : i < from) && allowed.includes(TICKET_STATUSES[i]))
      const over = step > 0 ? next[0] : next.at(-1)
      if (!over) return
      setSession({ ...session, over })
      setAnnouncement(`Тикет #${ticket.id}: ${columnName(over)}.`)
    }
  }

  const targets = useMemo(() => (session ? engineerMoves(session.ticket, meId) : []), [session, meId])

  return {
    session,
    targets,
    announcement,
    view,
    pointer,
    onMoveKey,
    /** Фокус ушёл с кнопки «Перенести» — перенос с клавиатуры отменяется. */
    onMoveBlur: (ticketId: number) => session?.via === 'keyboard' && session.ticket.id === ticketId && cancel(),
    isPending: (ticketId: number) => pending.has(ticketId),
    confirm,
    confirmMove: () => {
      if (confirm) void commit(confirm.ticket, confirm.to)
      setConfirm(null)
    },
    cancelConfirm: () => setConfirm(null),
  }
}
