// Замер по операциям (глава 24, ADR 0028 п. 13): каждая операция отдельно, 2 мин,
// 20 пользователей, пауза 1 с — находим самые медленные до смешанной нагрузки. Пороги здесь не
// проверяются: итог — таблица p50/p95/p99 по меткам name (load/analyze.py).

import exec from 'k6/execution';
import { sleep } from 'k6';

import {
  PROFILE, SEARCH, Session, adminSession, guarded, clientSession, clients, engineerSession, get, json, meta, pick,
  summaryTo, write,
} from '../lib/common.js';
import { ClientState, EngineerState, createTicket, pollBoard } from '../lib/roles.js';

const FULL = PROFILE !== 'ci';
const VUS = FULL ? 20 : 4;
const DURATION = FULL ? 120 : 20;
const GAP = 10;

// Клиент на каждую итерацию — для операций с лимитом на пользователя в час (тикеты, presign).
// У каждой такой операции свой диапазон клиентов: refresh-токен одноразовый.
// Диапазон — половина сида от offset (offset — доля сида), чтобы влезть и в сид ci (5000).
function iterationClient(share) {
  const half = Math.floor(clients.length / 2);
  const n = Math.floor(clients.length * share) + (exec.scenario.iterationInTest % (half - 1500));
  return new ClientState(new Session(clients[n], n), clients[n]);
}

let c = null;
let e = null;
let a = null;
const cl = () => c || (c = new ClientState(clientSession(), clients[exec.vu.idInTest - 1]));
const en = () => e || (e = new EngineerState(engineerSession()));
const ad = () => a || (a = adminSession());
const range = () => {
  const to = new Date();
  const d = (x) => x.toISOString().slice(0, 10);
  return `date_from=${d(new Date(to - 30 * 86400e3))}&date_to=${d(to)}`;
};

const OPS = {
  me: () => get('/me', 'users.me', cl().s),
  vehicles: () => get('/vehicles', 'vehicles.list', cl().s),
  aggregates: () => get(`/vehicles/${cl().vehicleId}/aggregate-statuses`, 'aggregates.statuses', cl().s),
  maintenance: () => get(`/vehicles/${cl().vehicleId}/maintenance-records`, 'vehicles.maintenance', cl().s),
  notifications: () => get('/notifications?page_size=20', 'notifications.list', cl().s),
  client_tickets: () => get('/tickets?page_size=20', 'tickets.list.client', cl().s),
  ticket_card: () => {
    const ids = (json(get('/tickets?page_size=5', 'tickets.list.client', cl().s), { items: [] }).items || [])
      .map((t) => t.id);
    if (ids.length) get(`/tickets/${pick(ids)}/messages?page_size=50`, 'tickets.messages.list', cl().s);
  },
  kb_list: () => get('/knowledge-articles?is_published=true&page_size=20', 'kb.list', cl().s),
  kb_get: () => get(`/knowledge-articles/${pick(meta.articles)}`, 'kb.get', cl().s),
  kb_search: () => get(`/knowledge-articles?is_published=true&search=${SEARCH}`, 'kb.search', cl().s),
  mileage: () => {
    const s = cl();
    if (s.mileage === null) {
      s.mileage = (json(get('/vehicles', 'vehicles.list', s.s), { items: [{ mileage: 0 }] }).items[0] || {}).mileage || 0;
    }
    s.mileage += 1;
    write('PATCH', `/vehicles/${s.vehicleId}/mileage`, { mileage: s.mileage }, 'vehicles.mileage', s.s);
  },
  ticket_create: () => createTicket(iterationClient(0.3), false),
  ticket_create_photo: () => createTicket(iterationClient(0.65), true),
  board: () => pollBoard(en()),
  ticket_get_staff: () => {
    const t = pick(en().board.new.length ? en().board.new : (pollBoard(en()), en().board.new));
    if (t) get(`/tickets/${t.id}`, 'tickets.get', en().s);
  },
  analytics: () => {
    get(`/analytics/ticket-resolution?${range()}`, 'analytics.resolution', ad());
    get(`/analytics/problem-models?${range()}`, 'analytics.problem_models', ad());
    get(`/analytics/maintenance-conversion?${range()}`, 'analytics.conversion', ad());
  },
  published: () => get('/notifications/published?page_size=20', 'notifications.published', ad()),
  users: () => get('/users?page_size=50', 'users.list', ad()),
};

const names = Object.keys(OPS);
export const options = {
  scenarios: Object.fromEntries(names.map((name, i) => [name, {
    executor: 'constant-vus',
    exec: 'op',
    vus: VUS,
    duration: `${DURATION}s`,
    startTime: `${i * (DURATION + GAP)}s`,
    gracefulStop: '5s',
    env: { OP: name },
  }])),
  summaryTrendStats: ['avg', 'med', 'p(95)', 'p(99)', 'max', 'count'],
};

export const op = guarded(() => {
  OPS[__ENV.OP]();
  sleep(1);
});

export function handleSummary(data) {
  return summaryTo(data, { scenario: 'per-op', ops: names, vus: VUS, duration_seconds: DURATION });
}
