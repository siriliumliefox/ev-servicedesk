// Уведомления о результате действий (конфликт взятия, ошибка переноса) — в живой области: их зачитывает
// скринридер.
import { useCallback, useRef, useState, type ReactNode } from 'react'
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
