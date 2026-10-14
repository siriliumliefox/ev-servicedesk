// Контекст авто клиента из тикета (ТЗ 4.3, ADR 0025 п. 12): модель, VIN, пробег, прошивка на момент тикета
// и текущая, статусы агрегатов, история ТО постранично. Авто и статусы приходят в TicketDetail.vehicle_context,
// история — listMaintenanceRecords. Инженер тикета фиксирует замену и работы по агрегату (E-05, глава 23,
// ADR 0027 п. 14) — после сохранения карточка тикета и история перечитываются.
import { useEffect, useState } from 'react'
import {
  Button,
  ErrorState,
  LoadingState,
  StatusBadge,
  formatDate,
  formatKm,
  type AggregateStatus,
  type MaintenanceRecord,
  type TicketDetail,
} from '@ev-servicedesk/web-shared'
import { useEngineer } from '../repo.ts'
import { MaintenanceForm, type MaintenanceTarget } from './MaintenanceForm.tsx'

const HISTORY_PAGE = 20

/** История ТО постранично: «Показать ещё» догружает следующую страницу. */
function useHistory(vehicleId: number | undefined) {
  const { repo } = useEngineer()
  const [items, setItems] = useState<MaintenanceRecord[]>()
  const [page, setPage] = useState(1)
  const [pages, setPages] = useState(1)
  const [error, setError] = useState<unknown>(null)
  const [attempt, setAttempt] = useState(0)

  useEffect(() => {
    if (vehicleId === undefined) return
    let cancelled = false
    repo.listMaintenanceRecords(vehicleId, { page, page_size: HISTORY_PAGE }).then(
      (result) => {
        if (cancelled) return
        setItems((list) => (page === 1 ? result.items : [...(list ?? []), ...result.items]))
        setPages(result.meta.total_pages)
        setError(null)
      },
      (e: unknown) => !cancelled && setError(e),
    )
    return () => {
      cancelled = true
    }
  }, [repo, vehicleId, page, attempt])

  return {
    items,
    error,
    more: page < pages ? () => setPage((p) => p + 1) : null,
    retry: () => setAttempt((n) => n + 1),
    /** С первой страницы — после новой записи. */
    reload: () => {
      setPage(1)
      setAttempt((n) => n + 1)
    },
  }
}

/** Общая работа без агрегата — отдельная форма под историей ТО. */
const OTHER_WORK: MaintenanceTarget = { code: null, name: 'другая работа' }

export function VehiclePanel({
  ticket,
  editable = false,
  onChanged,
}: {
  ticket: TicketDetail
  /** Свой нерешённый тикет — можно фиксировать замены и работы (иначе backend ответит 403). */
  editable?: boolean
  /** Данные авто изменились — перечитать карточку тикета (статусы, пробег). */
  onChanged?: () => void
}) {
  const context = ticket.vehicle_context
  const vehicle = context?.vehicle
  const records = useHistory(vehicle?.id)
  const [form, setForm] = useState<MaintenanceTarget | null>(null)
  const [saved, setSaved] = useState('')

  if (!vehicle) return <p className="text-body-sm text-fg-muted">Авто не привязано к обращению.</p>

  const names = new Map((context.aggregate_statuses ?? []).map((s) => [s.aggregate_type_code, s.aggregate_type_name]))
  const model = vehicle.vehicle_model
  const isOpen = (code: string | null) => editable && form !== null && form.code === code

  const open = (target: MaintenanceTarget) => {
    setSaved('')
    setForm(target)
  }
  const onSaved = (message: string) => {
    setForm(null)
    setSaved(message)
    records.reload()
    onChanged?.()
  }
  const formFor = (target: MaintenanceTarget) => (
    <MaintenanceForm vehicle={vehicle} target={target} onSaved={onSaved} onCancel={() => setForm(null)} />
  )

  return (
    <div className="grid content-start gap-5">
      <section aria-labelledby="vehicle-title" className="grid gap-2">
        <h3 id="vehicle-title" className="text-h3">
          {model.brand} {model.model}
          {model.trim ? ` ${model.trim}` : ''}
        </h3>
        <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-1 text-body-sm">
          <dt className="text-fg-muted">VIN</dt>
          <dd className="font-mono">{vehicle.vin}</dd>
          <dt className="text-fg-muted">Пробег</dt>
          <dd className="tabular-nums">{formatKm(vehicle.mileage)}</dd>
          <dt className="text-fg-muted">Прошивка сейчас</dt>
          <dd>{vehicle.current_firmware_version ?? 'не зафиксирована'}</dd>
          <dt className="text-fg-muted">На момент тикета</dt>
          <dd>{ticket.firmware_version_at_creation ?? 'не зафиксирована'}</dd>
        </dl>
      </section>

      <section aria-labelledby="aggregates-title" className="grid gap-2">
        <h3 id="aggregates-title" className="text-label">
          Статусы агрегатов
        </h3>
        <ul className="grid gap-2">
          {(context.aggregate_statuses ?? []).map((s) => (
            <li key={s.aggregate_type_code} className="grid gap-1 rounded-md border border-border p-2">
              <span className="flex items-center justify-between gap-2">
                <span className="text-body-sm">{s.aggregate_type_name}</span>
                <StatusBadge status={s.status} />
              </span>
              <span className="text-caption text-fg-muted">{statusDetails(s)}</span>
              {editable && !isOpen(s.aggregate_type_code) && (
                <Button
                  variant="secondary"
                  size="sm"
                  className="justify-self-start"
                  aria-label={`Замена или работа: ${s.aggregate_type_name}`}
                  onClick={() => open({ code: s.aggregate_type_code, name: s.aggregate_type_name })}
                >
                  Замена / работа
                </Button>
              )}
              {isOpen(s.aggregate_type_code) && formFor({ code: s.aggregate_type_code, name: s.aggregate_type_name })}
            </li>
          ))}
        </ul>
        <p role="status" className="text-body-sm text-fg empty:hidden">
          {saved}
        </p>
      </section>

      <section aria-labelledby="history-title" className="grid gap-2">
        <div className="flex items-center justify-between gap-2">
          <h3 id="history-title" className="text-label">
            История ТО
          </h3>
          {editable && !isOpen(null) && (
            <Button variant="ghost" size="sm" onClick={() => open(OTHER_WORK)}>
              Другая работа
            </Button>
          )}
        </div>
        {isOpen(null) && formFor(OTHER_WORK)}
        {records.error ? (
          <ErrorState error={records.error} onRetry={records.retry} />
        ) : !records.items ? (
          <LoadingState />
        ) : records.items.length === 0 ? (
          <p className="text-body-sm text-fg-muted">Записей ТО нет.</p>
        ) : (
          <ul className="grid gap-1 text-body-sm">
            {records.items.map((r) => (
              <li key={r.id} className="flex justify-between gap-3 border-b border-border py-1 last:border-b-0">
                <span>
                  {r.aggregate_type_code ? (names.get(r.aggregate_type_code) ?? r.aggregate_type_code) : 'Общие работы'}
                  {r.description ? <span className="text-fg-muted"> — {r.description}</span> : null}
                </span>
                <span className="shrink-0 text-fg-muted tabular-nums">
                  {formatDate(r.performed_at)} · {formatKm(r.mileage_at_service)}
                </span>
              </li>
            ))}
          </ul>
        )}
        {records.more && (
          <Button variant="secondary" size="sm" onClick={records.more}>
            Показать ещё
          </Button>
        )}
      </section>
    </div>
  )
}

function statusDetails(s: AggregateStatus): string {
  if (s.status === 'unknown') return 'Нет истории замены'
  const parts: string[] = []
  if (s.percentage != null) parts.push(`выработка ${s.percentage.toLocaleString('ru-RU')} %`)
  if (s.remaining_km != null) parts.push(s.remaining_km < 0 ? `перепробег ${formatKm(-s.remaining_km)}` : `осталось ${formatKm(s.remaining_km)}`)
  if (s.remaining_days != null) parts.push(s.remaining_days < 0 ? `просрочено ${-s.remaining_days} дн.` : `${s.remaining_days} дн.`)
  return parts.join(' · ')
}
