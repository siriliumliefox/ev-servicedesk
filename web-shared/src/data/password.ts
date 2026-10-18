// Пароль сотрудника: границы длины — как схемы контракта (12–128); стойкость (zxcvbn ≥ 3, без цифр
// своего номера) проверяет сервер — ADR 0029 п. 13. Общие для админ-панели и смены своего пароля.
export const PASSWORD_MIN = 12;
export const PASSWORD_MAX = 128;

/** Ошибка длины пароля до запроса — как схема контракта (12–128). */
export function passwordProblem(password: string): string | null {
  if (password.length < PASSWORD_MIN) return `Пароль — не короче ${PASSWORD_MIN} символов`;
  if (password.length > PASSWORD_MAX) return `Пароль — не длиннее ${PASSWORD_MAX} символов`;
  return null;
}

/** Сервер отклонил пароль как простой (422 VALIDATION_ERROR по полю пароля). */
export const WEAK_PASSWORD_TEXT =
  "Пароль слишком простой: используйте фразу из нескольких слов или случайный набор символов, без цифр своего номера.";
