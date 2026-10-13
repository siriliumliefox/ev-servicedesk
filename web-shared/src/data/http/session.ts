// Сессия сотрудника в браузере (глава 21, ADR 0025 п. 1, 3, 6): access-токен — только в памяти,
// refresh — в `sessionStorage` вкладки (переживает перезагрузку, не переживает закрытие вкладки).
// Запросы идут через openapi-fetch с собственным fetch: Bearer, на 401 — один общий refresh на все
// параллельные запросы и один повтор запроса; неудачный refresh завершает сессию («Сессия завершена»).
import createClient from "openapi-fetch";
import type { paths } from "../../api/schema.ts";
import type { UserPublic } from "../models.ts";
import { ApiError } from "../repository.ts";
import { apiErrorFromResponse, networkError } from "../errors.ts";

/** Где лежит refresh-токен между перезагрузками. */
export interface TokenStore {
  get(): string | null;
  set(token: string | null): void;
}

/** `sessionStorage` вкладки; недоступен (приватный режим, запрет) — токен живёт до перезагрузки. */
export function sessionTokenStore(key: string): TokenStore {
  let memory: string | null = null;
  return {
    get() {
      try {
        return sessionStorage.getItem(key);
      } catch {
        return memory;
      }
    },
    set(token) {
      memory = token;
      try {
        if (token === null) sessionStorage.removeItem(key);
        else sessionStorage.setItem(key, token);
      } catch {
        /* остаётся в памяти */
      }
    },
  };
}

export function memoryTokenStore(): TokenStore {
  let token: string | null = null;
  return { get: () => token, set: (v) => void (token = v) };
}

/** Почему сессии нет: не входили, вышли сами, сервер отказал в обновлении (истекла, заблокирован). */
export type SessionEnd = "logout" | "expired";

export interface ApiSessionOptions {
  /** `/v1` (тот же origin, ADR 0025 п. 2) или полный адрес в тестах. */
  baseUrl: string;
  store: TokenStore;
  fetch?: typeof fetch;
}

type Tokens = { access_token: string; refresh_token: string };
type Client = ReturnType<typeof createClient<paths>>;
type Result<T> = { data?: T; error?: unknown; response: Response };

export class ApiSession {
  readonly baseUrl: string;
  readonly client: Client;
  private readonly store: TokenStore;
  private readonly fetchImpl: typeof fetch;
  private access: string | null = null;
  private refreshing: Promise<string> | null = null;
  private readonly listeners = new Set<(end: SessionEnd) => void>();

  constructor(options: ApiSessionOptions) {
    this.baseUrl = options.baseUrl.replace(/\/$/, "");
    this.store = options.store;
    const raw = options.fetch ?? globalThis.fetch.bind(globalThis);
    this.fetchImpl = raw;
    this.client = createClient<paths>({ baseUrl: this.baseUrl, fetch: (request) => this.send(request) });
  }

  get accessToken(): string | null {
    return this.access;
  }

  /** Есть refresh-токен прошлого входа в этой вкладке — сессию можно восстановить (`resume`). */
  get canResume(): boolean {
    return this.store.get() !== null;
  }

  /** Сессия завершилась не по нашему запросу (refresh отклонён) или выходом. */
  onEnd(listener: (end: SessionEnd) => void): () => void {
    this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  }

  async login(phone: string, password: string): Promise<UserPublic> {
    const data = await this.request((c) => c.POST("/auth/staff/login", { body: { phone, password } }));
    this.accept(data);
    return data.user as UserPublic;
  }

  /**
   * Операция API: ответ с ошибкой → `ApiError` с текстом по коду, сетевой сбой → `NETWORK`.
   * Для `204` возвращает `undefined`.
   */
  async request<T>(run: (client: Client) => Promise<Result<T>>): Promise<T> {
    let result: Result<T>;
    try {
      result = await run(this.client);
    } catch (error) {
      if (error instanceof ApiError) throw error;
      throw networkError();
    }
    if (!result.response.ok) throw apiErrorFromResponse(result.response, result.error);
    return result.data as T;
  }

  /** Восстановить сессию после перезагрузки: refresh по сохранённому токену. */
  async resume(): Promise<void> {
    await this.refresh();
  }

  /**
   * Новый access-токен. Параллельные вызовы ждут один запрос: refresh-токен одноразовый (ротация,
   * повтор отзывает все сессии — ADR 0013), второй параллельный refresh разлогинил бы пользователя.
   */
  refresh(): Promise<string> {
    this.refreshing ??= this.doRefresh().finally(() => {
      this.refreshing = null;
    });
    return this.refreshing;
  }

  async logout(): Promise<void> {
    const token = this.store.get();
    if (token) {
      // Отзыв на сервере — по возможности: локальный выход не зависит от сети.
      await this.client.POST("/auth/logout", { body: { refresh_token: token } }).catch(() => undefined);
    }
    this.end("logout");
  }

  private async doRefresh(): Promise<string> {
    const token = this.store.get();
    if (!token) {
      this.end("expired");
      throw new ApiError("UNAUTHORIZED", "Сессия завершена, войдите снова.", 401);
    }
    let response: Response;
    try {
      response = await this.fetchImpl(
        new Request(`${this.baseUrl}/auth/refresh`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ refresh_token: token }),
        }),
      );
    } catch {
      throw networkError(); // сеть — сессия не завершается, повторим позже
    }
    const body: unknown = await response.json().catch(() => null);
    if (!response.ok) {
      const error = apiErrorFromResponse(response, body);
      if (response.status === 401 || response.status === 422) this.end("expired");
      throw error;
    }
    this.accept(body as Tokens);
    return this.access!;
  }

  private accept(tokens: Tokens): void {
    this.access = tokens.access_token;
    this.store.set(tokens.refresh_token);
  }

  private end(reason: SessionEnd): void {
    const had = this.access !== null || this.store.get() !== null;
    this.access = null;
    this.store.set(null);
    if (had || reason === "expired") for (const listener of this.listeners) listener(reason);
  }

  /** fetch для openapi-fetch: Bearer, на 401 — refresh и один повтор. */
  private async send(request: Request): Promise<Response> {
    const authed = this.access !== null;
    const retry = authed ? request.clone() : null;
    if (this.access) request.headers.set("Authorization", `Bearer ${this.access}`);
    const response = await this.fetchImpl(request);
    if (response.status !== 401 || !retry || request.url.endsWith("/auth/logout")) return response;
    const token = await this.refresh(); // бросает UNAUTHORIZED, если сессия завершена
    retry.headers.set("Authorization", `Bearer ${token}`);
    return this.fetchImpl(retry);
  }
}
