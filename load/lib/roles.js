// Поведение ролей (глава 24, ADR 0028 п. 2, 10): одно действие пользователя — один вызов
// функции, между действиями — пауза на чтение экрана (в среднем 10 с, думает вызывающий).

import exec from 'k6/execution';
import http from 'k6/http';
import { sleep } from 'k6';
import { clearInterval, setInterval, setTimeout } from 'k6/timers';
import { WebSocket } from 'k6/websockets';
import { Counter } from 'k6/metrics';

// Карточки тикетов, взятых другим инженером после загрузки доски (ожидаемые 404).
const staleCards = new Counter('stale_board_cards');

import {
  BURST_CLIENT_OFFSET, SEARCH, Session, WS_BASE, chatDelivery, clients, errors, get, json, meta, phaseNow,
  pick, write,
} from './common.js';

const CATEGORIES = ['navigation', 'audio', 'sim', 'app_crash', 'maintenance'];
const PHOTO = new Uint8Array(500 * 1024).fill(0xff).buffer; // ~500 КБ «фото» (Q19)

// ---------- Клиент (мобильное приложение) ----------

export class ClientState {
  constructor(session, client) {
    this.s = session;
    this.vehicleId = client.vehicle_id;
    this.mileage = null;
    this.ticketIds = [];
    this.pushToken = `load-${client.id}`;
  }
}

function home(c) {
  get('/me', 'users.me', c.s);
  const r = get('/vehicles', 'vehicles.list', c.s);
  const v = (json(r, { items: [] }).items || [])[0];
  if (v) c.mileage = v.mileage;
}

function myTickets(c) {
  const r = get('/tickets?page_size=20', 'tickets.list.client', c.s);
  c.ticketIds = (json(r, { items: [] }).items || []).map((t) => t.id);
}

function ticketCard(c) {
  if (!c.ticketIds.length) return myTickets(c);
  const id = pick(c.ticketIds);
  get(`/tickets/${id}`, 'tickets.get', c.s);
  get(`/tickets/${id}/messages?page_size=50`, 'tickets.messages.list', c.s);
}

export function createTicket(c, withPhoto) {
  const body = {
    vehicle_id: c.vehicleId,
    category: pick(CATEGORIES),
    description: `Нагрузка: не работает ${Math.random().toString(36).slice(2, 8)}`,
  };
  if (withPhoto) {
    const p = write('POST', '/uploads/presign', { file_name: 'photo.jpg', file_type: 'photo' },
      'uploads.presign', c.s);
    if (p.status === 200) {
      const { upload_url: uploadUrl, file_url: fileUrl } = p.json();
      const put = http.put(uploadUrl, PHOTO, {
        headers: { 'Content-Type': 'image/jpeg' },
        tags: { name: 's3.put', kind: 's3', phase: phaseNow() },
        timeout: '30s',
      });
      errors.add(put.status !== 200, { name: 's3.put', kind: 's3', phase: phaseNow() });
      body.attachments = [{ file_url: fileUrl, file_type: 'photo' }];
    }
  }
  const r = write('POST', '/tickets', body, 'tickets.create', c.s, { expected: [201] });
  if (r.status === 201) c.ticketIds.unshift(r.json().id);
  return r;
}

// Набор действий клиента с весами (сумма — 1000).
const CLIENT_ACTIONS = [
  [180, home],
  [180, (c) => get(`/vehicles/${c.vehicleId}/aggregate-statuses`, 'aggregates.statuses', c.s)],
  [70, (c) => get(`/vehicles/${c.vehicleId}/maintenance-records`, 'vehicles.maintenance', c.s)],
  [150, (c) => get('/notifications?page_size=20', 'notifications.list', c.s)],
  [100, myTickets],
  [100, ticketCard],
  [100, (c) => get('/knowledge-articles?is_published=true&page_size=20', 'kb.list', c.s)],
  [70, (c) => get(`/knowledge-articles/${pick(meta.articles)}`, 'kb.get', c.s)],
  [30, (c) => get(`/knowledge-articles?is_published=true&search=${SEARCH}`, 'kb.search', c.s)],
  [18, (c) => {
    if (c.mileage === null) return home(c);
    c.mileage += 1 + Math.floor(Math.random() * 50);
    write('PATCH', `/vehicles/${c.vehicleId}/mileage`, { mileage: c.mileage }, 'vehicles.mileage',
      c.s);
  }],
  [2, (c) => createTicket(c, Math.random() < 0.2)],
];

function weighted(actions) {
  let roll = Math.random() * 1000;
  for (const [weight, fn] of actions) {
    roll -= weight;
    if (roll < 0) return fn;
  }
  return actions[0][1];
}

export function clientAction(c) {
  weighted(CLIENT_ACTIONS)(c);
}

// ---------- Инженер (веб-кабинет) ----------

export class EngineerState {
  constructor(session) {
    this.s = session;
    this.board = { new: [], in_progress: [], waiting_vendor: [], resolved: [] };
    this.lastPoll = 0;
  }
}

// Опрос канбана: колонка = запрос по статусу (ADR 0025 п. 8), «Решено» — за 7 дней.
export function pollBoard(e) {
  const since = new Date(Date.now() - 7 * 86400 * 1000).toISOString();
  for (const status of Object.keys(e.board)) {
    const extra = status === 'resolved' ? `&resolved_since=${encodeURIComponent(since)}` : '';
    const r = get(`/tickets?status=${status}&page_size=100${extra}`, `tickets.board.${status}`, e.s);
    e.board[status] = (json(r, { items: [] }).items || []);
  }
  e.lastPoll = Date.now();
}

function mine(e) {
  return e.board.in_progress.filter((t) => t.assigned_engineer_id === e.s.id);
}

const ENGINEER_ACTIONS = [
  [450, (e) => {
    const t = pick([...e.board.new, ...e.board.in_progress]);
    if (!t) return;
    // Доска устаревает до 15 с: новый тикет мог взять другой инженер, и он больше не виден
    // (RBAC-04, ADR 0017) — 404 здесь ожидаемый исход гонки, как 409 при взятии.
    const fromQueue = t.status === 'new';
    const card = get(`/tickets/${t.id}`, 'tickets.get', e.s,
      { expected: fromQueue ? [200, 404] : [200], headers: {} });
    if (card.status === 404) {
      staleCards.add(1);
      return;
    }
    get(`/tickets/${t.id}/messages?page_size=50`, 'tickets.messages.list', e.s);
    if (t.vehicle_id) {
      get(`/vehicles/${t.vehicle_id}/aggregate-statuses`, 'aggregates.statuses', e.s);
      get(`/vehicles/${t.vehicle_id}/maintenance-records`, 'vehicles.maintenance', e.s);
    }
  }],
  [200, (e) => {
    const t = pick(e.board.new);
    // 409 — тикет уже взял другой инженер: ожидаемый исход гонки (ADR 0017).
    if (t) write('POST', `/tickets/${t.id}/claim`, null, 'tickets.claim', e.s, { expected: [200, 409] });
  }],
  [200, (e) => {
    const t = pick(mine(e));
    if (t) {
      write('POST', `/tickets/${t.id}/messages`, { body: 'Проверьте, пожалуйста, ещё раз.' },
        'tickets.messages.create', e.s, { expected: [201, 409, 429] });
    }
  }],
  [100, (e) => {
    const t = pick(mine(e));
    if (t) {
      write('PATCH', `/tickets/${t.id}/status`, { status: pick(['waiting_vendor', 'resolved']) },
        'tickets.status', e.s, { expected: [200, 409] });
    }
  }],
  [50, (e) => get(`/knowledge-articles?is_published=true&search=${SEARCH}`, 'kb.search', e.s)],
];

export function engineerAction(e) {
  if (Date.now() - e.lastPoll >= 15000) pollBoard(e);
  else weighted(ENGINEER_ACTIONS)(e);
}

// ---------- Администратор (админ-панель) ----------

function period() {
  const to = new Date();
  const from = new Date(to.getTime() - 30 * 86400 * 1000);
  const d = (x) => x.toISOString().slice(0, 10);
  return `date_from=${d(from)}&date_to=${d(to)}`;
}

const ADMIN_ACTIONS = [
  [400, (a) => {
    get(`/analytics/ticket-resolution?${period()}`, 'analytics.resolution', a);
    get(`/analytics/problem-models?${period()}`, 'analytics.problem_models', a);
    get(`/analytics/maintenance-conversion?${period()}`, 'analytics.conversion', a);
  }],
  [200, (a) => get('/notifications/published?page_size=20', 'notifications.published', a)],
  [200, (a) => get('/users?page_size=50', 'users.list', a)],
  [200, (a) => get('/knowledge-articles?page_size=50', 'kb.list.admin', a)],
];

export function adminAction(a) {
  weighted(ADMIN_ACTIONS)(a);
}

// Рассылка всем клиентам (новость: прошивка адресуется одной модели, ADR 0019). Время
// доставки меряет load/run.sh по БД (ADR 0028 п. 12).
export function broadcast(a) {
  write('POST', '/notifications', { type: 'news', message: 'Нагрузка: новость для всех' },
    'notifications.create', a, { expected: [201] });
}

// ---------- Всплеск после рассылки: клиент открывает приложение (peak.js) ----------

export function burstSession(withTicket) {
  const n = BURST_CLIENT_OFFSET + exec.scenario.iterationInTest;
  const client = clients[n % clients.length];
  const c = new ClientState(new Session(client, n), client);
  const list = get('/notifications?page_size=20', 'notifications.list', c.s);
  const latest = (json(list, { items: [] }).items || [])[0];
  if (latest) {
    write('POST', `/notifications/${latest.id}/opened`, { token: c.pushToken },
      'notifications.opened', c.s, { expected: [204] });
    write('PATCH', `/notifications/${latest.id}/read`, null, 'notifications.read', c.s,
      { expected: [204] });
  }
  sleep(1 + Math.random());
  home(c);
  get(`/vehicles/${c.vehicleId}/aggregate-statuses`, 'aggregates.statuses', c.s);
  sleep(1 + Math.random());
  get(`/vehicles/${c.vehicleId}/maintenance-records`, 'vehicles.maintenance', c.s);
  if (withTicket) {
    sleep(2 + Math.random() * 3);
    createTicket(c, Math.random() < 0.2);
  }
}

// ---------- Чат по WebSocket (ADR 0028 п. 3: доставка p95 ≤ 1 с) ----------

// Клиент держит подключение к своему тикету и шлёт сообщение раз в intervalSeconds; своё же
// сообщение приходит ему событием message.created (AsyncAPI) — так меряется путь
// «запись → Redis → WebSocket». Подключение живёт holdSeconds, затем переподключение.
export function chatSession(c, holdSeconds, intervalSeconds) {
  c.s.ensureFresh(holdSeconds + 60);
  if (!c.ticketIds.length) createTicket(c, false);
  const ticketId = c.ticketIds[0];
  if (!ticketId) return;
  const ws = new WebSocket(`${WS_BASE}/tickets/${ticketId}/ws`, null, {
    headers: { 'X-Forwarded-For': c.s.ip },
    tags: { name: 'tickets.ws' },
  });
  const sent = {};
  let timer = null;
  let closing = false;
  // Закрываем один раз: повторный close() даёт ошибку «close sent» (наш артефакт, не сервера).
  const close = () => {
    if (closing) return;
    closing = true;
    if (timer) clearInterval(timer);
    ws.close();
  };
  const send = () => {
    if (closing) return;
    const marker = `${exec.vu.idInTest}-${Date.now()}`;
    sent[marker] = Date.now();
    const r = write('POST', `/tickets/${ticketId}/messages`, { body: `Чат ${marker}` },
      'tickets.messages.create', c.s, { expected: [201, 409, 429] });
    if (r.status === 409) {
      // Инженер решил тикет (409 TICKET_RESOLVED) — следующий раз клиент создаст новый.
      delete sent[marker];
      c.ticketIds = c.ticketIds.filter((id) => id !== ticketId);
      close();
    }
  };
  ws.onopen = () => ws.send(JSON.stringify({ type: 'auth', access_token: c.s.access }));
  ws.onmessage = (event) => {
    const frame = JSON.parse(event.data);
    if (frame.type === 'ready') {
      send();
      timer = setInterval(send, intervalSeconds * 1000);
    } else if (frame.type === 'message.created') {
      const marker = (frame.data.body || '').replace('Чат ', '');
      if (sent[marker]) {
        chatDelivery.add(Date.now() - sent[marker], { phase: phaseNow() });
        delete sent[marker];
      }
    }
  };
  ws.onerror = (e) => {
    errors.add(true, { name: 'tickets.ws', kind: 'ws', phase: phaseNow(), code: 'error' });
    console.warn(`WebSocket тикета ${ticketId}: ${e && e.error}`);
  };
  ws.onclose = (event) => {
    closing = true;
    if (timer) clearInterval(timer);
    // Ожидаемое закрытие — наше (1000/1005); 4401/1011/1013 и прочее — ошибка (ADR 0028 п. 3).
    const ok = !event || !event.code || event.code === 1000 || event.code === 1005;
    errors.add(!ok, { name: 'tickets.ws', kind: 'ws', phase: phaseNow(), code: String(event && event.code) });
  };
  setTimeout(close, holdSeconds * 1000);
}

