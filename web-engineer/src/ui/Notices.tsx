// Уведомления о результате действий (конфликт взятия, ошибка переноса) и подтверждение необратимых
// для клиента действий («Решено»). Уведомления — в живой области: их зачитывает скринридер.
import { useCallback, useEffect, useRef, useState, type ReactNode } from 'react'
import { Button } from '@ev-servicedesk/web-shared'
import { NoticeContext, type NoticeTone as Tone } from './notify.ts'

interface Notice {
  id: number
  text: string
  tone: Tone
}

const NOTICE_MS = 6000

export function NoticeProvider({ children }: { children: ReactNode }) {
  const [notices, setNotices] = useState<Notice[]>([])
  const nextId = useRef(1)

  const notify = useCallback((text: string, tone: Tone = 'info') => {
    const id = nextId.current++
    setNotices((list) => [...list, { id, text, tone }])
    setTimeout(() => setNotices((list) => list.filter((n) => n.id !== id)), NOTICE_MS)
  }, [])

  return (
    <NoticeContext.Provider value={notify}>
      {children}
      <div aria-live="polite" role="status" className="pointer-events-none fixed right-6 bottom-6 z-50 grid w-96 gap-2">
        {notices.map((n) => (
          <p
            key={n.id}
            className={`pointer-events-auto rounded-md border px-4 py-3 text-body-sm shadow-md ${
              n.tone === 'error'
                ? 'border-danger-text bg-status-red-bg text-status-red-fg'
                : 'border-border-strong bg-surface text-fg'
            }`}
          >
            {n.text}
          </p>
        ))}
      </div>
    </NoticeContext.Provider>
  )
}

/** Модальное подтверждение (`<dialog>`): фокус внутри, Esc — отмена. */
export function ConfirmDialog({
  title,
  children,
  confirmLabel,
  onConfirm,
  onCancel,
}: {
  title: string
  children: ReactNode
  confirmLabel: string
  onConfirm: () => void
  onCancel: () => void
}) {
  const ref = useRef<HTMLDialogElement>(null)

  useEffect(() => {
    const dialog = ref.current
    if (!dialog) return
    if (typeof dialog.showModal === 'function' && !dialog.open) dialog.showModal()
    else dialog.setAttribute('open', '')
    return () => {
      if (dialog.open && typeof dialog.close === 'function') dialog.close()
    }
  }, [])

  return (
    <dialog
      ref={ref}
      aria-labelledby="confirm-title"
      onCancel={(e) => {
        e.preventDefault()
        onCancel()
      }}
      className="m-auto w-[28rem] rounded-lg border border-border bg-surface p-6 text-fg shadow-lg backdrop:bg-black/50"
    >
      <h2 id="confirm-title" className="text-h3">
        {title}
      </h2>
      <div className="mt-2 text-body-sm text-fg-muted">{children}</div>
      <div className="mt-6 flex justify-end gap-2">
        <Button variant="secondary" onClick={onCancel}>
          Отмена
        </Button>
        <Button autoFocus onClick={onConfirm}>
          {confirmLabel}
        </Button>
      </div>
    </dialog>
  )
}
