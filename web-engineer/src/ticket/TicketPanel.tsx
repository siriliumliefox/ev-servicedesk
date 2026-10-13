// Карточка тикета справа от доски (ТЗ раздел 9): действия (claim, смена статуса), переписка с быстрыми
// ответами из базы знаний, контекст авто клиента. Переписка и статус обновляются вживую (WebSocket,
// ADR 0025 п. 6); тикет ушёл к другому инженеру — карточка только для чтения и закрывается (п. 10).
import { useEffect, useRef, useState, type FormEvent } from 'react'
import {
  ApiError,
  Badge,
  Button,
  ErrorState,
  InlineError,
  LoadingState,
  TICKET_CATEGORY_LABELS,
  TICKET_STATUS_LABELS,
  TextArea,
  allowedTransitions,
  formatDateTime,
  type TicketDetail,
  type TicketLiveState,
  type TicketMessage,
  type TicketStatus,
} from '@ev-servicedesk/web-shared'
import { SlaBadge } from '../board/SlaBadge.tsx'
import { useEngineer } from '../repo.ts'
import { assigneeLabel } from '../text.ts'
import { Attachments } from './Attachments.tsx'
import { QuickReplies } from './QuickReplies.tsx'
import { useLiveTicket, type LostReason } from './useLiveTicket.ts'
import { VehiclePanel } from './VehiclePanel.tsx'

/** Через сколько закрывается карточка тикета, ушедшего к другому инженеру. */
export const LOST_CLOSE_MS = 5000

const LOST_TEXT: Record<LostReason, string> = {
  claimed_by_other: 'Тикет уже взял в работу другой инженер.',
  reassigned: 'Тикет переназначен другому инженеру.',
  unavailable: 'Тикет больше вам недоступен.',
}

const LIVE_TEXT: Record<TicketLiveState, string> = {
  connecting: 'Подключение…',
  live: 'Обновляется вживую',
  offline: 'Нет связи — переподключение…',
}

/** Подпись кнопки перехода в статус. */
const ACTION_LABELS: Record<TicketStatus, string> = {
  new: 'Вернуть в новые',
  in_progress: 'Вернуть в работу',
  waiting_vendor: 'Ожидает вендора',
  resolved: 'Решено',
}

const STATUS_TONES = { new: 'neutral', in_progress: 'warning', waiting_vendor: 'neutral', resolved: 'success' } as const

export function TicketPanel({
  ticketId,
  version,
  onChanged,
  onClose,
}: {
  ticketId: number
  /** Версия данных приложения: меняется после действий и в панели «Демо». */
  version: number
  /** Тикет изменился (статус, исполнитель) — доска перечитывает данные. */
  onChanged: () => void
  onClose: () => void
}) {
  const { repo, now, meId } = useEngineer()
  const live = useLiveTicket(repo, ticketId, meId, version, onChanged)
  const [busy, setBusy] = useState(false)
  const [actionError, setActionError] = useState<unknown>(null)
  const [draft, setDraft] = useState('')
  const [showReplies, setShowReplies] = useState(false)
  const headingRef = useRef<HTMLHeadingElement>(null)
  const expiredAt = useRef(0)

  // Новый тикет — фокус на заголовок карточки (клавиатура и скринридер; карточка монтируется по key).
  useEffect(() => {
    headingRef.current?.focus()
  }, [])

  useEffect(() => {
    if (!live.lost) return
    const id = setTimeout(onClose, LOST_CLOSE_MS)
    return () => clearTimeout(id)
  }, [live.lost, onClose])

  /** Действие с карточкой: проигранный claim — тикет потерян; прочий 409 — показать актуальные данные. */
  const run = async <T,>(action: () => Promise<T>, done: (result: T) => void) => {
    setBusy(true)
    setActionError(null)
    try {
      done(await action())
      onChanged()
    } catch (e) {
      if (e instanceof ApiError && e.code === 'TICKET_ALREADY_CLAIMED') {
        live.lose()
        onChanged()
      } else {
        setActionError(e)
        if (e instanceof ApiError && e.status === 409) live.reload()
      }
    } finally {
      setBusy(false)
    }
  }

  const send = (text: string) =>
    run(
      () => repo.createTicketMessage(ticketId, text),
      (message) => {
        live.append(message)
        setDraft('')
        setShowReplies(false)
      },
    )

  const act = (action: () => Promise<TicketDetail>) => run(action, live.apply)

  // Ссылки на вложения живут 15 минут: перечитать карточку, но не чаще раза в 30 с.
  const onExpired = () => {
    if (Date.now() - expiredAt.current < 30_000) return
    expiredAt.current = Date.now()
    live.reload()
  }

  const t = live.ticket
  const readOnly = live.lost !== null
  const isMine = !readOnly && t?.assigned_engineer_id === meId
  // В решённый тикет не пишет никто (409 TICKET_RESOLVED) — сначала «Вернуть в работу».
  const canReply = isMine && t?.status !== 'resolved'
  const canClaim = !readOnly && t != null && t.assigned_engineer_id == null && t.status !== 'resolved'
  const model = t?.vehicle_context?.vehicle?.vehicle_model
  const modelName = model ? `${model.brand} ${model.model}` : null

  const onSubmit = (e: FormEvent) => {
    e.preventDefault()
    if (draft.trim()) void send(draft)
  }

  return (
    <aside aria-label={`Карточка тикета #${ticketId}`} className="flex min-h-0 w-240 shrink-0 flex-col border-l border-border bg-surface">
      <header className="flex items-start justify-between gap-4 border-b border-border px-6 py-4">
        <div className="grid gap-2">
          <h2 ref={headingRef} tabIndex={-1} className="text-h2 outline-none">
            Тикет #{ticketId}
            {t ? ` · ${TICKET_CATEGORY_LABELS[t.category]}` : ''}
          </h2>
          {t && (
            <div className="flex flex-wrap items-center gap-2 text-body-sm text-fg-muted">
              <Badge tone={STATUS_TONES[t.status]}>{TICKET_STATUS_LABELS[t.status]}</Badge>
              <SlaBadge ticket={t} now={now()} />
              <span>Создан {formatDateTime(t.created_at)}</span>
              <span>· Исполнитель: {assigneeLabel(t.assigned_engineer_id, meId)}</span>
              <span className="flex items-center gap-1" aria-live="polite">
                <span
                  aria-hidden="true"
                  className={`size-2 rounded-full ${live.live === 'live' ? 'bg-status-green-solid' : 'bg-status-unknown-solid'}`}
                />
                {LIVE_TEXT[live.live]}
              </span>
            </div>
          )}
        </div>
        <Button variant="ghost" size="sm" onClick={onClose} aria-label="Закрыть карточку тикета">
          ✕
        </Button>
      </header>

      {live.lost && (
        <div role="alert" className="flex items-center justify-between gap-4 border-b border-border bg-status-yellow-bg px-6 py-3">
          <p className="text-label text-status-yellow-fg">
            {LOST_TEXT[live.lost]} Карточка доступна только для чтения и сейчас закроется.
          </p>
          <Button variant="secondary" size="sm" onClick={onClose}>
            Закрыть
          </Button>
        </div>
      )}

      {live.error ? (
        <div className="p-6">
          <ErrorState error={live.error} onRetry={live.reload} />
        </div>
      ) : !t ? (
        <LoadingState label="Загрузка тикета…" />
      ) : (
        <>
          <div className="flex flex-wrap items-center gap-2 border-b border-border px-6 py-3">
            {canClaim && (
              <Button disabled={busy} onClick={() => act(() => repo.claimTicket(ticketId))}>
                Взять в работу
              </Button>
            )}
            {isMine &&
              allowedTransitions(t.status).map((s) => (
                <Button
                  key={s}
                  variant={s === 'resolved' ? 'primary' : 'secondary'}
                  disabled={busy}
                  onClick={() => act(() => repo.updateTicketStatus(ticketId, s))}
                >
                  {ACTION_LABELS[s]}
                </Button>
              ))}
            {!canClaim && !isMine && !readOnly && (
              <p className="text-body-sm text-fg-muted">
                {t.status === 'resolved' ? 'Тикет решён.' : `Тикет ведёт ${assigneeLabel(t.assigned_engineer_id, meId)}.`} Действия
                доступны назначенному инженеру.
              </p>
            )}
            <InlineError error={actionError} />
          </div>

          <div className="grid min-h-0 flex-1 grid-cols-[minmax(0,1fr)_24rem]">
            <section aria-label="Переписка" className="flex min-h-0 flex-col border-r border-border">
              <ol className="flex min-h-0 flex-1 flex-col gap-3 overflow-y-auto px-6 py-4">
                <li className="rounded-md bg-surface-subtle p-3 text-body-sm">
                  <span className="text-label">Обращение: </span>
                  <span className="whitespace-pre-line">{t.description}</span>
                  <Attachments items={t.attachments} onExpired={onExpired} />
                </li>
                {live.messagesError ? (
                  <li>
                    <ErrorState error={live.messagesError} onRetry={live.reload} />
                  </li>
                ) : (
                  live.messages.map((m) => <Message key={m.id} message={m} meId={meId} onExpired={onExpired} />)
                )}
              </ol>

              <form onSubmit={onSubmit} className="grid gap-3 border-t border-border px-6 py-4">
                {showReplies && (
                  <QuickReplies
                    modelName={modelName}
                    disabled={!canReply || busy}
                    onInsert={(text) => {
                      setDraft((d) => (d.trim() ? `${d}\n\n${text}` : text))
                      setShowReplies(false)
                    }}
                    onSend={(text) => void send(text)}
                  />
                )}
                <TextArea
                  label="Ответ клиенту"
                  rows={3}
                  value={draft}
                  disabled={!canReply}
                  hint={replyHint(t, meId)}
                  onChange={(e) => setDraft(e.target.value)}
                />
                <div className="flex justify-between gap-2">
                  <Button
                    variant="secondary"
                    aria-expanded={showReplies}
                    disabled={!canReply}
                    onClick={() => setShowReplies((v) => !v)}
                  >
                    Быстрые ответы
                  </Button>
                  <Button type="submit" disabled={!canReply || busy || !draft.trim()}>
                    Отправить
                  </Button>
                </div>
              </form>
            </section>

            <div className="min-h-0 overflow-y-auto px-4 py-4">
              <VehiclePanel ticket={t} />
            </div>
          </div>
        </>
      )}
    </aside>
  )
}

/**
 * Почему ответ клиенту недоступен (U-02, юзабилити-тест R1). «Взять в работу» есть только у свободного
 * нерешённого тикета, поэтому у чужого и решённого подсказка не зовёт его брать — иначе ведёт в тупик.
 */
function replyHint(ticket: TicketDetail, meId: number): string | undefined {
  if (ticket.status === 'resolved') {
    return ticket.assigned_engineer_id === meId
      ? 'Тикет решён — чтобы ответить, верните его в работу'
      : 'Тикет решён — ответ недоступен'
  }
  if (ticket.assigned_engineer_id === meId) return undefined
  if (ticket.assigned_engineer_id == null) return 'Возьмите тикет в работу, чтобы ответить клиенту'
  return `Тикет ведёт ${assigneeLabel(ticket.assigned_engineer_id, meId)} — ответить может только он`
}

function Message({ message, meId, onExpired }: { message: TicketMessage; meId: number; onExpired: () => void }) {
  const fromClient = message.author.role === 'client'
  const author = fromClient ? 'Клиент' : message.author.id === meId ? 'Вы' : `Инженер #${message.author.id}`
  return (
    <li className={`flex ${fromClient ? 'justify-start' : 'justify-end'}`}>
      <div
        className={`grid max-w-[85%] gap-1 rounded-lg p-3 text-body ${
          fromClient ? 'bg-surface-subtle' : 'border border-border bg-canvas'
        }`}
      >
        <span className="text-caption text-fg-muted">
          {author} · {formatDateTime(message.created_at)}
        </span>
        <span className="whitespace-pre-line">{message.body}</span>
        <Attachments items={message.attachments} onExpired={onExpired} />
      </div>
    </li>
  )
}
