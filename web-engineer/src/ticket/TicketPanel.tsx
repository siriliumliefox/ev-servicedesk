// Карточка тикета справа от доски (ТЗ раздел 9): действия (claim, смена статуса), переписка с быстрыми
// ответами из базы знаний, контекст авто клиента.
import { useEffect, useRef, useState, type FormEvent } from 'react'
import {
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
  useAsync,
  type TicketMessage,
  type TicketStatus,
} from '@ev-servicedesk/web-shared'
import { SlaBadge } from '../board/SlaBadge.tsx'
import { useEngineer } from '../repo.ts'
import { assigneeLabel } from '../text.ts'
import { QuickReplies } from './QuickReplies.tsx'
import { VehiclePanel } from './VehiclePanel.tsx'

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
  const ticket = useAsync(() => repo.getTicket(ticketId), [repo, ticketId, version])
  const messages = useAsync(() => repo.listTicketMessages(ticketId), [repo, ticketId, version])
  const [busy, setBusy] = useState(false)
  const [actionError, setActionError] = useState<unknown>(null)
  const [draft, setDraft] = useState('')
  const [showReplies, setShowReplies] = useState(false)
  const headingRef = useRef<HTMLHeadingElement>(null)

  // Новый тикет — фокус на заголовок карточки (клавиатура и скринридер; карточка монтируется по key).
  useEffect(() => {
    headingRef.current?.focus()
  }, [])

  const run = async (action: () => Promise<unknown>, after?: () => void) => {
    setBusy(true)
    setActionError(null)
    try {
      await action()
      after?.()
      onChanged()
    } catch (e) {
      setActionError(e)
    } finally {
      setBusy(false)
    }
  }

  const send = (text: string) =>
    run(
      () => repo.createTicketMessage(ticketId, text),
      () => {
        setDraft('')
        setShowReplies(false)
      },
    )

  const t = ticket.data
  const isMine = t?.assigned_engineer_id === meId
  const canClaim = t != null && t.assigned_engineer_id == null && t.status !== 'resolved'
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
            </div>
          )}
        </div>
        <Button variant="ghost" size="sm" onClick={onClose} aria-label="Закрыть карточку тикета">
          ✕
        </Button>
      </header>

      {ticket.error ? (
        <div className="p-6">
          <ErrorState error={ticket.error} onRetry={ticket.reload} />
        </div>
      ) : !t ? (
        <LoadingState label="Загрузка тикета…" />
      ) : (
        <>
          <div className="flex flex-wrap items-center gap-2 border-b border-border px-6 py-3">
            {canClaim && (
              <Button disabled={busy} onClick={() => run(() => repo.claimTicket(ticketId))}>
                Взять в работу
              </Button>
            )}
            {isMine &&
              allowedTransitions(t.status).map((s) => (
                <Button
                  key={s}
                  variant={s === 'resolved' ? 'primary' : 'secondary'}
                  disabled={busy}
                  onClick={() => run(() => repo.updateTicketStatus(ticketId, s))}
                >
                  {ACTION_LABELS[s]}
                </Button>
              ))}
            {!canClaim && !isMine && (
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
                  {t.description}
                </li>
                {messages.error ? (
                  <li>
                    <ErrorState error={messages.error} onRetry={messages.reload} />
                  </li>
                ) : (
                  (messages.data?.items ?? []).map((m) => <Message key={m.id} message={m} meId={meId} />)
                )}
              </ol>

              <form onSubmit={onSubmit} className="grid gap-3 border-t border-border px-6 py-4">
                {showReplies && (
                  <QuickReplies
                    modelName={modelName}
                    disabled={!isMine || busy}
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
                  disabled={!isMine}
                  hint={isMine ? undefined : 'Возьмите тикет в работу, чтобы ответить клиенту'}
                  onChange={(e) => setDraft(e.target.value)}
                />
                <div className="flex justify-between gap-2">
                  <Button
                    variant="secondary"
                    aria-expanded={showReplies}
                    disabled={!isMine}
                    onClick={() => setShowReplies((v) => !v)}
                  >
                    Быстрые ответы
                  </Button>
                  <Button type="submit" disabled={!isMine || busy || !draft.trim()}>
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

function Message({ message, meId }: { message: TicketMessage; meId: number }) {
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
      </div>
    </li>
  )
}
