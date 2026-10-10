import { describe, expect, it } from "vitest";
import type { Ticket } from "./models.ts";
import { DUE_SOON_MS, bySlaDue, matchesSla, slaState, slaText } from "./sla.ts";

const NOW = new Date("2026-10-10T12:00:00Z");
const at = (ms: number) => new Date(NOW.getTime() + ms).toISOString();

const ticket = (patch: Partial<Ticket>): Ticket => ({
  id: 1,
  category: "sim",
  status: "new",
  sla_due_at: at(2 * 3600_000),
  is_overdue: false,
  created_at: at(-3600_000),
  ...patch,
});

describe("slaState", () => {
  it("решённый тикет — closed, даже если срок прошёл", () => {
    expect(slaState(ticket({ status: "resolved", sla_due_at: at(-1), is_overdue: false }), NOW)).toBe("closed");
  });

  it("is_overdue от backend важнее локального расчёта", () => {
    expect(slaState(ticket({ is_overdue: true, sla_due_at: at(3600_000) }), NOW)).toBe("overdue");
  });

  it.each([
    [-1, "overdue"],
    [0, "overdue"],
    [1, "due_soon"],
    [DUE_SOON_MS, "due_soon"],
    [DUE_SOON_MS + 1, "ok"],
  ] as const)("до срока %i мс → %s", (left, expected) => {
    expect(slaState(ticket({ sla_due_at: at(left) }), NOW)).toBe(expected);
  });
});

describe("slaText", () => {
  it.each([
    [-(2 * 3600_000 + 10 * 60_000), "Просрочен на 2 ч 10 мин"],
    [40 * 60_000, "Осталось 40 мин"],
    [3 * 3600_000, "Осталось 3 ч"],
    [-(2 * 86_400_000 + 3600_000), "Просрочен на 2 д 1 ч"],
    [10_000, "Осталось 1 мин"],
  ] as const)("%i мс → «%s»", (left, text) => {
    expect(slaText(ticket({ sla_due_at: at(left) }), NOW)).toBe(text);
  });

  it("решён в срок / с просрочкой — по resolved_at", () => {
    const due = at(-3600_000);
    expect(slaText(ticket({ status: "resolved", sla_due_at: due, resolved_at: at(-2 * 3600_000) }), NOW)).toBe("Решён в срок");
    expect(slaText(ticket({ status: "resolved", sla_due_at: due, resolved_at: at(-60_000) }), NOW)).toBe("Решён с просрочкой");
  });
});

describe("фильтр и сортировка", () => {
  it("all пропускает всё, остальные — по состоянию", () => {
    const t = ticket({ sla_due_at: at(30 * 60_000) });
    expect(matchesSla(t, "all", NOW)).toBe(true);
    expect(matchesSla(t, "due_soon", NOW)).toBe(true);
    expect(matchesSla(t, "ok", NOW)).toBe(false);
  });

  it("сначала самый ранний срок", () => {
    const list = [ticket({ id: 1, sla_due_at: at(5) }), ticket({ id: 2, sla_due_at: at(-5) }), ticket({ id: 3, sla_due_at: at(0) })];
    expect(list.sort(bySlaDue).map((t) => t.id)).toEqual([2, 3, 1]);
  });
});
