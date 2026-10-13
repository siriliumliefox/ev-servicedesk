// Публикации (ТЗ 4.4; глоссарий «Публикация», «Аудитория»): новости и акции — createNotification с
// таргетингом по модели; прошивка — createFirmwareRelease (релиз + уведомление атомарно). Напоминания о ТО
// создаёт только система (ADR 0019). Перед публикацией — подтверждение с числом получателей
// (audience-preview, U-45, ADR 0026 п. 10): публикацию нельзя отменить. Лента — notifications/published со
// статистикой доставки.
// Тема (юзабилити-тест, U-08): поля title в контракте нет — тема уходит первой строкой message, как в
// мобильном клиенте (NotificationItem.title — первая строка, body — остальное).
import { useState, type FormEvent } from 'react'
import {
  Badge,
  Button,
  Card,
  Chip,
  ConfirmDialog,
  EmptyState,
  ErrorState,
  InlineError,
  LoadingState,
  NOTIFICATION_TYPE_LABELS,
  PUBLICATION_TYPES,
  Select,
  TextArea,
  TextField,
  formatDate,
  formatDateTime,
  formatInt,
  toIsoDate,
  useAsync,
  type NotificationAudiencePreview,
  type PublicationType,
  type PublishedNotification,
} from '@ev-servicedesk/web-shared'
import { modelName, useAdmin } from '../repo.ts'

/** Лимит формы — на тему и текст вместе (с переводом строки между ними): push длиннее не читается. */
const MESSAGE_MAX = 500
const FEED_PAGE = 20

function composeMessage(subject: string, text: string): string {
  return `${subject.trim()}\n${text.trim()}`
}

function splitMessage(message: string): { subject: string; text: string } {
  const [subject, ...rest] = message.split('\n')
  return { subject, text: rest.join('\n').trim() }
}

/** 1 клиент, 2 клиента, 5 клиентов. */
function plural(n: number, one: string, few: string, many: string): string {
  const mod10 = n % 10
  const mod100 = n % 100
  const word = mod10 === 1 && mod100 !== 11 ? one : mod10 >= 2 && mod10 <= 4 && (mod100 < 12 || mod100 > 14) ? few : many
  return `${formatInt(n)} ${word}`
}

export function Publications() {
  const [version, setVersion] = useState(0)
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
          <Feed version={version} />
          <FirmwareReleases version={version} />
        </div>
      </div>
    </div>
  )
}

function Feed({ version }: { version: number }) {
  const { repo, models } = useAdmin()
  const [type, setType] = useState<PublicationType | 'all'>('all')
  const [model, setModel] = useState('')
  const [page, setPage] = useState(1)
  const feed = useAsync(
    () =>
      repo.listPublishedNotifications({
        page,
        page_size: FEED_PAGE,
        ...(type === 'all' ? {} : { type }),
        ...(model ? { target_vehicle_model_id: Number(model) } : {}),
      }),
    [repo, type, model, page, version],
  )

  return (
    <section aria-labelledby="feed-title" className="grid gap-3">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <h2 id="feed-title" className="text-h3">
          Опубликовано
        </h2>
        <div className="flex flex-wrap items-center gap-2">
          <div role="group" aria-label="Тип публикации" className="flex items-center gap-2">
            {(['all', ...PUBLICATION_TYPES] as const).map((t) => (
              <Chip
                key={t}
                selected={type === t}
                onClick={() => {
                  setType(t)
                  setPage(1)
                }}
              >
                {t === 'all' ? 'Все' : NOTIFICATION_TYPE_LABELS[t]}
              </Chip>
            ))}
          </div>
          <Select
            label="Модель в ленте"
            inline
            value={model}
            onChange={(e) => {
              setModel(e.target.value)
              setPage(1)
            }}
          >
            <option value="">Любая</option>
            {models.map((m) => (
              <option key={m.id} value={m.id}>
                {m.brand} {m.model}
              </option>
            ))}
          </Select>
        </div>
      </div>
      {feed.error ? (
        <ErrorState error={feed.error} onRetry={feed.reload} />
      ) : !feed.data ? (
        <LoadingState />
      ) : feed.data.items.length === 0 ? (
        <EmptyState title="Публикаций нет">Новости, акции и прошивки появятся здесь после публикации.</EmptyState>
      ) : (
        <>
          <ol className="grid gap-2">
            {feed.data.items.map((n) => (
              <li key={n.id}>
                <PublishedItem notification={n} />
              </li>
            ))}
          </ol>
          {feed.data.meta.total_pages > 1 && (
            <nav aria-label="Страницы ленты" className="flex items-center gap-3 text-body-sm">
              <Button size="sm" variant="secondary" disabled={page <= 1} onClick={() => setPage((p) => p - 1)}>
                Новее
              </Button>
              <span>
                Страница {feed.data.meta.page} из {feed.data.meta.total_pages}
              </span>
              <Button size="sm" variant="secondary" disabled={page >= feed.data.meta.total_pages} onClick={() => setPage((p) => p + 1)}>
                Старее
              </Button>
            </nav>
          )}
        </>
      )}
    </section>
  )
}

function FirmwareReleases({ version }: { version: number }) {
  const { repo, models } = useAdmin()
  const releases = useAsync(() => repo.listFirmwareReleases(), [repo, version])
  if (!releases.data || releases.data.length === 0) return null
  const sorted = [...releases.data].sort((a, b) => b.released_at.localeCompare(a.released_at) || b.id - a.id)
  return (
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
            {sorted.map((f) => (
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
  )
}

function PublishedItem({ notification: n }: { notification: PublishedNotification }) {
  const { models } = useAdmin()
  const { subject, text } = splitMessage(n.message)
  const s = n.stats
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
      <p className="text-caption text-fg-muted">
        Получателей {formatInt(s.recipients)} · push доставлено {formatInt(s.delivered)}
        {s.failed ? `, не доставлено ${formatInt(s.failed)}` : ''} · открыли {formatInt(s.opened)} · прочитали{' '}
        {formatInt(s.read)}
      </p>
    </Card>
  )
}

const NO_MISSING = { model: false, subject: false, text: false }

/** Что подтверждает администратор: аудитория уже посчитана сервером. */
type Pending = { audience: NotificationAudiencePreview; publish: () => Promise<string> }

function PublishForm({ onPublished }: { onPublished: () => void }) {
  const { repo, models, now } = useAdmin()
  const [type, setType] = useState<PublicationType>('news')
  const [target, setTarget] = useState('')
  const [subject, setSubject] = useState('')
  const [message, setMessage] = useState('')
  const [fwVersion, setFwVersion] = useState('')
  const [releasedAt, setReleasedAt] = useState(() => toIsoDate(now()))
  const [error, setError] = useState<unknown>(null)
  const [missing, setMissing] = useState(NO_MISSING)
  const [done, setDone] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [pending, setPending] = useState<Pending | null>(null)
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

  /** Проверка формы → аудитория с сервера → подтверждение (U-45). */
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
        const body = { vehicle_model_id: Number(target), version: fwVersion, released_at: releasedAt }
        // Уведомление о прошивке создаётся вместе с релизом — для audience-preview его ещё нет. Оценка сверху —
        // владельцы модели; получат те, у кого прошивка старее (ADR 0019).
        const audience = await repo.previewNotificationAudience({ type: 'news', message: '-', target_vehicle_model_id: body.vehicle_model_id })
        setPending({
          audience,
          publish: async () => {
            const release = await repo.createFirmwareRelease(body)
            return `Релиз опубликован: ${modelLabel}, ${release.version}. Владельцы модели с более ранней прошивкой получат уведомление.`
          },
        })
      } else {
        const body = { type, message: composeMessage(subject, message), target_vehicle_model_id: target ? Number(target) : null }
        const audience = await repo.previewNotificationAudience(body)
        const who = target ? `владельцы ${modelLabel}` : 'все клиенты'
        const title = subject.trim()
        setPending({
          audience,
          publish: async () => {
            await repo.createNotification(body)
            return `Уведомление «${title}» поставлено в очередь на рассылку: ${who}.`
          },
        })
      }
    } catch (err) {
      setError(err)
    } finally {
      setBusy(false)
    }
  }

  const publish = async () => {
    if (!pending) return
    setBusy(true)
    try {
      setDone(await pending.publish())
      reset()
      onPublished()
    } catch (err) {
      setError(err)
    } finally {
      setPending(null)
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
          <div className="grid grid-cols-3 gap-2">
            {PUBLICATION_TYPES.map((t) => (
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
          <p className="text-caption text-fg-muted">Напоминания о ТО отправляет система по регламентам — вручную их не публикуют.</p>
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
          Опубликовать…
        </Button>
      </form>

      {pending && (
        <ConfirmDialog
          title={firmware ? 'Опубликовать релиз прошивки?' : 'Опубликовать уведомление?'}
          confirmLabel="Опубликовать"
          busy={busy}
          onConfirm={publish}
          onCancel={() => setPending(null)}
        >
          {firmware ? (
            <p>
              Уведомление получат не больше {plural(pending.audience.recipients, 'владельца', 'владельцев', 'владельцев')}{' '}
              {modelLabel} — те, у кого прошивка старее {fwVersion.trim() || 'новой'}.
            </p>
          ) : (
            <p>
              Получат {plural(pending.audience.recipients, 'клиент', 'клиента', 'клиентов')} (
              {plural(pending.audience.devices, 'устройство', 'устройства', 'устройств')} с push).
            </p>
          )}
          {pending.audience.recipients === 0 && <p className="text-status-yellow-fg">Получателей нет — уведомление никто не увидит.</p>}
          <p>Отменить или изменить публикацию нельзя.</p>
        </ConfirmDialog>
      )}
    </Card>
  )
}
