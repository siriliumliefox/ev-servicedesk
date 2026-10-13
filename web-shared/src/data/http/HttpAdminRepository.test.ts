// HttpAdminRepository на подменённом fetch (глава 22, ADR 0026 п. 2): адреса, тела и запросы операций
// админ-панели совпадают с контрактом, ошибки — `ApiError` с текстом по коду, справочники — все страницы.
import { describe, expect, it } from "vitest";
import { ERROR_TEXTS } from "../errors.ts";
import { ApiError } from "../repository.ts";
import { HttpAdminRepository } from "./HttpAdminRepository.ts";
import { ApiSession, memoryTokenStore } from "./session.ts";

const BASE = "http://api.test/v1";

type Call = { method: string; path: string; query: URLSearchParams; body: unknown };

const json = (status: number, body: unknown) =>
  new Response(body === null ? null : JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });

const page = <T>(items: T[], number = 1, pages = 1) => ({
  items,
  meta: { page: number, page_size: 100, total_items: items.length * pages, total_pages: pages },
});

/** Отвечает `respond(call)` на любой запрос и записывает его. Вход — сразу, без сервера авторизации. */
async function repoWith(respond: (call: Call) => Response) {
  const calls: Call[] = [];
  const fetch = async (input: RequestInfo | URL, init?: RequestInit) => {
    const request = input instanceof Request ? input : new Request(input, init);
    const url = new URL(request.url);
    const text = request.method === "GET" || request.method === "DELETE" ? "" : await request.text();
    const call = { method: request.method, path: url.pathname.replace("/v1", ""), query: url.searchParams, body: text ? JSON.parse(text) : null };
    if (call.path === "/auth/staff/login") {
      return json(200, { access_token: "a", refresh_token: "r", expires_in: 900, user: { id: 1, role: "admin" } });
    }
    calls.push(call);
    return respond(call);
  };
  const session = new ApiSession({ baseUrl: BASE, store: memoryTokenStore(), fetch });
  await session.login("+375291000001", "secret");
  return { repo: new HttpAdminRepository(session), calls };
}

describe("HttpAdminRepository", () => {
  it("пользователи: фильтры списка, создание, роль и блокировка, сброс пароля (контракт 1.11.0)", async () => {
    const { repo, calls } = await repoWith((c) => (c.method === "POST" && c.path.endsWith("/password") ? new Response(null, { status: 204 }) : json(200, page([]))));
    await repo.listUsers({ role: "engineer", is_active: false, search: "29", page: 2 });
    await repo.createStaffUser({ phone: "+375291234567", role: "engineer", password: "x".repeat(12) });
    await repo.updateUser(7, { is_active: false });
    await expect(repo.resetUserPassword(7, "y".repeat(12))).resolves.toBeUndefined();
    expect(calls.map((c) => `${c.method} ${c.path}`)).toEqual([
      "GET /users",
      "POST /users",
      "PATCH /users/7",
      "POST /users/7/password",
    ]);
    expect(Object.fromEntries(calls[0].query)).toEqual({ role: "engineer", is_active: "false", search: "29", page: "2" });
    expect(calls[2].body).toEqual({ is_active: false });
    expect(calls[3].body).toEqual({ password: "y".repeat(12) });
  });

  it("ошибка пользователя — код контракта и текст UI (LAST_ADMIN)", async () => {
    const { repo } = await repoWith(() => json(409, { error: { code: "LAST_ADMIN", message: "server" } }));
    const e = await repo.updateUser(1, { role: "engineer" }).catch((x: unknown) => x);
    expect(e).toBeInstanceOf(ApiError);
    expect([(e as ApiError).code, (e as ApiError).message]).toEqual(["LAST_ADMIN", ERROR_TEXTS.LAST_ADMIN]);
  });

  it("переназначение тикета: PATCH assign с инженером или null (в очередь)", async () => {
    const { repo, calls } = await repoWith(() => json(200, {}));
    await repo.assignTicket(42, 8);
    await repo.assignTicket(42, null);
    expect(calls.map((c) => [c.method, c.path, c.body])).toEqual([
      ["PATCH", "/tickets/42/assign", { assigned_engineer_id: 8 }],
      ["PATCH", "/tickets/42/assign", { assigned_engineer_id: null }],
    ]);
  });

  it("публикации: проверка аудитории ничего не публикует, лента — с фильтрами", async () => {
    const { repo, calls } = await repoWith((c) => json(200, c.path === "/notifications/audience-preview" ? { recipients: 3, devices: 4 } : page([])));
    const body = { type: "news" as const, message: "Тема\nТекст", target_vehicle_model_id: 2 };
    expect(await repo.previewNotificationAudience(body)).toEqual({ recipients: 3, devices: 4 });
    await repo.listPublishedNotifications({ type: "firmware", target_vehicle_model_id: 2 });
    expect(calls.map((c) => `${c.method} ${c.path}`)).toEqual(["POST /notifications/audience-preview", "GET /notifications/published"]);
    expect(calls[0].body).toEqual(body);
    expect(Object.fromEntries(calls[1].query)).toEqual({ type: "firmware", target_vehicle_model_id: "2" });
  });

  it("справочники и версии статьи — все страницы; версии — новые первыми", async () => {
    const { repo, calls } = await repoWith((c) => {
      const n = Number(c.query.get("page"));
      if (c.path === "/maintenance-regulations") return json(200, page([{ id: n }], n, 2));
      return json(200, page([{ version: n, title: `v${n}`, published_at: "2026-10-01T00:00:00Z" }], n, 3));
    });
    expect((await repo.listMaintenanceRegulations({ vehicle_model_id: 1, include_archived: true })).map((r) => r.id)).toEqual([1, 2]);
    expect(Object.fromEntries(calls[0].query)).toEqual({ vehicle_model_id: "1", include_archived: "true", page: "1", page_size: "100" });
    expect((await repo.listKnowledgeArticleRevisions(5)).map((r) => r.version)).toEqual([3, 2, 1]);
  });

  it("аналитика: период и фильтры уходят в запрос", async () => {
    const { repo, calls } = await repoWith(() => json(200, {}));
    await repo.getTicketResolutionStats({ date_from: "2026-03-01", date_to: "2026-03-31", vehicle_model_id: 3, category: "audio" });
    await repo.getMaintenanceConversionStats({ date_from: "2026-03-01", date_to: "2026-03-31" });
    expect(Object.fromEntries(calls[0].query)).toEqual({ date_from: "2026-03-01", date_to: "2026-03-31", vehicle_model_id: "3", category: "audio" });
    expect(calls[1].path).toBe("/analytics/maintenance-conversion");
  });
});
