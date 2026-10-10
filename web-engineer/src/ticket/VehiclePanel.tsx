// Контекст авто клиента из тикета (ТЗ 4.3): модель, VIN, пробег, прошивка, статусы агрегатов, история ТО.
// Авто и статусы приходят в TicketDetail.vehicle_context, история — listMaintenanceRecords.
import {
  ErrorState,
  LoadingState,
  StatusBadge,
  formatDate,
  formatKm,
  useAsync,
  type AggregateStatus,
  type TicketDetail,
} from '@ev-servicedesk/web-shared'
import { useEngineer } from '../repo.ts'

export function VehiclePanel({ ticket }: { ticket: TicketDetail }) {
  const { repo } = useEngineer()
  const context = ticket.vehicle_context
  const vehicle = context?.vehicle
  const records = useAsync(
    () => (vehicle ? repo.listMaintenanceRecords(vehicle.id) : Promise.resolve(null)),
    [repo, vehicle?.id],
  )

  if (!vehicle) return <p className="text-body-sm text-fg-muted">Авто не привязано к обращению.</p>

  const names = new Map((context.aggregate_statuses ?? []).map((s) => [s.aggregate_type_code, s.aggregate_type_name]))
  const model = vehicle.vehicle_model

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
          <dt className="text-fg-muted">Прошивка</dt>
          <dd>{vehicle.current_firmware_version ?? 'не зафиксирована'}</dd>
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
            </li>
          ))}
        </ul>
      </section>

      <section aria-labelledby="history-title" className="grid gap-2">
        <h3 id="history-title" className="text-label">
          История ТО
        </h3>
        {records.error ? (
          <ErrorState error={records.error} onRetry={records.reload} />
        ) : !records.data ? (
          <LoadingState />
        ) : records.data.items.length === 0 ? (
          <p className="text-body-sm text-fg-muted">Записей ТО нет.</p>
        ) : (
          <ul className="grid gap-1 text-body-sm">
            {records.data.items.map((r) => (
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
