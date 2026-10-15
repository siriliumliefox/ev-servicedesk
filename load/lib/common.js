// Общее для сценариев k6 (глава 24, ADR 0028): данные сида, сессии с обновлением токенов,
// запросы с метками «чтение/изменение» и фазы прогона, учёт ошибок, нормативы.
//
// Ошибка (ADR 0028 п. 3) — 5xx, тайм-аут (> 10 с) или неожиданный 4xx; ожидаемые ответы
// (например, 409 при одновременном взятии тикета) перечисляются у запроса.

import encoding from 'k6/encoding';
import exec from 'k6/execution';
import http from 'k6/http';
import { SharedArray } from 'k6/data';
import { sleep } from 'k6';
import { Rate, Trend } from 'k6/metrics';

export const BASE = `${__ENV.BASE_URL || 'http://backend:8000'}/v1`;
export const WS_BASE = BASE.replace(/^http/, 'ws');
export const PROFILE = __ENV.LOAD_PROFILE || 'full';
// Поисковый запрос базы знаний — кириллица в URL только закодированной.
export const SEARCH = encodeURIComponent('руководство');
const SEED_PATH = __ENV.SEED || '/seed/seed.json';

// Сид читается один раз и делится между VU (SharedArray — только чтение).
const seedFile = () => JSON.parse(open(SEED_PATH));
export const clients = new SharedArray('clients', () => seedFile().clients);
export const engineerSessions = new SharedArray('engineers', () =>
  seedFile().engineers.flatMap((u) => u.sessions.map((s) => ({ id: u.id, ...s }))),
);
export const adminSessions = new SharedArray('admins', () =>
  seedFile().admins.flatMap((u) => u.sessions.map((s) => ({ id: u.id, ...s }))),
);
export const meta = new SharedArray('meta', () => {
  const s = seedFile();
  return [{ articles: s.articles, firmwareNew: s.firmware_new, limitsStaffPhone: s.limits_staff_phone }];
})[0];

export const errors = new Rate('errors');
export const chatDelivery = new Trend('chat_delivery', true);

// Нормативы времени ответа (ADR 0028 п. 3). Фаза peak — только доля ошибок и p99 ≤ 2 с;
// recovery — первые 2 мин после пика, время ответа не нормируется (проверяется возврат).
export function thresholds(phases = ['steady']) {
  const t = { chat_delivery: ['p(95)<1000'] };
  for (const phase of phases) {
    t[`errors{phase:${phase}}`] = ['rate<0.01'];
    if (phase === 'steady') {
      t[`http_req_duration{kind:read,phase:${phase}}`] = ['p(95)<300', 'p(99)<1000'];
      t[`http_req_duration{kind:write,phase:${phase}}`] = ['p(95)<500', 'p(99)<1500'];
    } else if (phase === 'peak') {
      t[`http_req_duration{phase:${phase}}`] = ['p(99)<2000'];
    }
  }
  return t;
}

// Фаза по времени от начала прогона: [{from: секунд, phase}], по возрастанию from.
let phasePlan = [{ from: 0, phase: 'steady' }];
let startedAt = Date.now();
export function setPhases(plan, start) {
  phasePlan = plan;
  startedAt = start;
}
export function phaseNow() {
  const elapsed = (Date.now() - startedAt) / 1000;
  let current = phasePlan[0].phase;
  for (const p of phasePlan) if (elapsed >= p.from) current = p.phase;
  return current;
}

// Свой «IP» у каждого пользователя: прокси production передаёт его в X-Forwarded-For (п. 8).
export function ipFor(n) {
  return `10.${(n >> 16) & 255}.${(n >> 8) & 255}.${n & 255}`;
}

function jwtExp(token) {
  const payload = JSON.parse(encoding.b64decode(token.split('.')[1], 'rawurl', 's'));
  return payload.exp * 1000;
}

// Сессия пользователя: access обновляется заранее; refresh-токен одноразовый и есть только у
// этой сессии (номер VU или итерации), поэтому гонок ротации нет.
export class Session {
  constructor(tokens, ipIndex) {
    this.access = tokens.access;
    this.refreshToken = tokens.refresh;
    this.exp = jwtExp(tokens.access);
    this.index = ipIndex;
    this.ip = ipFor(ipIndex);
    this.id = tokens.id;
  }

  ensureFresh(marginSeconds = 60) {
    if (this.exp - Date.now() > marginSeconds * 1000) return;
    const r = request('POST', '/auth/refresh', { refresh_token: this.refreshToken }, {
      name: 'auth.refresh', kind: 'write', session: null, ip: this.ip,
    });
    if (r.status === 200) {
      const body = r.json();
      this.access = body.access_token;
      this.refreshToken = body.refresh_token;
      this.exp = jwtExp(body.access_token);
    }
  }
}

// Запрос с метками и учётом ошибок. opts: name (метка операции), kind (read|write),
// session, ip, expected (ожидаемые коды), headers.
export function request(method, path, body, opts) {
  const session = opts.session;
  if (session) session.ensureFresh();
  const headers = { 'X-Forwarded-For': session ? session.ip : opts.ip, ...(opts.headers || {}) };
  if (session) headers.Authorization = `Bearer ${session.access}`;
  if (body !== null && body !== undefined) headers['Content-Type'] = 'application/json';
  const tags = { name: opts.name, kind: opts.kind, phase: phaseNow() };
  const url = path.startsWith('http') ? path : `${BASE}${path}`;
  const payload = body === null || body === undefined ? null : JSON.stringify(body);
  const r = http.request(method, url, payload, { headers, tags, timeout: '10s' });
  const expected = opts.expected || [method === 'POST' ? [200, 201] : [200, 204]].flat();
  errors.add(!expected.includes(r.status), tags);
  return r;
}

export const get = (path, name, session, extra = {}) =>
  request('GET', path, null, { name, kind: 'read', session, ...extra });
export const write = (method, path, body, name, session, extra = {}) =>
  request(method, path, body, { name, kind: 'write', session, ...extra });

export function json(r, fallback = null) {
  try {
    return r.json();
  } catch (_) {
    return fallback;
  }
}

// Исключение в сценарии — тоже ошибка прогона, а не тихо оборванная итерация (и без паузы:
// иначе VU крутит пустые итерации).
export function guarded(fn) {
  return (...args) => {
    try {
      return fn(...args);
    } catch (e) {
      errors.add(true, { name: 'script', kind: 'script', phase: phaseNow() });
      console.error(`Сбой сценария: ${e}`);
      sleep(1);
      return undefined;
    }
  };
}

export function pick(items) {
  return items[Math.floor(Math.random() * items.length)];
}

export function think(min = 5, max = 15) {
  return min + Math.random() * (max - min);
}

// Сессии VU по номеру в тесте: у каждого VU своя (п. 7). Клиенты 0…1499 — для VU,
// с 1500 — для итераций всплеска (peak.js).
export const BURST_CLIENT_OFFSET = 1500;
export function clientSession() {
  const n = exec.vu.idInTest - 1;
  return new Session(clients[n], n);
}
export function engineerSession() {
  const n = exec.vu.idInTest - 1;
  return new Session(engineerSessions[n], 100000 + n);
}
export function adminSession() {
  const n = exec.vu.idInTest - 1;
  return new Session(adminSessions[n], 200000 + n);
}

export function summaryTo(data, extra = {}) {
  return { '/out/summary.json': JSON.stringify({ ...extra, metrics: data.metrics }, null, 1) };
}
