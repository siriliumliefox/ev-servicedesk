// Конструктор регламентов ТО (ТЗ 4.4, 5): интервалы замены агрегатов по моделям, справочник агрегатов,
// пороги «светофора» (глава 5). Изменение интервала — пересмотр (reviseMaintenanceRegulation): прошлая
// версия архивируется, а не перезаписывается.
import { useState, type FormEvent } from 'react'
import {
  Badge,
  Button,
  Card,
  Chip,
  ErrorState,
  InlineError,
  LoadingState,
  TextField,
  formatInt,
  useAsync,
  type AggregateType,
  type MaintenanceRegulation,
} from '@ev-servicedesk/web-shared'
import { useAdmin } from '../repo.ts'

/**
 * Целое из поля ввода (U-04): разряды можно разделять пробелом, как в таблице и карточке, — обычным,
 * неразрывным (U+00A0) или узким неразрывным (U+202F, так форматирует ru-RU).
 */
function parseInteger(value: string): number {
  return Number(value.replace(/[\s\u00A0\u202F]/g, ''))
}

/** «12 000 км, 12 мес.» — для подтверждения пересмотра. */
function intervals(r: MaintenanceRegulation): string {
  return [
    r.interval_km == null ? null : `${formatInt(r.interval_km)} км`,
    r.interval_months == null ? null : `${r.interval_months} мес.`,
  ]
    .filter(Boolean)
    .join(', ')
}

/** Сохранённый пересмотр: новая версия и прежняя (ушла в историю). */
type Revision = { name: string; before: MaintenanceRegulation | undefined; after: MaintenanceRegulation }

export function Regulations() {
  const { repo, models } = useAdmin()
  const [modelId, setModelId] = useState(models[0]?.id ?? 0)
  const [showArchive, setShowArchive] = useState(false)
  const [revised, setRevised] = useState<Revision | null>(null)
  const [version, setVersion] = useState(0)
  const refresh = () => setVersion((v) => v + 1)
  const data = useAsync(
    () =>
      Promise.all([
        repo.listAggregateTypes(),
        repo.listMaintenanceRegulations({ vehicle_model_id: modelId, include_archived: true }),
      ]),
    [repo, modelId, version],
  )

  return (
    <div className="grid grid-cols-[minmax(0,1fr)_22rem] items-start gap-6">
      <section aria-labelledby="regs-title" className="grid gap-4">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <h2 id="regs-title" className="text-h3">
            Интервалы замены
          </h2>
          <label className="flex items-center gap-2 text-body-sm">
            <input type="checkbox" className="size-4 accent-(--ev-fg)" checked={showArchive} onChange={(e) => setShowArchive(e.target.checked)} />
            Показать историю версий
          </label>
        </div>
        <div role="group" aria-label="Модель авто" className="flex flex-wrap gap-2">
          {models.map((m) => (
            <Chip
              key={m.id}
              selected={m.id === modelId}
              onClick={() => {
                setModelId(m.id)
                setRevised(null)
              }}
            >
              {m.brand} {m.model}
            </Chip>
          ))}
        </div>

        {/* A2 (юзабилити-тест): прежнее значение — сразу в подтверждении, история версий — одной кнопкой.
            Подтверждение снимается сменой модели, архивированием и новым пересмотром — не противоречит таблице. */}
        {revised && (
          <div
            role="status"
            className="flex flex-wrap items-center justify-between gap-3 rounded-md bg-status-green-bg px-4 py-3 text-body-sm text-status-green-fg"
          >
            <span>
              Сохранено: {revised.name} — {intervals(revised.after)}{' '}
              {revised.before ? `(было ${intervals(revised.before)})` : '(раньше не отслеживался)'}
            </span>
            {revised.before && !showArchive && (
              <Button size="sm" variant="secondary" onClick={() => setShowArchive(true)}>
                Показать историю версий
              </Button>
            )}
          </div>
        )}

        {data.error ? (
          <ErrorState error={data.error} onRetry={data.reload} />
        ) : !data.data ? (
          <LoadingState />
        ) : (
          <RegulationTable
            key={modelId}
            modelId={modelId}
            types={data.data[0]}
            regulations={data.data[1]}
            showArchive={showArchive}
            onChanged={refresh}
            onRevised={setRevised}
          />
        )}
      </section>

      <div className="grid gap-6">
        <Thresholds />
        <NewAggregateType onCreated={refresh} />
      </div>
    </div>
  )
}

function RegulationTable({
  modelId,
  types,
  regulations,
  showArchive,
  onChanged,
  onRevised,
}: {
  modelId: number
  types: AggregateType[]
  regulations: MaintenanceRegulation[]
  showArchive: boolean
  onChanged: () => void
  /** null — подтверждение устарело: агрегат архивирован или открыт новый пересмотр. */
  onRevised: (revision: Revision | null) => void
}) {
  const [editing, setEditing] = useState<string | null>(null)
  return (
    <Card className="p-0">
      <table className="w-full text-body-sm">
        <thead className="text-left text-fg-muted">
          <tr className="border-b border-border">
            <th className="px-4 py-3 font-semibold">Агрегат</th>
            <th className="px-4 py-3 font-semibold">Интервал, км</th>
            <th className="px-4 py-3 font-semibold">Интервал, мес.</th>
            <th className="px-4 py-3 text-right font-semibold">Действия</th>
          </tr>
        </thead>
        <tbody>
          {types.map((type) => {
            const active = regulations.find((r) => r.aggregate_type_code === type.code && !r.is_archived)
            const history = regulations
              .filter((r) => r.aggregate_type_code === type.code && r.is_archived)
              .sort((a, b) => b.id - a.id)
            return [
              editing === type.code ? (
                <RegulationForm
                  key={type.code}
                  modelId={modelId}
                  type={type}
                  current={active}
                  onDone={(saved) => {
                    setEditing(null)
                    if (saved) {
                      onRevised({ name: type.name, before: active, after: saved })
                      onChanged()
                    }
                  }}
                />
              ) : (
                <RegulationRow
                  key={type.code}
                  type={type}
                  regulation={active}
                  onEdit={() => {
                    setEditing(type.code)
                    onRevised(null)
                  }}
                  onChanged={() => {
                    onRevised(null)
                    onChanged()
                  }}
                />
              ),
              ...(showArchive
                ? history.map((r) => (
                    <tr key={`h-${r.id}`} className="border-b border-border text-fg-muted">
                      <td className="py-2 pr-4 pl-8">версия #{r.id} · в архиве</td>
                      <td className="px-4 py-2 tabular-nums">{r.interval_km == null ? '—' : formatInt(r.interval_km)}</td>
                      <td className="px-4 py-2 tabular-nums">{r.interval_months ?? '—'}</td>
                      <td />
                    </tr>
                  ))
                : []),
            ]
          })}
        </tbody>
      </table>
    </Card>
  )
}

function RegulationRow({
  type,
  regulation,
  onEdit,
  onChanged,
}: {
  type: AggregateType
  regulation: MaintenanceRegulation | undefined
  onEdit: () => void
  onChanged: () => void
}) {
  const { repo } = useAdmin()
  const [confirm, setConfirm] = useState(false)
  const [error, setError] = useState<unknown>(null)

  const archive = async () => {
    try {
      await repo.archiveMaintenanceRegulation(regulation!.id)
      onChanged()
    } catch (e) {
      setError(e)
    }
  }

  return (
    <tr className="border-b border-border">
      <th scope="row" className="px-4 py-3 text-left font-semibold">
        {type.name}
      </th>
      {regulation ? (
        <>
          <td className="px-4 py-3 tabular-nums">{regulation.interval_km == null ? '—' : formatInt(regulation.interval_km)}</td>
          <td className="px-4 py-3 tabular-nums">{regulation.interval_months ?? '—'}</td>
        </>
      ) : (
        <td colSpan={2} className="px-4 py-3">
          <Badge>Не отслеживается</Badge>
        </td>
      )}
      <td className="px-4 py-3">
        <span className="flex justify-end gap-2">
          <InlineError error={error} />
          {confirm ? (
            <>
              <Button size="sm" variant="danger" onClick={archive}>
                Да, архивировать
              </Button>
              <Button size="sm" variant="ghost" onClick={() => setConfirm(false)}>
                Отмена
              </Button>
            </>
          ) : (
            <>
              <Button size="sm" variant="secondary" onClick={onEdit} aria-label={`${regulation ? 'Изменить' : 'Добавить'} интервал: ${type.name}`}>
                {regulation ? 'Изменить' : 'Добавить'}
              </Button>
              {regulation && (
                <Button size="sm" variant="ghost" onClick={() => setConfirm(true)} aria-label={`Архивировать регламент: ${type.name}`}>
                  Архивировать
                </Button>
              )}
            </>
          )}
        </span>
      </td>
    </tr>
  )
}

function RegulationForm({
  modelId,
  type,
  current,
  onDone,
}: {
  modelId: number
  type: AggregateType
  current: MaintenanceRegulation | undefined
  /** Новая версия регламента или null — отмена. */
  onDone: (saved: MaintenanceRegulation | null) => void
}) {
  const { repo } = useAdmin()
  const [km, setKm] = useState(current?.interval_km?.toString() ?? '')
  const [months, setMonths] = useState(current?.interval_months?.toString() ?? '')
  const [error, setError] = useState<unknown>(null)
  const [busy, setBusy] = useState(false)

  const submit = async (e: FormEvent) => {
    e.preventDefault()
    setBusy(true)
    setError(null)
    try {
      const saved = await repo.reviseMaintenanceRegulation({
        vehicle_model_id: modelId,
        aggregate_type_code: type.code,
        interval_km: km.trim() ? parseInteger(km) : null,
        interval_months: months.trim() ? parseInteger(months) : null,
      })
      onDone(saved)
    } catch (err) {
      setError(err)
      setBusy(false)
    }
  }

  return (
    <tr className="border-b border-border bg-surface-subtle">
      <td colSpan={4} className="px-4 py-3">
        <form onSubmit={submit} className="grid gap-3" aria-label={`Интервал: ${type.name}`}>
          <p className="text-label">{type.name}</p>
          <div className="flex flex-wrap items-start gap-4">
            <TextField label="Интервал, км" inputMode="numeric" className="w-44" value={km} onChange={(e) => setKm(e.target.value)} />
            <TextField
              label="Интервал, мес."
              inputMode="numeric"
              className="w-44"
              value={months}
              onChange={(e) => setMonths(e.target.value)}
            />
            <p className="max-w-xs pt-7 text-caption text-fg-muted">
              Нужен хотя бы один интервал. {current ? 'Текущая версия уйдёт в историю — расчёты по прошлым ТО не изменятся.' : ''}
            </p>
          </div>
          <InlineError error={error} />
          <div className="flex gap-2">
            <Button type="submit" size="sm" disabled={busy}>
              Сохранить
            </Button>
            <Button size="sm" variant="ghost" onClick={() => onDone(null)}>
              Отмена
            </Button>
          </div>
        </form>
      </td>
    </tr>
  )
}

/** Пороги статусов «светофора» (глава 5, ADR 0009): общие для всех агрегатов. */
function Thresholds() {
  const { repo } = useAdmin()
  const current = useAsync(() => repo.getAggregateStatusThresholds(), [repo])
  if (current.error) return <ErrorState error={current.error} onRetry={current.reload} />
  if (!current.data) return <LoadingState />
  return <ThresholdsForm key={current.data.updated_at} initial={current.data} />
}

function ThresholdsForm({ initial }: { initial: { yellow_from_percent: number; red_above_percent: number } }) {
  const { repo } = useAdmin()
  const [yellow, setYellow] = useState(String(initial.yellow_from_percent))
  const [red, setRed] = useState(String(initial.red_above_percent))
  const [error, setError] = useState<unknown>(null)
  const [saved, setSaved] = useState(false)

  const submit = async (e: FormEvent) => {
    e.preventDefault()
    setError(null)
    setSaved(false)
    try {
      await repo.updateAggregateStatusThresholds({ yellow_from_percent: parseInteger(yellow), red_above_percent: parseInteger(red) })
      setSaved(true)
    } catch (err) {
      setError(err)
    }
  }

  return (
    <Card>
      <form onSubmit={submit} className="grid gap-3" aria-labelledby="thresholds-title">
        <h2 id="thresholds-title" className="text-h3">
          Пороги «светофора»
        </h2>
        <p className="text-body-sm text-fg-muted">% выработки интервала: зелёный — меньше «жёлтого», красный — больше «красного».</p>
        <div className="grid grid-cols-2 gap-3">
          <TextField label="Жёлтый с, %" inputMode="numeric" value={yellow} onChange={(e) => setYellow(e.target.value)} />
          <TextField label="Красный выше, %" inputMode="numeric" value={red} onChange={(e) => setRed(e.target.value)} />
        </div>
        <InlineError error={error} />
        {saved && (
          <p role="status" className="text-body-sm text-status-green-fg">
            Пороги сохранены. Статусы пересчитаются при следующем запросе.
          </p>
        )}
        <Button type="submit" size="sm">
          Сохранить пороги
        </Button>
      </form>
    </Card>
  )
}

function NewAggregateType({ onCreated }: { onCreated: () => void }) {
  const { repo } = useAdmin()
  const [code, setCode] = useState('')
  const [name, setName] = useState('')
  const [error, setError] = useState<unknown>(null)

  const submit = async (e: FormEvent) => {
    e.preventDefault()
    setError(null)
    try {
      await repo.createAggregateType({ code: code.trim(), name: name.trim() })
      setCode('')
      setName('')
      onCreated()
    } catch (err) {
      setError(err)
    }
  }

  return (
    <Card>
      <form onSubmit={submit} className="grid gap-3" aria-labelledby="new-aggregate-title">
        <h2 id="new-aggregate-title" className="text-h3">
          Новый агрегат
        </h2>
        <p className="text-body-sm text-fg-muted">Набор агрегатов на схеме расширяется без разработчика (ТЗ, блок 1).</p>
        <TextField label="Название" placeholder="Тормозная жидкость" value={name} onChange={(e) => setName(e.target.value)} />
        <TextField label="Код" placeholder="brake_fluid" hint="Латиница, цифры и «_»" value={code} onChange={(e) => setCode(e.target.value)} />
        <InlineError error={error} />
        <Button type="submit" size="sm" variant="secondary">
          Добавить агрегат
        </Button>
      </form>
    </Card>
  )
}
