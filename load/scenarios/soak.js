// Долгий прогон, 60 мин при целевой нагрузке (глава 24, ADR 0028 п. 13): утечки памяти,
// исчерпание пула соединений, рост времени ответа к концу. Один раз на финальной версии.

import { summaryTo, thresholds } from '../lib/common.js';
import { LIMITS_THRESHOLDS } from '../lib/limits.js';
import { FULL, USERS, mixedScenarios } from '../lib/mixed.js';

export { admin, chat, client, engineer, limits, setup } from '../lib/mixed.js';

export const options = {
  scenarios: mixedScenarios(FULL ? '56m' : '3m'),
  thresholds: { ...thresholds(['steady']), ...LIMITS_THRESHOLDS },
  summaryTrendStats: ['avg', 'med', 'p(95)', 'p(99)', 'max', 'count'],
};

export function handleSummary(data) {
  return summaryTo(data, { scenario: 'soak', users: USERS });
}
