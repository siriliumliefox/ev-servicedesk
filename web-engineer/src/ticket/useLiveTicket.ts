// Тикет и переписка «вживую» (docs/asyncapi.yaml, ADR 0025 п. 6, 10): REST-загрузка + события WebSocket.
// После каждого `ready` — догрузка сообщений с `after_id` = наибольший id из REST и перечитывание тикета;
// сообщения упорядочены и без повторов по id. Тикет ушёл к другому инженеру — `ticket.updated` с чужим
// исполнителем, закрытие `4403`, `404` при чтении, `409 TICKET_ALREADY_CLAIMED` — один путь `lose()`:
// причина выводится из последнего своего исполнителя (очередь — взял другой, вы — переназначен).
import { useCallback, useEffect, useRef, useState } from 'react'
import {
  ApiError,
  type EngineerRepository,
  type Ticket,
  type TicketDetail,
  type TicketLiveState,
  type TicketMessage,
} from '@ev-servicedesk/web-shared'

/** Почему тикет больше не ваш: взял другой (из очереди), переназначен админом, недоступен (удалён и т. п.). */
export type LostReason = 'claimed_by_other' | 'reassigned' | 'unavailable'

export interface LiveTicket {
  ticket: TicketDetail | undefined
  error: unknown
  messages: TicketMessage[]
  messagesError: unknown
  live: TicketLiveState
  lost: LostReason | null
  /** Перечитать тикет и всю переписку (ошибка, истёкшие ссылки на вложения). */
  reload: () => void
  /** Ответ действия (claim, статус) — новые данные тикета. */
  apply: (ticket: TicketDetail) => void
  /** Своё отправленное сообщение — сразу в ленту (WebSocket пришлёт его же, повтор отбросится). */
  append: (message: TicketMessage) => void
  /** Тикет больше не ваш (например, проигран claim) — только чтение. */
  lose: () => void
}

const merge = (list: TicketMessage[], incoming: TicketMessage[]) => {
  const byId = new Map(list.map((m) => [m.id, m]))
  for (const m of incoming) byId.set(m.id, m)
  return [...byId.values()].sort((a, b) => a.id - b.id)
}

const gone = (e: unknown) => e instanceof ApiError && (e.status === 404 || e.status === 403)

export function useLiveTicket(
  repo: EngineerRepository,
  ticketId: number,
  meId: number,
  version: number,
  onExternalChange: () => void,
): LiveTicket {
  const [ticket, setTicket] = useState<TicketDetail>()
  const [error, setError] = useState<unknown>(null)
  const [messages, setMessages] = useState<TicketMessage[]>([])
  const [messagesError, setMessagesError] = useState<unknown>(null)
  const [live, setLive] = useState<TicketLiveState>('connecting')
  const [lost, setLost] = useState<LostReason | null>(null)
  const [attempt, setAttempt] = useState(0)
  // Курсор догрузки — наибольший id из REST-истории, а не из кадров WebSocket (docs/asyncapi.yaml).
  const cursor = useRef(0)
  const external = useRef(onExternalChange)
  useEffect(() => {
    external.current = onExternalChange
  }, [onExternalChange])

  // Последний исполнитель, при котором тикет был виден как свой или из очереди (undefined — ещё не читали).
  const assignee = useRef<number | null | undefined>(undefined)

  const lose = useCallback(() => {
    const was = assignee.current
    setLost((current) => current ?? (was === null ? 'claimed_by_other' : was === meId ? 'reassigned' : 'unavailable'))
  }, [meId])

  /** Новые данные тикета: исполнитель сменился на чужого — тикет потерян; иначе запомнить исполнителя. */
  const track = useCallback(
    (next: Pick<Ticket, 'assigned_engineer_id'>) => {
      const after = next.assigned_engineer_id ?? null
      const foreign = after !== null && after !== meId && after !== assignee.current
      if (foreign && assignee.current !== undefined) lose()
      else assignee.current = after
    },
    [meId, lose],
  )

  const acceptTicket = useCallback(
    (t: TicketDetail) => {
      track(t)
      setTicket(t)
      setError(null)
    },
    [track],
  )
  const rejectTicket = useCallback(
    (e: unknown) => {
      if (gone(e) && assignee.current !== undefined) lose()
      else setError(e)
    },
    [lose],
  )
  const loadTicket = useCallback(
    () => repo.getTicket(ticketId).then(acceptTicket, rejectTicket),
    [repo, ticketId, acceptTicket, rejectTicket],
  )

  /** Вся история (`afterId` нет) или догрузка после `ready`. */
  const loadMessages = useCallback(
    (afterId?: number) =>
      repo.listTicketMessages(ticketId, afterId ? { after_id: afterId } : {}).then(
        (items) => {
          if (items.length) cursor.current = Math.max(cursor.current, ...items.map((m) => m.id))
          setMessages((list) => merge(afterId ? list : [], items))
          setMessagesError(null)
        },
        (e: unknown) => {
          if (!gone(e)) setMessagesError(e)
        },
      ),
    [repo, ticketId],
  )

  useEffect(() => {
    cursor.current = 0
    void loadTicket()
    void loadMessages()
  }, [loadTicket, loadMessages, version, attempt])

  useEffect(() => {
    return repo.watchTicket(ticketId, {
      onReady: () => {
        void loadMessages(cursor.current)
        void loadTicket()
      },
      onMessage: (m) => setMessages((list) => merge(list, [m])),
      onTicket: (t) => {
        track(t)
        setTicket((current) => (current ? { ...current, ...t } : current))
        external.current()
      },
      onLost: () => {
        lose()
        external.current()
      },
      onState: setLive,
    })
  }, [repo, ticketId, loadMessages, loadTicket, track, lose])

  return {
    ticket,
    error,
    messages,
    messagesError,
    live,
    lost,
    reload: useCallback(() => setAttempt((n) => n + 1), []),
    apply: useCallback(
      (t: TicketDetail) => {
        track(t)
        setTicket(t)
      },
      [track],
    ),
    append: useCallback((m: TicketMessage) => setMessages((list) => merge(list, [m])), []),
    lose,
  }
}
