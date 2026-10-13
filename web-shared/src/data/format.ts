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

/** Часы до 0,01, как в API (ADR 0020): 0.925 → «0,93 ч», 11 → «11 ч»; null → «—». Сверка с ручным расчётом. */
export function formatHours(value: number | null | undefined): string {
  return value == null ? "—" : `${value.toLocaleString("ru-RU", { maximumFractionDigits: 2 })} ч`;
}

/** Доля 0…1 → «23 %»; null → «—». */
export function formatRate(value: number | null | undefined): string {
  return value == null ? "—" : `${Math.round(value * 100)} %`;
}

/** Число со словом в нужной форме: plural(2, "шаг", "шага", "шагов") → «2 шага»; 11–14 — «много». */
export function plural(n: number, one: string, few: string, many: string): string {
  const mod10 = n % 10;
  const mod100 = n % 100;
  const word = mod10 === 1 && mod100 !== 11 ? one : mod10 >= 2 && mod10 <= 4 && (mod100 < 12 || mod100 > 14) ? few : many;
  return `${intFmt.format(n)} ${word}`;
}

/** Локальная дата в формате OpenAPI `date` (YYYY-MM-DD). */
export function toIsoDate(date: Date): string {
  const y = date.getFullYear();
  const m = String(date.getMonth() + 1).padStart(2, "0");
  const d = String(date.getDate()).padStart(2, "0");
  return `${y}-${m}-${d}`;
}
