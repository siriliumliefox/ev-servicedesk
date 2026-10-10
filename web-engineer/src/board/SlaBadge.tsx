// SLA тикета: иконка + текст + цвет (ТЗ раздел 6 — не только цветом). Формы иконок — как у статусов
// агрегатов: восьмиугольник — просрочен, треугольник — истекает, круг с галочкой — в норме.
import { Badge, SLA_LABELS, StatusIcon, slaState, slaText, type BadgeTone, type Ticket } from '@ev-servicedesk/web-shared'

const VIEW = {
  overdue: { tone: 'danger', icon: 'red' },
  due_soon: { tone: 'warning', icon: 'yellow' },
  ok: { tone: 'success', icon: 'green' },
  closed: { tone: 'neutral', icon: 'unknown' },
} as const satisfies Record<string, { tone: BadgeTone; icon: 'red' | 'yellow' | 'green' | 'unknown' }>

export function SlaBadge({ ticket, now }: { ticket: Ticket; now: Date }) {
  const state = slaState(ticket, now)
  const { tone, icon } = VIEW[state]
  return (
    <Badge tone={tone}>
      <StatusIcon status={icon} className="size-3.5" />
      <span className="sr-only">SLA: {SLA_LABELS[state]}. </span>
      {slaText(ticket, now)}
    </Badge>
  )
}
