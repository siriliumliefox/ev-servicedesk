// Сессия сотрудника в браузере (глава 21, ADR 0025 п. 1, 3, 6): access-токен — только в памяти,
// refresh — в `sessionStorage` вкладки (переживает перезагрузку, не переживает закрытие вкладки).
// Два клиента openapi-fetch: `client` — операции API (Bearer, на 401 — один общий refresh на все
// параллельные запросы и один повтор; неудачный refresh завершает сессию), `auth` — вход, refresh и
// выход как есть, без повтора (refresh внутри повтора ждал бы сам себя).
import createClient from "openapi-fetch";
import type { paths } from "../../api/schema.ts";
import { ApiError } from "../repository.ts";
import { ERROR_TEXTS, apiErrorFromResponse, networkError } from "../errors.ts";

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
  private readonly auth: Client;
  private readonly store: TokenStore;
  private readonly fetchImpl: typeof fetch;
  private access: string | null = null;
  private refreshing: Promise<string> | null = null;
  private readonly listeners = new Set<(end: SessionEnd) => void>();

  constructor(options: ApiSessionOptions) {
    this.baseUrl = options.baseUrl.replace(/\/$/, "");
    this.store = options.store;
    this.fetchImpl = options.fetch ?? globalThis.fetch.bind(globalThis);
    this.client = createClient<paths>({ baseUrl: this.baseUrl, fetch: (request) => this.send(request) });
    this.auth = createClient<paths>({ baseUrl: this.baseUrl, fetch: (request) => this.fetchImpl(request) });
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

  /** Вход сотрудника. Кто вошёл и пускать ли его — решает приложение по `getCurrentUser`. */
  async login(phone: string, password: string): Promise<void> {
    this.accept(await this.call(this.auth.POST("/auth/staff/login", { body: { phone, password } })));
  }

  /** Операция API через `client` (см. `call`). */
  request<T>(run: (client: Client) => Promise<Result<T>>): Promise<T> {
    return this.call(run(this.client));
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

  /**
   * Смена своего пароля (ADR 0029 п. 14): сервер отзывает прочие сессии и выдаёт новую пару для этой.
   * Неверный текущий — `PASSWORD_INVALID`, слабый новый — `VALIDATION_ERROR` по полю `new_password`.
   */
  async changePassword(currentPassword: string, newPassword: string): Promise<void> {
    const body = { current_password: currentPassword, new_password: newPassword };
    this.accept(await this.request((client) => client.POST("/auth/staff/password", { body })));
  }

  async logout(): Promise<void> {
    const token = this.store.get();
    if (token) {
      // Отзыв на сервере — по возможности: локальный выход не зависит от сети и истёкшего access-токена.
      const headers = this.access ? { Authorization: `Bearer ${this.access}` } : undefined;
      await this.auth.POST("/auth/logout", { body: { refresh_token: token }, headers }).catch(() => undefined);
    }
    this.end("logout");
  }

  private async doRefresh(): Promise<string> {
    const token = this.store.get();
    try {
      if (!token) throw new ApiError("UNAUTHORIZED", ERROR_TEXTS.UNAUTHORIZED, 401);
      this.accept(await this.call(this.auth.POST("/auth/refresh", { body: { refresh_token: token } })));
      return this.access!;
    } catch (error) {
      // Сеть — сессия не завершается (повторим позже); отказ сервера — сессия завершена.
      if (error instanceof ApiError && (error.status === 401 || error.status === 422)) this.end("expired");
      throw error;
    }
  }

  /** Ответ операции: ошибка → `ApiError` с текстом по коду, сетевой сбой → `NETWORK`; `204` — `undefined`. */
  private async call<T>(pending: Promise<Result<T>>): Promise<T> {
    let result: Result<T>;
    try {
      result = await pending;
    } catch (error) {
      if (error instanceof ApiError) throw error;
      throw networkError();
    }
    if (!result.response.ok) throw apiErrorFromResponse(result.response, result.error);
    return result.data as T;
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

  /** fetch операций API: Bearer, на 401 — refresh и один повтор. */
  private async send(request: Request): Promise<Response> {
    const retry = this.access !== null ? request.clone() : null;
    if (this.access) request.headers.set("Authorization", `Bearer ${this.access}`);
    const response = await this.fetchImpl(request);
    if (response.status !== 401 || !retry) return response;
    const token = await this.refresh(); // бросает UNAUTHORIZED, если сессия завершена
    retry.headers.set("Authorization", `Bearer ${token}`);
    return this.fetchImpl(retry);
  }
}
