// Лента публикаций (ТЗ 4.4): новости, акции, регламент ТО — createNotification с таргетингом по модели;
// прошивка — createFirmwareRelease (релиз + уведомление атомарно). Чтения ленты для админа в контракте v1
// нет — `listPublishedNotifications` (открытый вопрос ADR 0012).
// Тема (юзабилити-тест, U-08): поля title в контракте v1 нет — тема уходит первой строкой message, как в
// мобильном клиенте (NotificationItem.title — первая строка, body — остальное).
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
  type Notification,
  type NotificationType,
} from '@ev-servicedesk/web-shared'
import { modelName, useAdmin } from '../repo.ts'

/** Лимит message контракта — на тему и текст вместе (с переводом строки между ними). */
const MESSAGE_MAX = 500

function composeMessage(subject: string, text: string): string {
  return `${subject.trim()}\n${text.trim()}`
}

function splitMessage(message: string): { subject: string; text: string } {
  const [subject, ...rest] = message.split('\n')
  return { subject, text: rest.join('\n').trim() }
}

export function Publications() {
  const { repo, models } = useAdmin()
  const [version, setVersion] = useState(0)
  const feed = useAsync(() => Promise.all([repo.listPublishedNotifications(), repo.listFirmwareReleases()]), [repo, version])

  return (
    <div className="grid gap-6">
      {/* U-08: публикацию путали со статьёй базы знаний — что здесь, а что в «Базе знаний». */}
      <p className="rounded-md border border-border border-l-4 border-l-info-text bg-surface px-4 py-3 text-body-sm">
        Здесь — рассылка уведомлений клиентам: push и лента «Новости» в приложении. Статьи и инструкции публикуются
        в разделе <a href="#/articles">«База знаний»</a>.
      </p>
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
                    <PublishedItem notification={n} />
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
    </div>
  )
}

function PublishedItem({ notification: n }: { notification: Notification }) {
  const { models } = useAdmin()
  const { subject, text } = splitMessage(n.message)
  return (
    <Card className="grid gap-2">
      <span className="flex flex-wrap items-center gap-2 text-caption text-fg-muted">
        <Badge tone={n.type === 'firmware' ? 'warning' : n.type === 'promo' ? 'success' : 'neutral'}>
          {NOTIFICATION_TYPE_LABELS[n.type]}
        </Badge>
        <span>Аудитория: {modelName(models, n.target_vehicle_model_id)}</span>
        <span>· {formatDateTime(n.created_at)}</span>
      </span>
      <p className="text-label">{subject}</p>
      {text && <p className="whitespace-pre-line text-body-sm">{text}</p>}
    </Card>
  )
}

const NO_MISSING = { model: false, subject: false, text: false }

function PublishForm({ onPublished }: { onPublished: () => void }) {
  const { repo, models, now } = useAdmin()
  const [type, setType] = useState<NotificationType>('news')
  const [target, setTarget] = useState('')
  const [subject, setSubject] = useState('')
  const [message, setMessage] = useState('')
  const [fwVersion, setFwVersion] = useState('')
  const [releasedAt, setReleasedAt] = useState(() => toIsoDate(now()))
  const [error, setError] = useState<unknown>(null)
  const [missing, setMissing] = useState(NO_MISSING)
  const [done, setDone] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const firmware = type === 'firmware'
  const length = subject.trim() || message.trim() ? composeMessage(subject, message).length : 0
  const tooLong = length > MESSAGE_MAX
  const modelLabel = target ? modelName(models, Number(target)) : '…'

  /** U-03: после публикации — исходное состояние, иначе следующая «новость всем» уйдёт прошлой модели. */
  const reset = () => {
    setType('news')
    setTarget('')
    setSubject('')
    setMessage('')
    setFwVersion('')
    setReleasedAt(toIsoDate(now()))
  }

  const submit = async (e: FormEvent) => {
    e.preventDefault()
    setError(null)
    setDone(null)
    const check = {
      model: firmware && !target,
      subject: !firmware && !subject.trim(),
      text: !firmware && !message.trim(),
    }
    setMissing(check)
    if (check.model || check.subject || check.text || (!firmware && tooLong)) return
    setBusy(true)
    try {
      if (firmware) {
        const release = await repo.createFirmwareRelease({ vehicle_model_id: Number(target), version: fwVersion, released_at: releasedAt })
        setDone(`Релиз опубликован: ${modelLabel}, ${release.version}. Владельцы модели получат уведомление.`)
      } else {
        await repo.createNotification({
          type,
          message: composeMessage(subject, message),
          target_vehicle_model_id: target ? Number(target) : null,
        })
        setDone(
          `Уведомление «${subject.trim()}» поставлено в очередь на рассылку: ${target ? `владельцы ${modelLabel}` : 'все клиенты'}.`,
        )
      }
      reset()
      onPublished()
    } catch (err) {
      setError(err)
    } finally {
      setBusy(false)
    }
  }

  const preview = firmware
    ? { subject: `Доступна прошивка ${fwVersion.trim() || '…'} для ${modelLabel}. Запишитесь на обновление.`, text: '' }
    : { subject: subject.trim(), text: message.trim() }

  return (
    <Card>
      {/* Раунд 2 (U-03): после сброса формы сообщение о прошлой публикации скрывается при первом изменении — иначе
          казалось, что новая публикация уже ушла. */}
      <form onSubmit={submit} onChange={() => setDone(null)} className="grid gap-4" aria-labelledby="publish-title">
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
                <input
                  type="radio"
                  name="publication-type"
                  className="size-4 accent-(--ev-fg)"
                  checked={type === t}
                  onChange={() => {
                    setType(t)
                    setMissing(NO_MISSING)
                  }}
                />
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
          error={missing.model ? 'Выберите модель' : undefined}
        >
          <option value="">{firmware ? '— выберите —' : 'Все модели'}</option>
          {models.map((m) => (
            <option key={m.id} value={m.id}>
              {m.brand} {m.model}
            </option>
          ))}
        </Select>
        {firmware ? (
          <div className="grid grid-cols-2 items-start gap-3">
            {/* A7: пример — в подсказке под полем, а не в placeholder (его принимали за введённое значение). */}
            <TextField label="Версия" hint="Например: RU 2.6.0" value={fwVersion} onChange={(e) => setFwVersion(e.target.value)} />
            <TextField label="Дата выпуска" type="date" value={releasedAt} onChange={(e) => setReleasedAt(e.target.value)} />
          </div>
        ) : (
          <>
            <TextField
              label="Тема"
              aria-required="true"
              hint="Заголовок push-уведомления и записи в ленте «Новости»"
              error={missing.subject ? 'Укажите тему' : undefined}
              value={subject}
              onChange={(e) => setSubject(e.target.value)}
            />
            <TextArea
              label="Текст уведомления"
              aria-required="true"
              rows={4}
              hint={`Тема и текст: ${length} / ${MESSAGE_MAX}`}
              error={
                tooLong
                  ? `Тема и текст вместе — не длиннее ${MESSAGE_MAX} символов: ${length} / ${MESSAGE_MAX}`
                  : missing.text
                    ? 'Введите текст уведомления'
                    : undefined
              }
              value={message}
              onChange={(e) => setMessage(e.target.value)}
            />
          </>
        )}
        <div className="grid gap-2 rounded-md bg-surface-subtle p-3">
          <span className="text-caption text-fg-muted">Предпросмотр push-уведомления</span>
          <div className="grid gap-0.5 rounded-md border border-border bg-surface p-3">
            <span className="text-caption text-fg-muted">EV-ServiceDesk · {NOTIFICATION_TYPE_LABELS[type]}</span>
            <span className={`text-label ${preview.subject ? 'text-fg' : 'text-fg-muted'}`}>{preview.subject || 'Тема'}</span>
            {!firmware && (
              <span className={`whitespace-pre-line text-body-sm ${preview.text ? 'text-fg' : 'text-fg-muted'}`}>
                {preview.text || 'Текст уведомления'}
              </span>
            )}
          </div>
          {firmware && <span className="text-caption text-fg-muted">Тему уведомления о прошивке формирует система.</span>}
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
