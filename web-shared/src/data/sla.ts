// SLA тикета на канбане (Глава 8, ADR 0012). Приоритета в контракте v1 нет — срочность выводится из
// `sla_due_at` и `is_overdue` (вычисляет backend), порог «истекает» — DUE_SOON_MS.
import type { Ticket } from "./models.ts";

export type SlaState = "overdue" | "due_soon" | "ok" | "closed";

/** Фильтры канбана «SLA»: всё, просрочен, истекает < 1 ч, в норме. */
export type SlaFilter = "all" | Exclude<SlaState, "closed">;

export const DUE_SOON_MS = 60 * 60 * 1000;

export const SLA_LABELS: Record<SlaState, string> = {
  overdue: "Просрочен",
  due_soon: "Истекает < 1 ч",
  ok: "В норме",
  closed: "Закрыт",
};

export function slaState(ticket: Pick<Ticket, "status" | "sla_due_at" | "is_overdue">, now: Date): SlaState {
  if (ticket.status === "resolved") return "closed";
  if (ticket.is_overdue) return "overdue";
  const left = Date.parse(ticket.sla_due_at) - now.getTime();
  if (left <= 0) return "overdue";
  return left <= DUE_SOON_MS ? "due_soon" : "ok";
}

export function matchesSla(ticket: Ticket, filter: SlaFilter, now: Date): boolean {
  return filter === "all" || slaState(ticket, now) === filter;
}

/** «Просрочен на 2 ч 10 мин» / «Осталось 45 мин» / «Решён в срок». */
export function slaText(ticket: Ticket, now: Date): string {
  const state = slaState(ticket, now);
  if (state === "closed") {
    const resolved = ticket.resolved_at ? Date.parse(ticket.resolved_at) : now.getTime();
    return resolved > Date.parse(ticket.sla_due_at) ? "Решён с просрочкой" : "Решён в срок";
  }
  const diff = Date.parse(ticket.sla_due_at) - now.getTime();
  const span = formatSpan(Math.abs(diff));
  return state === "overdue" ? `Просрочен на ${span}` : `Осталось ${span}`;
}

/** Сортировка колонки: сначала самый ранний срок SLA. */
export function bySlaDue(a: Ticket, b: Ticket): number {
  return Date.parse(a.sla_due_at) - Date.parse(b.sla_due_at);
}

function formatSpan(ms: number): string {
  const minutes = Math.max(1, Math.round(ms / 60_000));
  const days = Math.floor(minutes / 1440);
  const hours = Math.floor((minutes % 1440) / 60);
  const mins = minutes % 60;
  if (days > 0) return hours > 0 ? `${days} д ${hours} ч` : `${days} д`;
  if (hours > 0) return mins > 0 ? `${hours} ч ${mins} мин` : `${hours} ч`;
  return `${mins} мин`;
}
