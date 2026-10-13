// Граф статусов тикета (ADR 0017 п. 4) — общее правило для прототипа и кабинета на реальном API.
// new → in_progress — только взятием в работу (claim) или назначением админом; в очередь не возвращается.
import type { Ticket, TicketStatus } from "./models.ts";

const TRANSITIONS: Record<TicketStatus, readonly TicketStatus[]> = {
  new: [],
  in_progress: ["waiting_vendor", "resolved"],
  waiting_vendor: ["in_progress", "resolved"],
  resolved: ["in_progress"],
};

/** Переходы статуса для назначенного сотрудника (`updateTicketStatus`). */
export function allowedTransitions(status: TicketStatus): readonly TicketStatus[] {
  return TRANSITIONS[status];
}

/**
 * Куда инженер `meId` может перенести тикет на доске: из очереди — только «В работе» (взять в работу),
 * свой — по графу, чужой — никуда.
 */
export function engineerMoves(ticket: Ticket, meId: number): readonly TicketStatus[] {
  if (ticket.status === "new") return ticket.assigned_engineer_id == null ? ["in_progress"] : [];
  return ticket.assigned_engineer_id === meId ? TRANSITIONS[ticket.status] : [];
}
