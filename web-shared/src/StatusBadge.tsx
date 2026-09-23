/**
 * Индикатор статуса агрегата ("светофор") — Глава 5 ТЗ / AggregateStatus (Глава 3).
 * Общий для web-engineer и web-admin, чтобы цвета/подписи не разъезжались
 * между интерфейсами (требование "не только цветом", ТЗ раздел 6 — доступность).
 */
export type AggregateStatusValue = "green" | "yellow" | "red" | "unknown";

const LABELS: Record<AggregateStatusValue, string> = {
  green: "Заменено",
  yellow: "Скоро менять",
  red: "Требуется замена",
  unknown: "Нет данных",
};

const COLORS: Record<AggregateStatusValue, string> = {
  green: "bg-green-100 text-green-800",
  yellow: "bg-yellow-100 text-yellow-800",
  red: "bg-red-100 text-red-800",
  unknown: "bg-gray-100 text-gray-600",
};

export function StatusBadge({ status }: { status: AggregateStatusValue }) {
  return (
    <span className={`inline-flex items-center px-2 py-1 rounded text-sm font-medium ${COLORS[status]}`}>
      {LABELS[status]}
    </span>
  );
}
