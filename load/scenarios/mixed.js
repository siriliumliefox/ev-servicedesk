// Смешанная целевая нагрузка, 20 мин (глава 24, ADR 0028 п. 13): нормативы времени ответа
// и доля ошибок < 1 % на всём прогоне; параллельно — проверка лимитов (п. 9).

import { summaryTo, thresholds } from '../lib/common.js';
import { LIMITS_THRESHOLDS } from '../lib/limits.js';
import { FULL, USERS, mixedScenarios } from '../lib/mixed.js';

export { admin, chat, client, engineer, limits, setup } from '../lib/mixed.js';

export const options = {
  scenarios: mixedScenarios(FULL ? '16m' : '2m'),
  thresholds: { ...thresholds(['steady']), ...LIMITS_THRESHOLDS },
  summaryTrendStats: ['avg', 'med', 'p(95)', 'p(99)', 'max', 'count'],
};

export function handleSummary(data) {
  return summaryTo(data, { scenario: 'mixed', users: USERS });
}
