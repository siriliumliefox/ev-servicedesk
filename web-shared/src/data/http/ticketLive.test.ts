// Подписка на события тикета (docs/asyncapi.yaml): auth первым кадром, ready, коды закрытия,
// нарастающая пауза, скрытая вкладка (глава 21, ADR 0025 п. 6).
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ApiError, type TicketLiveHandlers } from "../repository.ts";
import { openTicketLive, webSocketUrl, type Visibility } from "./ticketLive.ts";

class FakeSocket {
  static all: FakeSocket[] = [];
  readonly sent: string[] = [];
  closedWith: number | null = null;
  onopen: (() => void) | null = null;
  onmessage: ((event: { data: string }) => void) | null = null;
  onclose: ((event: { code: number }) => void) | null = null;
  readonly url: string;

  constructor(url: string) {
    this.url = url;
    FakeSocket.all.push(this);
  }
  send(data: string) {
    this.sent.push(data);
  }
  close(code = 1000) {
    this.closedWith = code;
  }
  // Сервер:
  open() {
    this.onopen?.();
  }
  frame(value: unknown) {
    this.onmessage?.({ data: JSON.stringify(value) });
  }
  serverClose(code: number) {
    this.onclose?.({ code });
  }
}

const last = () => FakeSocket.all.at(-1)!;

function handlers() {
  const events: string[] = [];
  const h: TicketLiveHandlers = {
    onReady: () => events.push("ready"),
    onMessage: (m) => events.push(`message:${m.id}`),
    onTicket: (t) => events.push(`ticket:${t.status}`),
    onLost: () => events.push("lost"),
    onState: (s) => events.push(`state:${s}`),
  };
  return { h, events };
}

function fakeVisibility() {
  let hidden = false;
  let listener: () => void = () => undefined;
  const v: Visibility = {
    hidden: () => hidden,
    subscribe: (l) => {
      listener = l;
      return () => (listener = () => undefined);
    },
  };
  return {
    v,
    set(value: boolean) {
      hidden = value;
      listener();
    },
  };
}

function open(extra: { token?: () => string | null; refresh?: () => Promise<string> } = {}) {
  const { h, events } = handlers();
  const vis = fakeVisibility();
  const refresh = vi.fn(extra.refresh ?? (() => Promise.resolve("access-2")));
  const stop = openTicketLive({
    url: "ws://api.test/v1/tickets/5/ws",
    handlers: h,
    accessToken: extra.token ?? (() => "access-1"),
    refresh,
    WebSocketImpl: FakeSocket as unknown as typeof WebSocket,
    visibility: vis.v,
    random: () => 0.5,
  });
  return { stop, events, refresh, vis };
}

beforeEach(() => {
  FakeSocket.all = [];
  vi.useFakeTimers();
});
afterEach(() => vi.useRealTimers());

describe("openTicketLive", () => {
  it("auth первым кадром, ready → события; отписка закрывает 1000", () => {
    const { stop, events } = open();
    last().open();
    expect(JSON.parse(last().sent[0])).toEqual({ type: "auth", access_token: "access-1" });
    last().frame({ type: "ready" });
    last().frame({ type: "message.created", data: { id: 11 } });
    last().frame({ type: "ticket.updated", data: { status: "resolved" } });
    last().frame({ type: "unknown" });
    stop();
    expect(last().closedWith).toBe(1000);
    expect(events).toEqual(["state:connecting", "state:live", "ready", "message:11", "ticket:resolved"]);
  });

  it("обрыв — переподключение с нарастающей паузой 1, 2, 4 с; ready сбрасывает паузу", async () => {
    const { events } = open();
    last().serverClose(1011);
    expect(FakeSocket.all).toHaveLength(1);
    await vi.advanceTimersByTimeAsync(999);
    expect(FakeSocket.all).toHaveLength(1);
    await vi.advanceTimersByTimeAsync(1);
    expect(FakeSocket.all).toHaveLength(2);
    last().serverClose(1006);
    await vi.advanceTimersByTimeAsync(2000);
    expect(FakeSocket.all).toHaveLength(3);
    last().serverClose(1013);
    await vi.advanceTimersByTimeAsync(3999);
    expect(FakeSocket.all).toHaveLength(3);
    await vi.advanceTimersByTimeAsync(1);
    last().open();
    last().frame({ type: "ready" });
    last().serverClose(1006);
    await vi.advanceTimersByTimeAsync(1000);
    expect(FakeSocket.all).toHaveLength(5);
    expect(events.filter((e) => e === "ready")).toHaveLength(1);
  });

  it("4401 — refresh и сразу переподключение с новым токеном", async () => {
    let token = "access-1";
    const { refresh } = open({
      token: () => token,
      refresh: () => {
        token = "access-2";
        return Promise.resolve(token);
      },
    });
    last().open();
    last().serverClose(4401);
    await vi.advanceTimersByTimeAsync(0);
    expect(refresh).toHaveBeenCalledTimes(1);
    expect(FakeSocket.all).toHaveLength(2);
    last().open();
    expect(JSON.parse(last().sent[0]).access_token).toBe("access-2");
  });

  it("4401, сессия завершена (refresh — UNAUTHORIZED) — не переподключаться", async () => {
    open({ refresh: () => Promise.reject(new ApiError("UNAUTHORIZED", "", 401)) });
    last().serverClose(4401);
    await vi.advanceTimersByTimeAsync(120_000);
    expect(FakeSocket.all).toHaveLength(1);
  });

  it("4403 — доступ потерян: onLost, без переподключения", async () => {
    const { events } = open();
    last().serverClose(4403);
    await vi.advanceTimersByTimeAsync(120_000);
    expect(FakeSocket.all).toHaveLength(1);
    expect(events.at(-1)).toBe("lost");
  });

  it("4429 — не раньше чем через минуту", async () => {
    open();
    last().serverClose(4429);
    await vi.advanceTimersByTimeAsync(59_999);
    expect(FakeSocket.all).toHaveLength(1);
    await vi.advanceTimersByTimeAsync(1);
    expect(FakeSocket.all).toHaveLength(2);
  });

  it("вкладка скрыта 5 минут — соединение закрыто; вернулись — подключение и ready", async () => {
    const { vis, events } = open();
    last().open();
    last().frame({ type: "ready" });
    vis.set(true);
    await vi.advanceTimersByTimeAsync(4 * 60_000);
    vis.set(false);
    vis.set(true);
    await vi.advanceTimersByTimeAsync(5 * 60_000);
    expect(last().closedWith).toBe(1000);
    last().serverClose(1000); // закрытие по нашему запросу — без переподключения
    await vi.advanceTimersByTimeAsync(60_000);
    expect(FakeSocket.all).toHaveLength(1);
    vis.set(false);
    expect(FakeSocket.all).toHaveLength(2);
    last().open();
    last().frame({ type: "ready" });
    expect(events.filter((e) => e === "ready")).toHaveLength(2);
  });
});

describe("webSocketUrl", () => {
  it("тот же origin и полный адрес", () => {
    expect(webSocketUrl("/v1", "/tickets/5/ws", { protocol: "https:", host: "desk.example" })).toBe(
      "wss://desk.example/v1/tickets/5/ws",
    );
    expect(webSocketUrl("/v1", "/tickets/5/ws", { protocol: "http:", host: "localhost:5173" })).toBe(
      "ws://localhost:5173/v1/tickets/5/ws",
    );
    expect(webSocketUrl("http://127.0.0.1:18080/v1", "/tickets/5/ws")).toBe("ws://127.0.0.1:18080/v1/tickets/5/ws");
  });
});
