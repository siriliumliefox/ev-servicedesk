// ApiSession и HttpEngineerRepository на подменённом fetch (глава 21, ADR 0025 п. 1, 6).
import { describe, expect, it } from "vitest";
import { ApiError } from "../repository.ts";
import { HttpEngineerRepository } from "./HttpEngineerRepository.ts";
import { ApiSession, memoryTokenStore, type SessionEnd } from "./session.ts";

const BASE = "http://api.test/v1";

type Handler = (request: Request) => Response | Promise<Response>;

const json = (status: number, body: unknown, headers: Record<string, string> = {}) =>
  new Response(body === null ? null : JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json", ...headers },
  });

const error = (status: number, code: string, details: unknown = null) =>
  json(status, { error: { code, message: "server text", details } });

const USER = { id: 7, phone: "+375291112233", role: "engineer", is_active: true, created_at: "2026-10-01T00:00:00Z" };

/** Сервер с ротацией: каждый вход и refresh выдаёт `access-N`/`refresh-N`, прежние недействительны. */
function server(routes: Record<string, Handler> = {}) {
  let generation = 0;
  let access: string | null = null;
  let refresh: string | null = null;
  const log: string[] = [];
  const issue = () => {
    generation += 1;
    access = `access-${generation}`;
    refresh = `refresh-${generation}`;
    return { access_token: access, refresh_token: refresh, expires_in: 900 };
  };
  const fetch = async (input: RequestInfo | URL, init?: RequestInit): Promise<Response> => {
    const request = input instanceof Request ? input : new Request(input, init);
    const url = new URL(request.url);
    const key = `${request.method} ${url.pathname.replace("/v1", "")}`;
    log.push(`${key} ${request.headers.get("Authorization") ?? "-"}`);
    if (key === "POST /auth/staff/login") {
      const body = (await request.json()) as { password: string };
      if (body.password !== "secret") return error(401, "UNAUTHORIZED");
      return json(200, { ...issue(), user: USER });
    }
    if (key === "POST /auth/refresh") {
      const body = (await request.json()) as { refresh_token: string };
      if (refresh === null || body.refresh_token !== refresh) return error(401, "UNAUTHORIZED");
      return json(200, issue());
    }
    if (key === "POST /auth/logout") return new Response(null, { status: 204 });
    const route = routes[key];
    if (!route) return error(404, "NOT_FOUND");
    if (access === null || request.headers.get("Authorization") !== `Bearer ${access}`) return error(401, "UNAUTHORIZED");
    return route(request);
  };
  return {
    fetch,
    log,
    /** Истёк access-токен (15 мин), refresh ещё действителен. */
    expireAccess: () => void (access = null),
    /** Сотрудник заблокирован / все сессии отозваны. */
    revoke: () => void ((access = null), (refresh = null)),
  };
}

async function signedIn(routes: Record<string, Handler> = {}) {
  const api = server(routes);
  const store = memoryTokenStore();
  const session = new ApiSession({ baseUrl: BASE, store, fetch: api.fetch });
  await session.login("+375291112233", "secret");
  return { api, store, session, repo: new HttpEngineerRepository(session) };
}

describe("ApiSession", () => {
  it("вход: access в памяти, refresh в хранилище; неверный пароль — UNAUTHORIZED с текстом по коду", async () => {
    const { session, store } = await signedIn();
    expect(session.accessToken).toBe("access-1");
    expect(store.get()).toBe("refresh-1");
    const fresh = new ApiSession({ baseUrl: BASE, store: memoryTokenStore(), fetch: server().fetch });
    const e = await fresh.login("+375291112233", "wrong").catch((x: unknown) => x as ApiError);
    expect([e.code, e.status, e.message]).toEqual(["UNAUTHORIZED", 401, "Сессия завершена, войдите снова."]);
  });

  it("401 у запроса — один refresh на параллельные запросы и повтор каждого", async () => {
    const { api, session, repo } = await signedIn({ "GET /me": () => json(200, USER) });
    api.expireAccess();
    const results = await Promise.all([repo.getCurrentUser(), repo.getCurrentUser(), repo.getCurrentUser()]);
    expect(results.map((u) => u.id)).toEqual([7, 7, 7]);
    expect(api.log.filter((l) => l.startsWith("POST /auth/refresh"))).toHaveLength(1);
    expect(session.accessToken).toBe("access-2");
    expect(api.log.filter((l) => l === "GET /me Bearer access-2")).toHaveLength(3);
  });

  it("refresh отклонён — сессия завершена (expired), хранилище очищено, ошибка UNAUTHORIZED", async () => {
    const { api, session, store, repo } = await signedIn({ "GET /me": () => json(200, USER) });
    const ends: SessionEnd[] = [];
    session.onEnd((end) => ends.push(end));
    api.revoke();
    const e = await repo.getCurrentUser().catch((x: unknown) => x as ApiError);
    expect(e.code).toBe("UNAUTHORIZED");
    expect(ends).toEqual(["expired"]);
    expect(store.get()).toBeNull();
    expect(session.accessToken).toBeNull();
  });

  it("восстановление после перезагрузки: refresh по сохранённому токену", async () => {
    const api = server({ "GET /me": () => json(200, USER) });
    const store = memoryTokenStore();
    const first = new ApiSession({ baseUrl: BASE, store, fetch: api.fetch });
    await first.login("+375291112233", "secret");
    const reloaded = new ApiSession({ baseUrl: BASE, store, fetch: api.fetch });
    expect(reloaded.canResume).toBe(true);
    await reloaded.resume();
    expect(reloaded.accessToken).toBe("access-2");
    expect((await new HttpEngineerRepository(reloaded).getCurrentUser()).id).toBe(7);
  });

  it("выход: отзыв refresh на сервере, событие logout", async () => {
    const { api, session, store } = await signedIn();
    const ends: SessionEnd[] = [];
    session.onEnd((end) => ends.push(end));
    await session.logout();
    expect(api.log.at(-1)).toMatch(/^POST \/auth\/logout/);
    expect([store.get(), session.accessToken, ends]).toEqual([null, null, ["logout"]]);
  });

  it("смена пароля: новая пара токенов этой сессии; неверный текущий и слабый новый — ошибки с текстом", async () => {
    let issued = 0;
    const { session, store } = await signedIn({
      "POST /auth/staff/password": async (request) => {
        const body = (await request.json()) as { current_password: string; new_password: string };
        if (body.current_password !== "secret") return error(400, "PASSWORD_INVALID");
        if (body.new_password === "aaaaaaaaaaaa") {
          return error(422, "VALIDATION_ERROR", { fields: [{ loc: ["body", "new_password"] }] });
        }
        issued += 1;
        return json(200, { access_token: `changed-${issued}`, refresh_token: `changed-r${issued}`, expires_in: 900 });
      },
    });
    const wrong = await session.changePassword("nope", "Mileage-Battery-Gomel").catch((x: unknown) => x as ApiError);
    expect([wrong.code, wrong.message]).toEqual(["PASSWORD_INVALID", "Неверный текущий пароль."]);
    const weak = await session.changePassword("secret", "aaaaaaaaaaaa").catch((x: unknown) => x as ApiError);
    expect([weak.code, weak.field]).toEqual(["VALIDATION_ERROR", "new_password"]);
    expect(weak.message).toMatch(/слишком простой/);
    await session.changePassword("secret", "Mileage-Battery-Gomel");
    expect([session.accessToken, store.get()]).toEqual(["changed-1", "changed-r1"]);
  });

  it("сеть недоступна — NETWORK, сессия не завершается", async () => {
    const store = memoryTokenStore();
    const failing = new ApiSession({
      baseUrl: BASE,
      store,
      fetch: () => Promise.reject(new TypeError("Failed to fetch")),
    });
    store.set("refresh-1");
    const e = await failing.resume().catch((x: unknown) => x as ApiError);
    expect(e.code).toBe("NETWORK");
    expect(store.get()).toBe("refresh-1");
    const e2 = await new HttpEngineerRepository(failing).getCurrentUser().catch((x: unknown) => x as ApiError);
    expect(e2.code).toBe("NETWORK");
  });
});

describe("HttpEngineerRepository", () => {
  it("ошибки контракта: текст по коду, поле 422, Retry-After", async () => {
    const { repo } = await signedIn({
      "POST /tickets/5/claim": () => error(409, "TICKET_ALREADY_CLAIMED"),
      "POST /tickets/5/messages": () => error(422, "VALIDATION_ERROR", { fields: [{ loc: ["body", "body"] }] }),
      "PATCH /tickets/5/status": () => error(429, "RATE_LIMITED", null),
    });
    const claim = await repo.claimTicket(5).catch((x: unknown) => x as ApiError);
    expect([claim.code, claim.status, claim.message]).toEqual([
      "TICKET_ALREADY_CLAIMED",
      409,
      "Тикет уже взял в работу другой инженер.",
    ]);
    const message = await repo.createTicketMessage(5, " ").catch((x: unknown) => x as ApiError);
    expect([message.code, message.field]).toEqual(["VALIDATION_ERROR", "body"]);
    const limited = await repo.updateTicketStatus(5, "resolved").catch((x: unknown) => x as ApiError);
    expect(limited.code).toBe("RATE_LIMITED");
  });

  it("история сообщений — все страницы по 100, after_id передаётся", async () => {
    const queries: string[] = [];
    const all = Array.from({ length: 230 }, (_, i) => ({ id: i + 1, body: `m${i + 1}` }));
    const { repo } = await signedIn({
      "GET /tickets/9/messages": (request) => {
        const q = new URL(request.url).searchParams;
        queries.push(q.toString());
        const after = Number(q.get("after_id") ?? 0);
        const page = Number(q.get("page"));
        const size = Number(q.get("page_size"));
        const rows = all.filter((m) => m.id > after);
        return json(200, {
          items: rows.slice((page - 1) * size, page * size),
          meta: { page, page_size: size, total_items: rows.length, total_pages: Math.ceil(rows.length / size) },
        });
      },
    });
    expect((await repo.listTicketMessages(9)).map((m) => m.id)).toEqual(all.map((m) => m.id));
    expect(queries).toEqual(["page=1&page_size=100", "page=2&page_size=100", "page=3&page_size=100"]);
    expect((await repo.listTicketMessages(9, { after_id: 228 })).map((m) => m.id)).toEqual([229, 230]);
  });

  it("фильтры доски уходят в запрос listTickets (resolved_since — контракт 1.10.0)", async () => {
    let query = "";
    const { repo } = await signedIn({
      "GET /tickets": (request) => {
        query = new URL(request.url).search;
        return json(200, { items: [], meta: { page: 2, page_size: 100, total_items: 0, total_pages: 0 } });
      },
    });
    await repo.listTickets({ status: "resolved", resolved_since: "2026-10-06T12:00:00.000Z", page: 2, page_size: 100 });
    expect(new URLSearchParams(query).get("resolved_since")).toBe("2026-10-06T12:00:00.000Z");
    expect(new URLSearchParams(query).get("status")).toBe("resolved");
  });
});
