// Дашборд аналитики (ТЗ 4.4, A-05/A-06): время реакции и закрытия тикетов, проблемные модели, конверсия
// в запись на ТО. Только операции `/analytics/*` контракта v1 (ADR 0012 п. 4).
import { useState } from 'react'
import {
  Card,
  Chip,
  EmptyState,
  ErrorState,
  LoadingState,
  TICKET_CATEGORIES,
  TICKET_CATEGORY_LABELS,
  formatHours,
  formatInt,
  formatRate,
  toIsoDate,
  useAsync,
  type DateRange,
  type MaintenanceConversionStats,
  type ProblemModelStats,
  type TicketResolutionStats,
} from '@ev-servicedesk/web-shared'
import { useAdmin } from '../repo.ts'

const PERIODS = [7, 30, 90] as const

export function Dashboard() {
  const { repo, now } = useAdmin()
  const [days, setDays] = useState<(typeof PERIODS)[number]>(30)
  const today = now()
  const range: DateRange = {
    date_from: toIsoDate(new Date(today.getFullYear(), today.getMonth(), today.getDate() - days + 1)),
    date_to: toIsoDate(today),
  }
  const data = useAsync(
    () =>
      Promise.all([
        repo.getTicketResolutionStats(range),
        repo.listProblemModels(range),
        repo.getMaintenanceConversionStats(range),
      ]),
    [repo, range.date_from, range.date_to],
  )

  return (
    <div className="grid gap-6">
      <div role="group" aria-label="Период" className="flex items-center gap-2">
        <span className="text-label text-fg-muted">Период</span>
        {PERIODS.map((p) => (
          <Chip key={p} selected={days === p} onClick={() => setDays(p)}>
            {p} дней
          </Chip>
        ))}
      </div>

      {data.error ? (
        <ErrorState error={data.error} onRetry={data.reload} />
      ) : !data.data ? (
        <LoadingState label="Загрузка аналитики…" />
      ) : (
        <DashboardBody stats={data.data} />
      )}
    </div>
  )
}

function DashboardBody({
  stats: [resolution, models, conversion],
}: {
  stats: [TicketResolutionStats, ProblemModelStats[], MaintenanceConversionStats]
}) {
  const overdueShare = resolution.tickets_resolved ? resolution.tickets_resolved_overdue / resolution.tickets_resolved : null
  return (
    <>
      <section aria-labelledby="kpi-title" className="grid gap-3">
        <h2 id="kpi-title" className="text-h3">
          Тикеты
        </h2>
        <div className="grid grid-cols-3 gap-4 xl:grid-cols-6">
          <Kpi label="Создано" value={formatInt(resolution.tickets_created)} />
          <Kpi label="Решено" value={formatInt(resolution.tickets_resolved)} />
          <Kpi
            label="Решено с просрочкой SLA"
            value={formatInt(resolution.tickets_resolved_overdue)}
            note={overdueShare == null ? undefined : `${formatRate(overdueShare)} от решённых`}
          />
          <Kpi label="Первый ответ, в среднем" value={formatHours(resolution.avg_first_response_hours)} />
          <Kpi label="Закрытие, в среднем" value={formatHours(resolution.avg_resolution_hours)} />
          <Kpi label="Закрытие, медиана" value={formatHours(resolution.median_resolution_hours)} />
        </div>
      </section>

      <section aria-labelledby="models-title" className="grid gap-3">
        <h2 id="models-title" className="text-h3">
          Проблемные модели
        </h2>
        {models.length === 0 ? (
          <EmptyState title="Обращений за период нет">Модели без тикетов в отчёт не попадают.</EmptyState>
        ) : (
          <ProblemModels items={models} />
        )}
      </section>

      <section aria-labelledby="conversion-title" className="grid gap-3">
        <h2 id="conversion-title" className="text-h3">
          Конверсия в запись на ТО
        </h2>
        <div className="grid grid-cols-2 gap-4">
          <Funnel
            title="Обращение → запись на ТО"
            rate={conversion.ticket_to_maintenance_rate}
            steps={[
              ['Тикетов', conversion.tickets_total],
              ['С записью на ТО', conversion.tickets_with_maintenance],
            ]}
          />
          <Funnel
            title="Уведомление о ТО → запись"
            rate={conversion.notification_to_maintenance_rate}
            steps={[
              ['Получили уведомление', conversion.notifications_recipients],
              ['Открыли', conversion.notifications_opened],
              ['Записались на ТО', conversion.recipients_with_maintenance],
            ]}
          />
        </div>
      </section>
    </>
  )
}

function Kpi({ label, value, note }: { label: string; value: string; note?: string }) {
  return (
    <Card className="grid content-start gap-1">
      <span className="text-body-sm text-fg-muted">{label}</span>
      <span className="text-h1 tabular-nums">{value}</span>
      {note && <span className="text-caption text-fg-muted">{note}</span>}
    </Card>
  )
}

/** Таблица, а не только диаграмма: значения читаются скринридером; полоса — тикеты на 10 авто модели. */
function ProblemModels({ items }: { items: ProblemModelStats[] }) {
  const per10 = (m: ProblemModelStats) => (m.vehicles_total ? (m.tickets_total / m.vehicles_total) * 10 : 0)
  const max = Math.max(...items.map(per10), 1)
  return (
    <Card className="overflow-x-auto p-0">
      <table className="w-full text-body-sm">
        <thead className="text-left text-fg-muted">
          <tr className="border-b border-border">
            <th className="px-4 py-3 font-semibold">Модель</th>
            <th className="px-4 py-3 text-right font-semibold">Тикетов</th>
            <th className="px-4 py-3 text-right font-semibold">Авто</th>
            <th className="w-64 px-4 py-3 font-semibold">На 10 авто</th>
            {TICKET_CATEGORIES.map((c) => (
              <th key={c} className="px-4 py-3 text-right font-semibold">
                {TICKET_CATEGORY_LABELS[c]}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {items.map((m) => (
            <tr key={m.vehicle_model.id} className="border-b border-border last:border-b-0">
              <th scope="row" className="px-4 py-3 text-left font-semibold">
                {m.vehicle_model.brand} {m.vehicle_model.model}
              </th>
              <td className="px-4 py-3 text-right tabular-nums">{formatInt(m.tickets_total)}</td>
              <td className="px-4 py-3 text-right tabular-nums">{formatInt(m.vehicles_total)}</td>
              <td className="px-4 py-3">
                <span className="flex items-center gap-2">
                  <span className="h-2 flex-1 rounded-full bg-surface-subtle" aria-hidden="true">
                    <span className="block h-2 rounded-full bg-info-text" style={{ width: `${(per10(m) / max) * 100}%` }} />
                  </span>
                  <span className="w-10 text-right tabular-nums">{per10(m).toLocaleString('ru-RU', { maximumFractionDigits: 1 })}</span>
                </span>
              </td>
              {TICKET_CATEGORIES.map((c) => (
                <td key={c} className="px-4 py-3 text-right tabular-nums">
                  {formatInt(m.by_category.find((x) => x.category === c)?.count ?? 0)}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </Card>
  )
}

function Funnel({ title, rate, steps }: { title: string; rate: number | null | undefined; steps: [string, number][] }) {
  const first = steps[0][1]
  return (
    <Card className="grid gap-3">
      <div className="flex items-baseline justify-between gap-2">
        <h3 className="text-label">{title}</h3>
        <span className="text-h2 tabular-nums">{formatRate(rate)}</span>
      </div>
      <ol className="grid gap-2">
        {steps.map(([label, value]) => (
          <li key={label} className="grid gap-1">
            <span className="flex justify-between text-body-sm">
              <span>{label}</span>
              <span className="tabular-nums">{formatInt(value)}</span>
            </span>
            <span className="h-2 rounded-full bg-surface-subtle" aria-hidden="true">
              <span className="block h-2 rounded-full bg-info-text" style={{ width: `${first ? (value / first) * 100 : 0}%` }} />
            </span>
          </li>
        ))}
      </ol>
    </Card>
  )
}
