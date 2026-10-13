// События тикета по WebSocket `/v1/tickets/{id}/ws` (docs/asyncapi.yaml, ADR 0017 п. 9; браузер —
// ADR 0025 п. 6). Авторизация — первым кадром `auth` (токен в URL не передаётся), после `ready` экран
// догружает пропущенное через REST. Закрытия: 4401 — refresh и переподключение; 4403 — доступ потерян,
// не переподключаться; 4429 — не раньше чем через минуту; прочие — нарастающая пауза до 30 с.
// Вкладка скрыта дольше 5 минут — соединение закрывается и открывается снова при возврате.
import type { Ticket, TicketMessage } from "../models.ts";
import { ApiError, type TicketLiveHandlers } from "../repository.ts";

export interface TicketLiveOptions {
  url: string;
  handlers: TicketLiveHandlers;
  accessToken(): string | null;
  /** Новый access-токен; `UNAUTHORIZED` — сессия завершена (её закрывает `ApiSession`). */
  refresh(): Promise<string>;
  WebSocketImpl?: typeof WebSocket;
  /** Видимость вкладки; по умолчанию — `document`. */
  visibility?: Visibility;
  random?: () => number;
}

export interface Visibility {
  hidden(): boolean;
  subscribe(listener: () => void): () => void;
}

const MAX_DELAY_MS = 30_000;
const RATE_LIMIT_DELAY_MS = 60_000;
const HIDDEN_CLOSE_MS = 5 * 60_000;

const documentVisibility: Visibility = {
  hidden: () => typeof document !== "undefined" && document.visibilityState === "hidden",
  subscribe(listener) {
    if (typeof document === "undefined") return () => undefined;
    document.addEventListener("visibilitychange", listener);
    return () => document.removeEventListener("visibilitychange", listener);
  },
};

type Frame =
  | { type: "ready" }
  | { type: "message.created"; data: TicketMessage }
  | { type: "ticket.updated"; data: Ticket };

/** Открывает подписку; возвращает отписку (закрывает соединение и все таймеры). */
export function openTicketLive(options: TicketLiveOptions): () => void {
  const { handlers } = options;
  const Socket = options.WebSocketImpl ?? WebSocket;
  const visibility = options.visibility ?? documentVisibility;
  const random = options.random ?? Math.random;

  let socket: WebSocket | null = null;
  let stopped = false;
  let paused = false;
  let failures = 0;
  let retryTimer: ReturnType<typeof setTimeout> | null = null;
  let hiddenTimer: ReturnType<typeof setTimeout> | null = null;

  const state = (value: "connecting" | "live" | "offline") => handlers.onState?.(value);

  const clearRetry = () => {
    if (retryTimer !== null) clearTimeout(retryTimer);
    retryTimer = null;
  };

  const schedule = (delayMs: number) => {
    clearRetry();
    state("offline");
    retryTimer = setTimeout(connect, delayMs);
  };

  /** 1, 2, 4 … 30 с с разбросом ±20 %: переподключения вкладок не идут залпом. */
  const backoff = () => {
    const base = Math.min(MAX_DELAY_MS, 1000 * 2 ** failures);
    failures += 1;
    return Math.round(base * (0.8 + 0.4 * random()));
  };

  function connect() {
    retryTimer = null;
    if (stopped || paused) return;
    state("connecting");
    const ws = new Socket(options.url);
    socket = ws;
    ws.onopen = () => {
      const token = options.accessToken();
      // Без токена сервер закроет 4401 через 5 с — сразу закрываем сами тем же кодом.
      if (token) ws.send(JSON.stringify({ type: "auth", access_token: token }));
      else ws.close(4401);
    };
    ws.onmessage = (event) => {
      let frame: Frame;
      try {
        frame = JSON.parse(String(event.data)) as Frame;
      } catch {
        return;
      }
      if (frame.type === "ready") {
        failures = 0;
        state("live");
        handlers.onReady();
      } else if (frame.type === "message.created") handlers.onMessage(frame.data);
      else if (frame.type === "ticket.updated") handlers.onTicket(frame.data);
    };
    ws.onclose = (event) => {
      if (socket !== ws) return;
      socket = null;
      if (stopped || paused) return;
      onClosed(event.code);
    };
  }

  function onClosed(code: number) {
    if (code === 4403) {
      stopped = true;
      state("offline");
      handlers.onLost();
      return;
    }
    if (code === 4429) return schedule(Math.max(RATE_LIMIT_DELAY_MS, backoff()));
    if (code === 4401) {
      state("offline");
      const delay = failures === 0 ? 0 : backoff();
      if (failures === 0) failures = 1;
      options.refresh().then(
        () => !stopped && schedule(delay),
        (error: unknown) => {
          // Сессия завершена — экран входа покажет приложение; сеть — повторим позже.
          if (error instanceof ApiError && error.code === "NETWORK") schedule(backoff());
        },
      );
      return;
    }
    schedule(backoff());
  }

  const onVisibility = () => {
    if (visibility.hidden()) {
      hiddenTimer ??= setTimeout(() => {
        hiddenTimer = null;
        paused = true;
        clearRetry();
        socket?.close(1000);
        socket = null;
        state("offline");
      }, HIDDEN_CLOSE_MS);
      return;
    }
    if (hiddenTimer !== null) clearTimeout(hiddenTimer);
    hiddenTimer = null;
    if (paused) {
      paused = false;
      failures = 0;
      connect();
    }
  };
  const unsubscribeVisibility = visibility.subscribe(onVisibility);

  connect();

  return () => {
    stopped = true;
    clearRetry();
    if (hiddenTimer !== null) clearTimeout(hiddenTimer);
    unsubscribeVisibility();
    const ws = socket;
    socket = null;
    ws?.close(1000);
  };
}

/** Адрес WebSocket по базовому адресу API: `/v1` → `ws(s)://<этот хост>/v1`, `http(s)://…` → `ws(s)://…`. */
export function webSocketUrl(baseUrl: string, path: string, location?: { protocol: string; host: string }): string {
  if (/^https?:\/\//.test(baseUrl)) return baseUrl.replace(/^http/, "ws") + path;
  const loc = location ?? globalThis.location;
  return `${loc.protocol === "https:" ? "wss" : "ws"}://${loc.host}${baseUrl}${path}`;
}
