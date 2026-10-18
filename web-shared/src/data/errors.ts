// Тексты ошибок API для UI — по коду `Error.code` контракта (ADR 0025 п. 6): `Error.message` сервера
// «для логов/поддержки, не для UI напрямую». Тест сверяет, что у каждого кода, который называют
// операции кабинета в docs/openapi.yaml, есть текст (errors.test.ts).
import { WEAK_PASSWORD_TEXT } from "./password.ts";
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
  // Замена и работы по агрегату (E-05, глава 23, ADR 0027 п. 14).
  REPLACED_AT_IN_FUTURE: "Дата замены не может быть позже сегодняшней.",
  PERFORMED_AT_IN_FUTURE: "Дата работы не может быть позже сегодняшней.",
  MILEAGE_AHEAD_OF_VEHICLE: "Пробег замены больше текущего пробега авто — уточните пробег у клиента.",
  MAINTENANCE_SUBJECT_REQUIRED: "Опишите работу: без агрегата нужен комментарий.",
  // Админ-панель (глава 22, ADR 0026): регламенты и справочник агрегатов.
  AGGREGATE_TYPE_EXISTS: "Агрегат с таким кодом уже есть.",
  AGGREGATE_TYPE_NOT_FOUND: "Такого агрегата нет в справочнике — обновите страницу.",
  VEHICLE_MODEL_NOT_FOUND: "Такой модели авто нет в справочнике — обновите страницу.",
  REGULATION_NOT_FOUND: "Регламент уже в архиве или удалён — обновите страницу.",
  // База знаний.
  CATEGORY_REQUIRED: "Выберите категорию ошибки.",
  FIRMWARE_RELEASE_NOT_FOUND: "Такой прошивки нет — выберите другую.",
  DECISION_TREE_INVALID: "В дереве решений есть ошибки — исправьте их перед публикацией.",
  ARTICLE_TYPE_HAS_NO_TREE: "Дерево решений есть только у статей «Устранение неполадок».",
  ARTICLE_PUBLISHED: "Дерево опубликованной статьи не меняется — сначала снимите статью с публикации.",
  DECISION_TREE_ROOT_EXISTS: "Корневой шаг уже есть — у дерева может быть только один.",
  INVALID_NEXT_NODE: "Вариант ведёт к шагу, которого нет в этом дереве.",
  DECISION_TREE_TOO_LARGE: "В дереве слишком много шагов.",
  DECISION_TREE_NODE_REFERENCED: "На этот шаг ведут варианты других шагов — сначала измените их.",
  // Публикации и прошивки.
  NOTIFICATION_TYPE_RESERVED: "Напоминания о ТО отправляет система — выберите другой тип.",
  FIRMWARE_RELEASE_REQUIRED: "Для уведомления о прошивке выберите релиз.",
  FIRMWARE_RELEASE_NOT_ALLOWED: "Релиз прошивки указывается только у уведомления о прошивке.",
  FIRMWARE_MODEL_MISMATCH: "Прошивка относится к другой модели.",
  FIRMWARE_VERSION_EXISTS: "Такая версия прошивки для модели уже опубликована.",
  RELEASED_AT_IN_FUTURE: "Дата выпуска не может быть в будущем.",
  // Пользователи.
  PHONE_ALREADY_REGISTERED: "Этот телефон уже зарегистрирован.",
  USER_NOT_FOUND: "Пользователь не найден — возможно, его данные удалены.",
  ROLE_CHANGE_NOT_ALLOWED: "Клиента нельзя сделать сотрудником: создайте сотрудника с другим телефоном.",
  LAST_ADMIN: "Это последний активный администратор — его нельзя понизить или заблокировать.",
  PASSWORD_NOT_ALLOWED: "У клиента нет пароля: он входит по SMS-коду.",
  // Смена своего пароля (глава 25, ADR 0029 п. 14).
  PASSWORD_INVALID: "Неверный текущий пароль.",
  SERVICE_UNAVAILABLE: "Сервис временно недоступен. Повторите попытку позже.",
  // Аналитика.
  INVALID_PERIOD: "Начало периода позже конца.",
  PERIOD_TOO_LONG: "Период — не длиннее 366 дней.",
};

const FALLBACK = "Что-то пошло не так. Повторите попытку.";

/** 422 по полю, где общий «Проверьте данные» не объясняет, что не так (глава 25, ADR 0029 пп. 10, 13). */
const FIELD_TEXTS: Readonly<Record<string, string>> = {
  password: WEAK_PASSWORD_TEXT,
  new_password: WEAK_PASSWORD_TEXT,
  content: "Проверьте текст статьи: только Markdown без HTML-тегов, не длиннее 50 000 символов.",
};

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
  const text = code === "VALIDATION_ERROR" && field ? (FIELD_TEXTS[field] ?? errorTextFor(code)) : errorTextFor(code);
  return new ApiError(code, text, response.status, field, Number.isFinite(retry) && retry > 0 ? retry : undefined);
}

export function networkError(): ApiError {
  return new ApiError("NETWORK", ERROR_TEXTS.NETWORK, 0);
}
