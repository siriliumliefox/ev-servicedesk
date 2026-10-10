/**
 * Индикатор статуса агрегата ("светофор") — Глава 5 ТЗ / AggregateStatus (Глава 3).
 * Общий для web-engineer и web-admin, чтобы цвета/подписи не разъезжались
 * между интерфейсами. Статус передаётся тремя каналами — цвет, форма иконки
 * и подпись (ТЗ раздел 6: "не только цветом"). Цвета — токены status-* (Глава 6).
 */
export type AggregateStatusValue = "green" | "yellow" | "red" | "unknown";

export const STATUS_LABELS: Record<AggregateStatusValue, string> = {
  green: "Заменено",
  yellow: "Скоро менять",
  red: "Требуется замена",
  unknown: "Нет данных",
};

const COLORS: Record<AggregateStatusValue, string> = {
  green: "bg-status-green-bg text-status-green-fg",
  yellow: "bg-status-yellow-bg text-status-yellow-fg",
  red: "bg-status-red-bg text-status-red-fg",
  unknown: "bg-status-unknown-bg text-status-unknown-fg",
};

/** Форма иконки своя у каждого статуса: круг с галочкой, треугольник, восьмиугольник, круг с вопросом. */
export function StatusIcon({ status, className = "size-4" }: { status: AggregateStatusValue; className?: string }) {
  return (
    <svg
      viewBox="0 0 16 16"
      fill="none"
      stroke="currentColor"
      strokeWidth={1.5}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      className={className}
    >
      {status === "green" && (
        <>
          <circle cx="8" cy="8" r="6.25" />
          <path d="M5.25 8.25 7 10l3.75-4" />
        </>
      )}
      {status === "yellow" && (
        <>
          <path d="M8 1.75 14.75 13.75H1.25Z" />
          <path d="M8 6v3.5" />
          <circle cx="8" cy="11.6" r="0.4" fill="currentColor" />
        </>
      )}
      {status === "red" && (
        <>
          <path d="M5.3 1.5h5.4l3.8 3.8v5.4l-3.8 3.8H5.3l-3.8-3.8V5.3Z" />
          <path d="m5.75 5.75 4.5 4.5m0-4.5-4.5 4.5" />
        </>
      )}
      {status === "unknown" && (
        <>
          <circle cx="8" cy="8" r="6.25" />
          <path d="M6.25 6.25a1.75 1.75 0 1 1 2.6 1.53c-.5.28-.85.62-.85 1.22v.25" />
          <circle cx="8" cy="11.25" r="0.4" fill="currentColor" />
        </>
      )}
    </svg>
  );
}

export function StatusBadge({ status }: { status: AggregateStatusValue }) {
  return (
    <span
      className={`inline-flex items-center gap-2 rounded-full py-1 pr-3 pl-2 text-label ${COLORS[status]}`}
    >
      <StatusIcon status={status} />
      {STATUS_LABELS[status]}
    </span>
  );
}
