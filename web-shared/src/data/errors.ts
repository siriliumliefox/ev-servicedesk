// Тексты ошибок API для UI — по коду `Error.code` контракта (ADR 0025 п. 6): `Error.message` сервера
// «для логов/поддержки, не для UI напрямую». Тест сверяет, что у каждого кода, который называют
// операции кабинета в docs/openapi.yaml, есть текст (errors.test.ts).
import { ApiError } from "./repository.ts";

export const ERROR_TEXTS: Readonly<Record<string, string>> = {
  NETWORK: "Нет соединения с сервером. Проверьте сеть и повторите.",
  BAD_REQUEST: "Сервер не принял запрос. Обновите страницу и повторите.",
  UNAUTHORIZED: "Сессия завершена, войдите снова.",
  TOKEN_REVOKED: "Сессия завершена, войдите снова.",
  FORBIDDEN: "Недостаточно прав для этого действия.",
  NOT_FOUND: "Объект не найден — возможно, его удалили или он больше вам не доступен.",
  METHOD_NOT_ALLOWED: "Сервер не поддерживает это действие. Обновите страницу.",
  CONFLICT: "Данные уже изменил другой пользователь. Обновите и повторите.",
  VALIDATION_ERROR: "Проверьте введённые данные.",
  RATE_LIMITED: "Слишком много запросов. Подождите и повторите.",
  INTERNAL_ERROR: "Сбой на сервере. Повторите попытку позже.",
  STAFF_PASSWORD_LOGIN: "Вход по паролю — только для сотрудников.",
  TICKET_ALREADY_CLAIMED: "Тикет уже взял в работу другой инженер.",
  INVALID_STATUS_TRANSITION: "Такой переход статуса недоступен — данные тикета обновлены.",
  TICKET_RESOLVED: "Тикет решён — чтобы написать клиенту, верните его в работу.",
  ASSIGNEE_NOT_ENGINEER: "Назначить можно только активного инженера.",
  ATTACHMENT_NOT_FOUND: "Вложение не найдено — загрузите файл заново.",
  ATTACHMENT_ALREADY_USED: "Вложение уже прикреплено к другому сообщению.",
  ATTACHMENT_TOO_LARGE: "Файл слишком большой.",
  ATTACHMENT_TYPE_NOT_ALLOWED: "Такой тип файла не поддерживается.",
  TOO_MANY_ATTACHMENTS: "Слишком много вложений — не больше 10.",
};

const FALLBACK = "Что-то пошло не так. Повторите попытку.";

export function errorTextFor(code: string): string {
  return ERROR_TEXTS[code] ?? FALLBACK;
}

/** Текст для UI — по коду; у ошибки валидации — `message` (прототип пишет его сам, HTTP-слой — по коду). */
export function errorText(error: unknown): string {
  if (!(error instanceof ApiError)) return FALLBACK;
  if (error.code === "VALIDATION_ERROR") return error.message || ERROR_TEXTS.VALIDATION_ERROR;
  return ERROR_TEXTS[error.code] ?? FALLBACK;
}

/**
 * Ответ сервера с ошибкой → `ApiError`: текст — по коду; поле 422 — последний элемент `loc`
 * (`details.fields[0].loc`); `Retry-After` при 429.
 */
export function apiErrorFromResponse(response: Response, body: unknown): ApiError {
  const error = (body as { error?: { code?: unknown; details?: unknown } } | null)?.error;
  const code = typeof error?.code === "string" ? error.code : response.status >= 500 ? "INTERNAL_ERROR" : "BAD_REQUEST";
  const fields = (error?.details as { fields?: { loc?: unknown[] }[] } | null | undefined)?.fields;
  const loc = fields?.[0]?.loc;
  const field = Array.isArray(loc) && loc.length > 0 ? String(loc[loc.length - 1]) : undefined;
  const retry = Number(response.headers.get("Retry-After"));
  return new ApiError(code, errorTextFor(code), response.status, field, Number.isFinite(retry) && retry > 0 ? retry : undefined);
}

export function networkError(): ApiError {
  return new ApiError("NETWORK", ERROR_TEXTS.NETWORK, 0);
}
