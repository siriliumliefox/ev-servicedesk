// Лента публикаций (ТЗ 4.4): новости, акции, регламент ТО — createNotification с таргетингом по модели;
// прошивка — createFirmwareRelease (релиз + уведомление атомарно). Чтения ленты для админа в контракте v1
// нет — `listPublishedNotifications` (открытый вопрос ADR 0012).
import { useState, type FormEvent } from 'react'
import {
  Badge,
  Button,
  Card,
  EmptyState,
  ErrorState,
  InlineError,
  LoadingState,
  NOTIFICATION_TYPES,
  NOTIFICATION_TYPE_LABELS,
  Select,
  TextArea,
  TextField,
  formatDate,
  formatDateTime,
  toIsoDate,
  useAsync,
  type NotificationType,
} from '@ev-servicedesk/web-shared'
import { modelName, useAdmin } from '../repo.ts'

const MESSAGE_MAX = 500

export function Publications() {
  const { repo, models } = useAdmin()
  const [version, setVersion] = useState(0)
  const feed = useAsync(() => Promise.all([repo.listPublishedNotifications(), repo.listFirmwareReleases()]), [repo, version])

  return (
    <div className="grid grid-cols-[28rem_minmax(0,1fr)] items-start gap-6">
      <PublishForm onPublished={() => setVersion((v) => v + 1)} />

      <div className="grid gap-6">
        <section aria-labelledby="feed-title" className="grid gap-3">
          <h2 id="feed-title" className="text-h3">
            Опубликовано
          </h2>
          {feed.error ? (
            <ErrorState error={feed.error} onRetry={feed.reload} />
          ) : !feed.data ? (
            <LoadingState />
          ) : feed.data[0].length === 0 ? (
            <EmptyState title="Публикаций пока нет">Новости, акции и прошивки появятся здесь после публикации.</EmptyState>
          ) : (
            <ol className="grid gap-2">
              {feed.data[0].map((n) => (
                <li key={n.id}>
                  <Card className="grid gap-2">
                    <span className="flex flex-wrap items-center gap-2 text-caption text-fg-muted">
                      <Badge tone={n.type === 'firmware' ? 'warning' : n.type === 'promo' ? 'success' : 'neutral'}>
                        {NOTIFICATION_TYPE_LABELS[n.type]}
                      </Badge>
                      <span>Аудитория: {modelName(models, n.target_vehicle_model_id)}</span>
                      <span>· {formatDateTime(n.created_at)}</span>
                    </span>
                    <p className="text-body">{n.message}</p>
                  </Card>
                </li>
              ))}
            </ol>
          )}
        </section>

        {feed.data && feed.data[1].length > 0 && (
          <section aria-labelledby="fw-title" className="grid gap-3">
            <h2 id="fw-title" className="text-h3">
              Релизы прошивок
            </h2>
            <Card className="p-0">
              <table className="w-full text-body-sm">
                <thead className="text-left text-fg-muted">
                  <tr className="border-b border-border">
                    <th className="px-4 py-3 font-semibold">Модель</th>
                    <th className="px-4 py-3 font-semibold">Версия</th>
                    <th className="px-4 py-3 font-semibold">Дата выпуска</th>
                  </tr>
                </thead>
                <tbody>
                  {feed.data[1].map((f) => (
                    <tr key={f.id} className="border-b border-border last:border-b-0">
                      <td className="px-4 py-3">{modelName(models, f.vehicle_model_id)}</td>
                      <td className="px-4 py-3 font-mono">{f.version}</td>
                      <td className="px-4 py-3">{formatDate(f.released_at)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </Card>
          </section>
        )}
      </div>
    </div>
  )
}

function PublishForm({ onPublished }: { onPublished: () => void }) {
  const { repo, models, now } = useAdmin()
  const [type, setType] = useState<NotificationType>('news')
  const [target, setTarget] = useState('')
  const [message, setMessage] = useState('')
  const [fwVersion, setFwVersion] = useState('')
  const [releasedAt, setReleasedAt] = useState(() => toIsoDate(now()))
  const [error, setError] = useState<unknown>(null)
  const [modelMissing, setModelMissing] = useState(false)
  const [done, setDone] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const firmware = type === 'firmware'

  const submit = async (e: FormEvent) => {
    e.preventDefault()
    setError(null)
    setDone(null)
    setModelMissing(firmware && !target)
    if (firmware && !target) return
    setBusy(true)
    try {
      if (firmware) {
        await repo.createFirmwareRelease({ vehicle_model_id: Number(target), version: fwVersion, released_at: releasedAt })
        setFwVersion('')
        setDone('Релиз опубликован, владельцы модели получат уведомление.')
      } else {
        await repo.createNotification({ type, message, target_vehicle_model_id: target ? Number(target) : null })
        setMessage('')
        setDone('Уведомление поставлено в очередь на рассылку.')
      }
      onPublished()
    } catch (err) {
      setError(err)
    } finally {
      setBusy(false)
    }
  }

  return (
    <Card>
      <form onSubmit={submit} className="grid gap-4" aria-labelledby="publish-title">
        <h2 id="publish-title" className="text-h3">
          Новая публикация
        </h2>
        <fieldset className="grid gap-2">
          <legend className="pb-1 text-label">Тип</legend>
          <div className="grid grid-cols-2 gap-2">
            {NOTIFICATION_TYPES.map((t) => (
              <label
                key={t}
                className={`flex h-(--size-control-web) cursor-pointer items-center gap-2 rounded-md border px-3 text-body ${
                  type === t ? 'border-fg' : 'border-border'
                }`}
              >
                <input type="radio" name="publication-type" className="size-4 accent-(--ev-fg)" checked={type === t} onChange={() => setType(t)} />
                {NOTIFICATION_TYPE_LABELS[t]}
              </label>
            ))}
          </div>
        </fieldset>
        <Select
          label={firmware ? 'Модель' : 'Аудитория'}
          hint={firmware ? 'Прошивка выпускается для одной модели' : 'Владельцы выбранной модели или все клиенты'}
          value={target}
          onChange={(e) => setTarget(e.target.value)}
          error={modelMissing ? 'Выберите модель' : undefined}
        >
          <option value="">{firmware ? '— выберите —' : 'Все модели'}</option>
          {models.map((m) => (
            <option key={m.id} value={m.id}>
              {m.brand} {m.model}
            </option>
          ))}
        </Select>
        {firmware ? (
          <div className="grid grid-cols-2 gap-3">
            <TextField label="Версия" placeholder="RU 2.5.0" value={fwVersion} onChange={(e) => setFwVersion(e.target.value)} />
            <TextField label="Дата выпуска" type="date" value={releasedAt} onChange={(e) => setReleasedAt(e.target.value)} />
          </div>
        ) : (
          <TextArea
            label="Текст уведомления"
            rows={4}
            maxLength={MESSAGE_MAX}
            hint={`${message.length} / ${MESSAGE_MAX}`}
            value={message}
            onChange={(e) => setMessage(e.target.value)}
          />
        )}
        <div className="grid gap-1 rounded-md bg-surface-subtle p-3">
          <span className="text-caption text-fg-muted">Предпросмотр push-уведомления</span>
          <span className="text-label">EV-ServiceDesk · {NOTIFICATION_TYPE_LABELS[type]}</span>
          <span className="text-body-sm">
            {firmware
              ? `Доступна прошивка ${fwVersion || '…'} для ${target ? modelName(models, Number(target)) : '…'}. Запишитесь на обновление.`
              : message || 'Текст уведомления'}
          </span>
        </div>
        <InlineError error={error} />
        {done && (
          <p role="status" className="text-body-sm text-status-green-fg">
            {done}
          </p>
        )}
        <Button type="submit" disabled={busy}>
          Опубликовать
        </Button>
      </form>
    </Card>
  )
}
