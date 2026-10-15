// Лимиты под нагрузкой (глава 24, ADR 0028 п. 9): с одного «IP» лимиты N-06 и WebSocket
// срабатывают как в production за прокси, остальные пользователи при этом не страдают.

import { check } from 'k6';
import { setTimeout } from 'k6/timers';
import { WebSocket } from 'k6/websockets';

import { WS_BASE, ipFor, meta, request } from './common.js';

// Свои «IP» на каждый прогон: счётчики лимитов живут в Redis до часа (SMS), и следующий
// сценарий на том же стенде иначе начал бы с заполненного окна.
const RUN_IP_BASE = 250000 + (Math.floor(Date.now() / 1000) % 100000) * 4;
const limitsIp = (k) => ipFor(RUN_IP_BASE + k);

const randomPhone = (prefix) => `${prefix}${String(Math.floor(Math.random() * 1e7)).padStart(7, '0')}`;

function smsPerIp() {
  const ip = limitsIp(0);
  const codes = [];
  for (let i = 0; i < 31; i += 1) {
    const r = request('POST', '/auth/phone/request-code', { phone: randomPhone('+37529') },
      { name: 'limits.sms', kind: 'limits', ip, expected: [200, 429] });
    codes.push(r.status);
    if (i === 30) check(r, { 'SMS: 31-й запрос с IP → Retry-After': (x) => !!x.headers['Retry-After'] });
  }
  check(codes, {
    'SMS: 30 запросов с IP проходят': (c) => c.slice(0, 30).every((s) => s === 200),
    'SMS: 31-й запрос с IP → 429': (c) => c[30] === 429,
  });
}

function staffLoginPerIp() {
  const ip = limitsIp(1);
  const codes = [];
  for (let i = 0; i < 21; i += 1) {
    const r = request('POST', '/auth/staff/login', { phone: randomPhone('+37525'), password: 'wrong-password' },
      { name: 'limits.staff_login', kind: 'limits', ip, expected: [401, 429] });
    codes.push(r.status);
  }
  check(codes, {
    'Вход сотрудника: 20 неверных с IP → 401': (c) => c.slice(0, 20).every((s) => s === 401),
    'Вход сотрудника: 21-й с IP → 429': (c) => c[20] === 429,
  });
  const phoneCodes = [];
  for (let i = 0; i < 6; i += 1) {
    const r = request('POST', '/auth/staff/login', { phone: meta.limitsStaffPhone, password: 'wrong-password' },
      { name: 'limits.staff_login', kind: 'limits', ip: limitsIp(2), expected: [401, 429] });
    phoneCodes.push(r.status);
  }
  check(phoneCodes, { 'Вход сотрудника: 6-я неверная попытка по номеру → 429': (c) => c[5] === 429 });
}

// 61 подключение за минуту с одного IP: 60 закрывает сервер по таймауту auth (4401) или мы
// сами, одно — 4429.
function wsPerIp() {
  const ip = limitsIp(3);
  const closes = new Array(61).fill(null);
  for (let i = 0; i < 61; i += 1) {
    const ws = new WebSocket(`${WS_BASE}/tickets/1/ws`, null, {
      headers: { 'X-Forwarded-For': ip }, tags: { name: 'limits.ws' },
    });
    ws.onclose = (e) => { closes[i] = e && e.code; };
    ws.onerror = () => {};
    setTimeout(() => { if (closes[i] === null) ws.close(); }, 2000);
  }
  setTimeout(() => {
    check(closes, {
      // Порядок одновременных подключений на сервере не задан — проверяем число отказов.
      'WebSocket: из 61 подключения с IP ровно одно → 4429': (c) => c.filter((x) => x === 4429).length === 1,
    });
  }, 4000);
}

export function limitsScenario() {
  smsPerIp();
  staffLoginPerIp();
  wsPerIp(); // итерация завершится, когда закроются все подключения и сработают таймеры
}

export const LIMITS_THRESHOLDS = { 'checks{scenario:limits}': ['rate==1'] };
