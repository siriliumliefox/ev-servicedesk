// Данные канбан-доски (ADR 0025 п. 8, 9): колонка = запрос `listTickets` по статусу, не больше 5 страниц
// по 100; «Решено» — за 7 дней (`resolved_since`, контракт 1.10.0). Опрос раз в 15 с, при возврате на
// вкладку и после своих действий; пока вкладка скрыта, опроса нет. Новые тикеты очереди подсвечиваются.
import { useCallback, useEffect, useRef, useState } from 'react'
import {
  TICKET_STATUSES,
  fetchPages,
  type EngineerRepository,
  type Ticket,
  type TicketStatus,
} from '@ev-servicedesk/web-shared'

export const POLL_MS = 15_000
export const MAX_PAGES = 5
export const PAGE_SIZE = 100
export const RESOLVED_DAYS = 7

export interface Column {
  items: Ticket[]
  /** Размер всей выборки (`total_items`). */
  total: number
  /** Загружены не все тикеты колонки (больше MAX_PAGES страниц). */
  truncated: boolean
}

export type Columns = Record<TicketStatus, Column>

export async function loadColumns(repo: EngineerRepository, now: Date): Promise<Columns> {
  const since = new Date(now.getTime() - RESOLVED_DAYS * 86_400_000).toISOString()
  const entries = await Promise.all(
    TICKET_STATUSES.map(async (status) => {
      const query = status === 'resolved' ? { status, resolved_since: since } : { status }
      const column = await fetchPages((page) => repo.listTickets({ ...query, page, page_size: PAGE_SIZE }), MAX_PAGES)
      return [status, column] as const
    }),
  )
  return Object.fromEntries(entries) as Columns
}

export interface BoardData {
  columns: Columns | undefined
  error: unknown
  /** Перечитать доску (после своего действия — сразу, без ожидания опроса). */
  reload: () => void
  /** id тикетов очереди, появившихся после первой загрузки (подсветка). */
  fresh: ReadonlySet<number>
  /** Тикет просмотрен — снять подсветку. */
  seen: (ticketId: number) => void
}

export function useBoardData(repo: EngineerRepository, clock: () => Date, version: number): BoardData {
  const [columns, setColumns] = useState<Columns>()
  const [error, setError] = useState<unknown>(null)
  const [fresh, setFresh] = useState<ReadonlySet<number>>(new Set())
  const [attempt, setAttempt] = useState(0)
  const known = useRef<Set<number> | null>(null)

  const reload = useCallback(() => setAttempt((n) => n + 1), [])

  useEffect(() => {
    let cancelled = false
    loadColumns(repo, clock()).then(
      (next) => {
        if (cancelled) return
        const queue = next.new.items.map((t) => t.id)
        if (known.current === null) known.current = new Set(queue)
        else {
          const added = queue.filter((id) => !known.current!.has(id))
          added.forEach((id) => known.current!.add(id))
          if (added.length) setFresh((prev) => new Set([...prev, ...added]))
        }
        setColumns(next)
        setError(null)
      },
      (e: unknown) => !cancelled && setError(e),
    )
    return () => {
      cancelled = true
    }
  }, [repo, clock, version, attempt])

  // Опрос — только на видимой вкладке; вернулись на вкладку — перечитать сразу.
  useEffect(() => {
    let timer: ReturnType<typeof setInterval> | null = null
    const start = () => {
      timer ??= setInterval(reload, POLL_MS)
    }
    const stop = () => {
      if (timer !== null) clearInterval(timer)
      timer = null
    }
    const onVisibility = () => {
      if (document.visibilityState === 'hidden') return stop()
      reload()
      start()
    }
    if (document.visibilityState !== 'hidden') start()
    document.addEventListener('visibilitychange', onVisibility)
    return () => {
      stop()
      document.removeEventListener('visibilitychange', onVisibility)
    }
  }, [reload])

  const seen = useCallback((ticketId: number) => {
    setFresh((prev) => {
      if (!prev.has(ticketId)) return prev
      const next = new Set(prev)
      next.delete(ticketId)
      return next
    })
  }, [])

  return { columns, error, reload, fresh, seen }
}
