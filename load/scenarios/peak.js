// Пиковый сценарий, 25 мин (глава 24, ADR 0028 п. 10, 12): разгон до 500 пользователей (0–5),
// целевая нагрузка и 200 чатов (5–10), на 10-й минуте рассылка всем клиентам и всплеск
// ≈ 150 RPS (10–15): получатели открывают приложение, каждый четвёртый создаёт тикет (каждый
// пятый тикет — с фото), инженеры разбирают очередь; затем 50 RPS (15–25) — восстановление.
//
// Пороги: steady — нормативы времени ответа; peak — доля ошибок < 1 % и p99 ≤ 2 с; recovery
// (15–17) — только доля ошибок; с 17-й минуты снова нормативы. Доставку рассылки (≤ 5 мин,
// ADR 0028 п. 12) меряет load/run.sh по БД после сценария: k6 видит только сводку API, где
// получатели без действующего push-токена есть, а доставок у них нет.

import { adminSession, clients, guarded, setPhases, summaryTo, thresholds } from '../lib/common.js';
import { CHAT_GRACE, FULL, USERS, rampingVus } from '../lib/mixed.js';
import { broadcast as publishBroadcast, burstSession } from '../lib/roles.js';

export { admin, chat, client, engineer } from '../lib/mixed.js';

const scaleTime = (minutes) => (FULL ? minutes * 60 : minutes * 12); // ci: 25 мин → 5 мин
const at = (minutes) => `${scaleTime(minutes)}s`;
const BURST_PEAK = FULL ? 10 : 2; // сессий в секунду на пике всплеска

export const options = {
  scenarios: {
    clients: rampingVus(USERS.clients, at(19), 'client', { ramp: at(5) }),
    engineers: rampingVus(USERS.engineers, at(19), 'engineer', { ramp: at(5) }),
    admins: rampingVus(USERS.admins, at(19), 'admin', { ramp: at(5) }),
    chat: rampingVus(USERS.chat * 2, at(14), 'chat', { ramp: at(1), startTime: at(5), grace: CHAT_GRACE }),
    broadcast: {
      executor: 'per-vu-iterations', exec: 'broadcast', vus: 1, iterations: 1,
      startTime: at(10), maxDuration: '1m',
    },
    burst: {
      executor: 'ramping-arrival-rate',
      exec: 'burst',
      startTime: at(10),
      startRate: 0,
      timeUnit: '1s',
      preAllocatedVUs: FULL ? 150 : 20,
      maxVUs: FULL ? 400 : 60,
      stages: [
        { duration: at(0.5), target: BURST_PEAK },
        { duration: at(1.5), target: BURST_PEAK },
        { duration: at(3), target: Math.max(1, Math.round(BURST_PEAK / 5)) },
      ],
    },
  },
  thresholds: thresholds(['steady', 'peak', 'recovery']),
  summaryTrendStats: ['avg', 'med', 'p(95)', 'p(99)', 'max', 'count'],
};

export function setup() {
  if (clients.length < 5000) throw new Error('Для всплеска нужен сид от 5000 клиентов');
  return {
    start: Date.now(),
    phases: [
      { from: 0, phase: 'steady' },
      { from: scaleTime(10), phase: 'peak' },
      { from: scaleTime(15), phase: 'recovery' },
      { from: scaleTime(17), phase: 'steady' },
    ],
  };
}

export const broadcast = guarded((data) => {
  setPhases(data.phases, data.start);
  publishBroadcast(adminSession());
});

let burstPhasesSet = false;
export const burst = guarded((data) => {
  if (!burstPhasesSet) {
    setPhases(data.phases, data.start);
    burstPhasesSet = true;
  }
  burstSession(Math.random() < 0.25);
});

export function handleSummary(data) {
  return summaryTo(data, { scenario: 'peak', users: USERS, burst_peak_per_second: BURST_PEAK });
}
