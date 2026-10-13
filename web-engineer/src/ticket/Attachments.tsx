// Вложения клиента — только просмотр (ADR 0025 п. 12): миниатюры фото, видео в плеере, фото во весь
// экран. Ссылки — presigned GET на 15 минут: не открылась (истекла) — карточка перечитывается (`onExpired`).
import { useState } from 'react'
import type { TicketDetail } from '@ev-servicedesk/web-shared'

type Attachment = NonNullable<TicketDetail['attachments']>[number]

export function Attachments({ items, onExpired }: { items: Attachment[] | undefined; onExpired: () => void }) {
  const [opened, setOpened] = useState<string | null>(null)
  if (!items?.length) return null
  return (
    <>
      <ul aria-label="Вложения" className="mt-2 flex flex-wrap gap-2">
        {items.map((a, i) => (
          <li key={a.file_url}>
            {a.file_type === 'video' ? (
              <video
                src={a.file_url}
                controls
                preload="metadata"
                aria-label={`Видео ${i + 1}`}
                onError={onExpired}
                className="h-28 max-w-56 rounded-md border border-border bg-canvas"
              />
            ) : (
              <button
                type="button"
                aria-label={`Открыть фото ${i + 1}`}
                onClick={() => setOpened(a.file_url)}
                className="block overflow-hidden rounded-md border border-border"
              >
                <img src={a.file_url} alt={`Фото ${i + 1}`} onError={onExpired} className="h-28 w-28 object-cover" />
              </button>
            )}
          </li>
        ))}
      </ul>
      {opened && (
        <div
          role="dialog"
          aria-modal="true"
          aria-label="Фото во весь экран"
          className="fixed inset-0 z-50 grid place-items-center bg-[rgb(0_0_0/0.8)] p-8"
          onClick={() => setOpened(null)}
          onKeyDown={(e) => {
            // Esc закрывает только фото, а не карточку тикета (слушатель Esc у окна в App).
            if (e.key !== 'Escape') return
            e.stopPropagation()
            setOpened(null)
          }}
        >
          <img src={opened} alt="Фото во весь экран" className="max-h-full max-w-full rounded-md" />
          <button
            type="button"
            autoFocus
            onClick={() => setOpened(null)}
            className="absolute top-4 right-4 rounded-md bg-surface px-3 py-1 text-label text-fg"
          >
            Закрыть
          </button>
        </div>
      )}
    </>
  )
}
