// Граф статусов (ADR 0017 п. 4) и переносы инженера на доске (ADR 0025 п. 7).
import { describe, expect, it } from "vitest";
import type { Ticket } from "./models.ts";
import { allowedTransitions, engineerMoves } from "./ticketFlow.ts";

const ticket = (status: Ticket["status"], assigned: number | null) => ({ status, assigned_engineer_id: assigned }) as Ticket;

describe("ticketFlow", () => {
  it("граф: в очередь не возвращается, решённый — только переоткрыть", () => {
    expect(allowedTransitions("new")).toEqual([]);
    expect(allowedTransitions("in_progress")).toEqual(["waiting_vendor", "resolved"]);
    expect(allowedTransitions("resolved")).toEqual(["in_progress"]);
  });

  it("инженер: из очереди — взять в работу, свой — по графу, чужой — никуда", () => {
    expect(engineerMoves(ticket("new", null), 7)).toEqual(["in_progress"]);
    expect(engineerMoves(ticket("waiting_vendor", 7), 7)).toEqual(["in_progress", "resolved"]);
    expect(engineerMoves(ticket("in_progress", 8), 7)).toEqual([]);
    expect(engineerMoves(ticket("new", 8), 7)).toEqual([]);
  });
});
