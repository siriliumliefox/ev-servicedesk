// Форматирование дат и чисел для интерфейса (ru-RU, часовой пояс браузера).

const dateFmt = new Intl.DateTimeFormat("ru-RU", { day: "numeric", month: "short", year: "numeric" });
const dateTimeFmt = new Intl.DateTimeFormat("ru-RU", {
  day: "numeric",
  month: "short",
  hour: "2-digit",
  minute: "2-digit",
});
const intFmt = new Intl.NumberFormat("ru-RU");

/** `2026-10-08` или ISO date-time → «8 окт. 2026 г.». */
export function formatDate(value: string): string {
  return dateFmt.format(new Date(value.length === 10 ? `${value}T00:00:00` : value));
}

export function formatDateTime(value: string): string {
  return dateTimeFmt.format(new Date(value));
}

export function formatInt(value: number): string {
  return intFmt.format(value);
}

export function formatKm(value: number): string {
  return `${intFmt.format(value)} км`;
}

/** Часы с одним знаком: 1.25 → «1,3 ч»; null → «—». */
export function formatHours(value: number | null | undefined): string {
  return value == null ? "—" : `${value.toLocaleString("ru-RU", { maximumFractionDigits: 1 })} ч`;
}

/** Доля 0…1 → «23 %»; null → «—». */
export function formatRate(value: number | null | undefined): string {
  return value == null ? "—" : `${Math.round(value * 100)} %`;
}

/** Локальная дата в формате OpenAPI `date` (YYYY-MM-DD). */
export function toIsoDate(date: Date): string {
  const y = date.getFullYear();
  const m = String(date.getMonth() + 1).padStart(2, "0");
  const d = String(date.getDate()).padStart(2, "0");
  return `${y}-${m}-${d}`;
}
