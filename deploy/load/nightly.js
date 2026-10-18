// Ночной облегчённый прогон на staging (глава 26, ADR 0030 п. 20): 20 виртуальных пользователей 5 мин,
// чтение главного экрана клиента и базы знаний; нормативы ADR 0028 — чтение p95 ≤ 300 мс, p99 ≤ 1 с,
// ошибки < 1 %. Без сида: вход тестовым номером (SMS_TEST_PHONES — SMS не отправляется) в setup.
// Итоги — remote write в Prometheus staging (дашборд «Нагрузка k6»). Запуск — scripts/nightly-load.sh.
import http from 'k6/http';
import { check, sleep } from 'k6';

const BASE = `${__ENV.BASE_URL || 'http://backend:8000'}/v1`;

export const options = {
  scenarios: {
    nightly: { executor: 'constant-vus', vus: Number(__ENV.VUS || 20), duration: __ENV.DURATION || '5m' },
  },
  thresholds: {
    'http_req_duration{kind:read}': ['p(95)<300', 'p(99)<1000'],
    http_req_failed: ['rate<0.01'],
  },
};

export function setup() {
  const json = { headers: { 'Content-Type': 'application/json' } };
  const phone = __ENV.EV_PHONE;
  const requested = http.post(`${BASE}/auth/phone/request-code`, JSON.stringify({ phone }), json);
  check(requested, { 'код запрошен': (r) => r.status === 200 });
  const verified = http.post(
    `${BASE}/auth/phone/verify-code`,
    JSON.stringify({ phone, code: __ENV.EV_CODE, pd_policy_version: __ENV.EV_POLICY || '2026-10' }),
    json,
  );
  if (verified.status !== 200) throw new Error(`вход не удался: ${verified.status}`);
  return { token: verified.json('access_token') };
}

export default function (data) {
  const params = { headers: { Authorization: `Bearer ${data.token}` }, tags: { kind: 'read' } };
  for (const path of ['/me', '/vehicles', '/notifications?page_size=20', '/knowledge-articles?page_size=20']) {
    const r = http.get(`${BASE}${path}`, { ...params, tags: { kind: 'read', name: path.split('?')[0] } });
    check(r, { '200': (res) => res.status === 200 });
  }
  sleep(1);
}
