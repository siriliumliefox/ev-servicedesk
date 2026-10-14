/// <reference lib="dom" />
// Опора Playwright всех веб-наборов E2E (главы 21–23): запросы к API стека напрямую — от клиента (как мобильное
// приложение) и сотрудника, вход на экране сотрудника, проверка нарушений CSP. Подключается из e2e/*.ts:
// `@ev-servicedesk/web-shared/e2e` (только Node, в браузерную сборку не попадает; lib dom — для addInitScript).
import { expect, test, type Page } from "@playwright/test";

export { todayInMinsk } from "./src/data/format.ts";

export interface Account {
  phone: string;
  password: string;
}

const API = `${process.env.API_BASE_URL ?? "http://127.0.0.1:18080"}/v1`;

/** Запрос к API стека; `expected` — ожидаемый код ответа (иначе тест падает с телом ответа). */
export async function api<T>(method: string, path: string, token: string | null, body?: unknown, expected = 200): Promise<T> {
  const response = await fetch(`${API}${path}`, {
    method,
    headers: { ...(token ? { Authorization: `Bearer ${token}` } : {}), "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  const text = await response.text();
  expect(response.status, `${method} ${path} → ${response.status} ${text}`).toBe(expected);
  return (text ? JSON.parse(text) : undefined) as T;
}

/** Вход сотрудника по API: 200 — вошёл, 401 — пароль не подходит или учётная запись заблокирована. */
export async function staffLoginStatus(account: Account): Promise<number> {
  const response = await fetch(`${API}/auth/staff/login`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(account),
  });
  return response.status;
}

export async function staffToken(account: Account): Promise<string> {
  return (await api<{ access_token: string }>("POST", "/auth/staff/login", null, account)).access_token;
}

/** Статус «светофор» агрегата так, как его видит клиент. */
export async function aggregateStatus(clientToken: string, vehicleId: number, code: string): Promise<string> {
  const path = `/vehicles/${vehicleId}/aggregate-statuses`;
  const { items } = await api<{ items: { aggregate_type_code: string; status: string }[] }>("GET", path, clientToken);
  return items.find((s) => s.aggregate_type_code === code)?.status ?? "нет агрегата";
}

/**
 * Данные текущего браузера. Набор, который меняет общие данные стека (блокировка, взятие тикета, замена агрегата),
 * получает от seed по элементу на каждый проект Playwright (`--sets N`) — в порядке `projects` конфига.
 */
export function forBrowser<T>(sets: readonly T[], what: string): T {
  const { project, config } = test.info();
  const index = config.projects.findIndex((p) => p.name === project.name);
  const set = sets[index];
  if (set === undefined) throw new Error(`Нет данных «${what}» для ${project.name}: seed --sets ${index + 1}`);
  return set;
}

/** Нарушения CSP страниц под `guardCsp` — проверяются после каждого теста. */
const violations: string[] = [];

test.afterEach(() => {
  const found = violations.splice(0);
  expect(found, "нарушения CSP").toEqual([]);
});

/**
 * Собирать нарушения CSP страницы (securitypolicyviolation) — с директивой и источником. Без источника — инъекция
 * самого Playwright: в WebKit скриншот трассировки прячет курсор встроенным <style>; стиль или скрипт приложения
 * указал бы на файл сборки.
 */
export async function guardCsp(page: Page): Promise<void> {
  await page.addInitScript(() => {
    document.addEventListener("securitypolicyviolation", (e) => {
      if (!e.sourceFile) return;
      console.error(
        `CSP-VIOLATION ${e.violatedDirective} blocked=${e.blockedURI} source=${e.sourceFile}:${e.lineNumber} sample=${e.sample}`,
      );
    });
  });
  page.on("console", (message) => {
    if (message.text().startsWith("CSP-VIOLATION")) violations.push(message.text());
  });
}

/** Заполнить и отправить форму входа сотрудника (`StaffSessionGate`); результат проверяет тест. */
export async function submitLogin(page: Page, url: string, account: Account): Promise<void> {
  await page.goto(url);
  await page.getByLabel("Телефон").fill(account.phone);
  await page.getByLabel("Пароль").fill(account.password);
  await page.getByRole("button", { name: "Войти" }).click();
}
