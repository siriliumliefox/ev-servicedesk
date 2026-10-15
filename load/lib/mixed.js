// Смешанная целевая нагрузка (глава 24, ADR 0028 п. 2, 13): 500 одновременных пользователей —
// 85 % клиентов (из них 100 держат чат по WebSocket), 13 % инженеров, 2 % администраторов.
// Профиль ci — 10 % пользователей и короткие этапы (load.yml, ADR 0028 п. 16).

import { sleep } from 'k6';

import {
  PROFILE, adminSession, clientSession, clients, engineerSession, guarded, setPhases, think,
} from './common.js';
import { limitsScenario } from './limits.js';
import { ClientState, EngineerState, adminAction, chatSession, clientAction, engineerAction } from './roles.js';

export const FULL = PROFILE !== 'ci';
const scale = FULL ? 1 : 0.1;
export const USERS = {
  clients: Math.round(325 * scale),
  chat: Math.round(100 * scale),
  engineers: Math.round(65 * scale),
  admins: Math.max(1, Math.round(10 * scale)),
};
export const CHAT_HOLD_SECONDS = FULL ? 300 : 60;
export const CHAT_INTERVAL_SECONDS = 15;
export const CHAT_GRACE = `${CHAT_HOLD_SECONDS + 30}s`;

// Разгон, удержание, спад — для каждой роли одинаково.
// grace — время на штатное завершение итерации при спаде: у чата это удержание подключения,
// иначе k6 оборвёт сокеты и они посчитаются ошибками.
export function rampingVus(target, hold, execName, {
  ramp = FULL ? '3m' : '30s', startTime = '0s', grace = '30s',
} = {}) {
  return {
    executor: 'ramping-vus',
    exec: execName,
    startTime,
    startVUs: 0,
    stages: [
      { duration: ramp, target },
      { duration: hold, target },
      { duration: FULL ? '1m' : '20s', target: 0 },
    ],
    gracefulRampDown: grace,
    gracefulStop: grace,
  };
}

export function mixedScenarios(hold) {
  const scenarios = {
    clients: rampingVus(USERS.clients, hold, 'client'),
    chat: rampingVus(USERS.chat, hold, 'chat', { grace: CHAT_GRACE }),
    engineers: rampingVus(USERS.engineers, hold, 'engineer'),
    admins: rampingVus(USERS.admins, hold, 'admin'),
  };
  // Лимиты — параллельно с целевой нагрузкой, после разгона (п. 9). В ci — тоже: дёшево.
  scenarios.limits = {
    executor: 'per-vu-iterations', exec: 'limits', vus: 1, iterations: 1,
    startTime: FULL ? '5m' : '1m', maxDuration: '2m',
  };
  return scenarios;
}

export function setup() {
  if (clients.length < 3000) throw new Error('Сид меньше 3000 клиентов — сессий VU не хватит');
  return { start: Date.now() };
}

// Состояние VU — своё у каждого (модуль загружается в каждом VU отдельно).
let state = null;
let phasesSet = false;
function init(data, make) {
  if (!phasesSet) {
    setPhases(data.phases || [{ from: 0, phase: 'steady' }], data.start);
    phasesSet = true;
  }
  if (state === null) state = make();
  return state;
}

export const client = guarded((data) => {
  const c = init(data, () => {
    const s = clientSession();
    return new ClientState(s, clients[s.index]);
  });
  clientAction(c);
  sleep(think());
});

export const chat = guarded((data) => {
  const c = init(data, () => {
    const s = clientSession();
    return new ClientState(s, clients[s.index]);
  });
  chatSession(c, CHAT_HOLD_SECONDS, CHAT_INTERVAL_SECONDS);
});

export const engineer = guarded((data) => {
  const e = init(data, () => new EngineerState(engineerSession()));
  engineerAction(e);
  sleep(think(3, 7));
});

export const admin = guarded((data) => {
  const a = init(data, () => adminSession());
  adminAction(a);
  sleep(think());
});

export const limits = guarded((data) => {
  init(data, () => true);
  limitsScenario();
});
