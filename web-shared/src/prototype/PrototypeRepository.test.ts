import { describe, expect, it } from "vitest";
import { ApiError } from "../data/repository.ts";
import { slaState } from "../data/sla.ts";
import { ENGINEER_ID, OTHER_ENGINEER_ID } from "./fixtures.ts";
import { PrototypeRepository } from "./PrototypeRepository.ts";

const NOW = new Date("2026-10-10T12:00:00Z");
const engineer = () => new PrototypeRepository({ role: "engineer", now: () => NOW });
const admin = () => new PrototypeRepository({ role: "admin", now: () => NOW });

async function apiError(promise: Promise<unknown>): Promise<ApiError> {
  try {
    await promise;
  } catch (e) {
    if (e instanceof ApiError) return e;
    throw e;
  }
  throw new Error("ожидалась ApiError");
}

describe("фикстуры тикетов", () => {
  it("покрывают все колонки канбана и все состояния SLA", async () => {
    const { items } = await engineer().listTickets();
    expect(new Set(items.map((t) => t.status))).toEqual(new Set(["new", "in_progress", "waiting_vendor", "resolved"]));
    expect(new Set(items.map((t) => slaState(t, NOW)))).toEqual(new Set(["overdue", "due_soon", "ok", "closed"]));
  });

  it("is_overdue = now > sla_due_at и status != resolved (контракт)", async () => {
    const { items } = await engineer().listTickets();
    for (const t of items) {
      expect(t.is_overdue).toBe(t.status !== "resolved" && Date.parse(t.sla_due_at) < NOW.getTime());
      expect(t.resolved_at != null).toBe(t.status === "resolved");
    }
  });

  it("фильтры listTickets: status, category, overdue, assigned_engineer_id", async () => {
    const repo = engineer();
    expect((await repo.listTickets({ status: "new" })).items.every((t) => t.status === "new")).toBe(true);
    expect((await repo.listTickets({ category: "sim" })).items.every((t) => t.category === "sim")).toBe(true);
    expect((await repo.listTickets({ overdue: true })).items.map((t) => t.id).sort()).toEqual([1038, 1042, 1058]);
    expect((await repo.listTickets({ assigned_engineer_id: ENGINEER_ID })).items.length).toBe(4);
  });
});

describe("тикет: claim, статусы, сообщения", () => {
  it("claim нового тикета — назначает и переводит в работу", async () => {
    const t = await engineer().claimTicket(1056);
    expect(t.assigned_engineer_id).toBe(ENGINEER_ID);
    expect(t.status).toBe("in_progress");
  });

  it("claim чужого тикета — 409", async () => {
    const e = await apiError(engineer().claimTicket(1050));
    expect([e.code, e.status]).toEqual(["CONFLICT", 409]);
  });

  it("статус чужого тикета — 403, недопустимый переход — 422", async () => {
    const repo = engineer();
    expect((await apiError(repo.updateTicketStatus(1050, "resolved"))).status).toBe(403);
    const e = await apiError(repo.updateTicketStatus(1042, "new"));
    expect([e.code, e.field]).toEqual(["VALIDATION_ERROR", "status"]);
  });

  it("решение заполняет resolved_at, возврат в работу — очищает", async () => {
    const repo = engineer();
    expect((await repo.updateTicketStatus(1042, "resolved")).resolved_at).toBe(NOW.toISOString());
    expect((await repo.updateTicketStatus(1042, "in_progress")).resolved_at).toBeNull();
  });

  it("сообщение — только назначенному инженеру и не пустое", async () => {
    const repo = engineer();
    expect((await apiError(repo.createTicketMessage(1050, "Здравствуйте"))).status).toBe(403);
    expect((await apiError(repo.createTicketMessage(1042, "  "))).status).toBe(422);
    const m = await repo.createTicketMessage(1042, "Проверьте APN");
    expect(m.author.id).toBe(ENGINEER_ID);
    expect((await repo.listTicketMessages(1042)).items.at(-1)?.body).toBe("Проверьте APN");
  });

  it("контекст авто в карточке тикета", async () => {
    const t = await engineer().getTicket(1042);
    expect(t.vehicle_context?.vehicle?.vin).toBe("LLXAB3CF7SA067890");
    expect(t.vehicle_context?.aggregate_statuses?.map((s) => s.status)).toContain("red");
  });

  it("ответы — копии: изменение объекта не меняет данные репозитория", async () => {
    const repo = engineer();
    const t = await repo.getTicket(1050);
    t.assigned_engineer_id = ENGINEER_ID;
    expect((await repo.getTicket(1050)).assigned_engineer_id).toBe(OTHER_ENGINEER_ID);
  });
});

describe("сценарии «Демо»", () => {
  it("нет сети — ApiError NETWORK на любой операции", async () => {
    const repo = engineer();
    repo.setOffline(true);
    expect((await apiError(repo.listTickets())).code).toBe("NETWORK");
    repo.setOffline(false);
    expect((await repo.listTickets()).items.length).toBeGreaterThan(0);
  });

  it("пустой сценарий и сброс", async () => {
    const repo = engineer();
    repo.setScenario("empty");
    expect((await repo.listTickets()).items).toEqual([]);
    repo.setScenario("demo");
    await repo.claimTicket(1056);
    repo.reset();
    expect((await repo.getTicket(1056)).status).toBe("new");
  });
});

describe("регламенты ТО", () => {
  it("пересмотр архивирует прошлую версию, а не перезаписывает", async () => {
    const repo = admin();
    const before = await repo.listMaintenanceRegulations({ vehicle_model_id: 1 });
    const old = before.find((r) => r.aggregate_type_code === "engine_oil")!;
    const next = await repo.reviseMaintenanceRegulation({ vehicle_model_id: 1, aggregate_type_code: "engine_oil", interval_km: 12000, interval_months: 12 });
    const all = await repo.listMaintenanceRegulations({ vehicle_model_id: 1, include_archived: true });
    expect(all.find((r) => r.id === old.id)?.is_archived).toBe(true);
    expect(next.is_archived).toBe(false);
    expect((await repo.listMaintenanceRegulations({ vehicle_model_id: 1 })).filter((r) => r.aggregate_type_code === "engine_oil")).toEqual([next]);
  });

  it("нужен хотя бы один интервал ≥ 1", async () => {
    const repo = admin();
    const body = { vehicle_model_id: 1, aggregate_type_code: "engine_oil" };
    expect((await apiError(repo.reviseMaintenanceRegulation({ ...body, interval_km: null, interval_months: null }))).status).toBe(422);
    expect((await apiError(repo.reviseMaintenanceRegulation({ ...body, interval_km: 0 }))).field).toBe("interval_km");
  });

  it("пороги: 1 ≤ жёлтый < красный ≤ 200", async () => {
    const repo = admin();
    expect((await apiError(repo.updateAggregateStatusThresholds({ yellow_from_percent: 100, red_above_percent: 100 }))).status).toBe(422);
    expect(await repo.updateAggregateStatusThresholds({ yellow_from_percent: 75, red_above_percent: 110 })).toMatchObject({
      yellow_from_percent: 75,
      red_above_percent: 110,
    });
  });

  it("справочник агрегатов: код по шаблону, без дублей", async () => {
    const repo = admin();
    expect((await apiError(repo.createAggregateType({ code: "Brake Fluid", name: "Тормозная жидкость" }))).field).toBe("code");
    await repo.createAggregateType({ code: "brake_fluid", name: "Тормозная жидкость" });
    expect((await apiError(repo.createAggregateType({ code: "brake_fluid", name: "Ещё раз" }))).status).toBe(409);
  });
});

describe("база знаний и дерево решений", () => {
  it("деревья фикстур проходят проверку", async () => {
    const repo = admin();
    for (const id of [10, 11, 12, 13]) expect((await repo.validateDecisionTree(id)).is_valid).toBe(true);
  });

  it("проверка находит тупик, битую ссылку, недостижимый шаг и второй корень", async () => {
    const repo = admin();
    const dead = await repo.createDecisionTreeNode(10, {
      question_text: "Тупик",
      is_root: false,
      is_escalation: false,
      options: [{ label: "Дальше", next_node_id: null }],
    });
    await repo.createDecisionTreeNode(10, { question_text: "Второй корень", is_root: true, is_escalation: false, options: [{ label: "x", next_node_id: 999 }] });
    const { is_valid, issues } = await repo.validateDecisionTree(10);
    expect(is_valid).toBe(false);
    expect(new Set(issues.map((i) => i.problem))).toEqual(new Set(["DEAD_END", "BROKEN_REFERENCE", "UNREACHABLE", "MULTIPLE_ROOTS"]));
    expect(issues).toContainEqual({ node_id: dead.id, problem: "DEAD_END" });
  });

  it("статья: черновик → публикация, правка поднимает версию; дерево с ошибкой не публикуется", async () => {
    const repo = admin();
    const draft = await repo.createKnowledgeArticle({ article_type: "guide", title: "Новая", content: "Текст" });
    expect([draft.is_published, draft.version]).toEqual([false, 1]);
    const published = await repo.updateKnowledgeArticle(draft.id, { content: "Текст 2", is_published: true });
    expect([published.is_published, published.version]).toEqual([true, 2]);

    const ts = await repo.createKnowledgeArticle({ article_type: "troubleshooting", title: "Без дерева?", content: "x" });
    await repo.createDecisionTreeNode(ts.id, { question_text: "?", is_root: true, is_escalation: false, options: [{ label: "a", next_node_id: null }] });
    expect((await apiError(repo.updateKnowledgeArticle(ts.id, { is_published: true }))).field).toBe("is_published");
  });

  it("прошивка статьи должна относиться к её модели", async () => {
    const e = await apiError(
      admin().createKnowledgeArticle({ article_type: "guide", title: "t", content: "c", vehicle_model_id: 2, firmware_release_id: 1 }),
    );
    expect(e.field).toBe("firmware_release_id");
  });

  it("поиск — по заголовку и тексту, без учёта регистра", async () => {
    const { items } = await engineer().listKnowledgeArticles({ search: "ПРОБКИ" });
    expect(items.map((a) => a.id)).toContain(3);
  });
});

describe("публикации и аналитика", () => {
  it("релиз прошивки создаёт уведомление type=firmware с таргетингом по модели", async () => {
    const repo = admin();
    const release = await repo.createFirmwareRelease({ vehicle_model_id: 2, version: "RU 5.2.0", released_at: "2026-10-10" });
    const [latest] = await repo.listPublishedNotifications();
    expect(latest).toMatchObject({ type: "firmware", target_vehicle_model_id: 2, firmware_release_id: release.id });
    expect((await apiError(repo.createFirmwareRelease({ vehicle_model_id: 2, version: "RU 5.2.0", released_at: "2026-10-10" }))).status).toBe(409);
  });

  it("уведомление: текст обязателен; новое — первым в ленте", async () => {
    const repo = admin();
    expect((await apiError(repo.createNotification({ type: "news", message: " " }))).field).toBe("message");
    const n = await repo.createNotification({ type: "promo", message: "Акция", target_vehicle_model_id: null });
    expect((await repo.listPublishedNotifications())[0].id).toBe(n.id);
  });

  it("аналитика пропорциональна периоду; пустая система — нули и null", async () => {
    const repo = admin();
    const week = await repo.getTicketResolutionStats({ date_from: "2026-10-04", date_to: "2026-10-10" });
    const month = await repo.getTicketResolutionStats({ date_from: "2026-09-11", date_to: "2026-10-10" });
    expect(week.tickets_created).toBe(30);
    expect(month.tickets_created).toBeGreaterThan(week.tickets_created);
    expect(week.tickets_resolved_overdue).toBeLessThanOrEqual(week.tickets_resolved);
    repo.setScenario("empty");
    const empty = await repo.getMaintenanceConversionStats({ date_from: "2026-10-04", date_to: "2026-10-10" });
    expect([empty.tickets_total, empty.ticket_to_maintenance_rate]).toEqual([0, null]);
    expect(await repo.listProblemModels({ date_from: "2026-10-04", date_to: "2026-10-10" })).toEqual([]);
  });
});
