// Smoke-тест mock-сервера (Глава 3, Issue #18): поднимает Prism по docs/openapi.yaml и
// вызывает его клиентом фронтенда (web-shared). Запуск: npm run test:mock (Node ≥ 22.18).
import { spawn } from "node:child_process";
import assert from "node:assert/strict";
import { createApiClient } from "../web-shared/src/api/client.ts";

const PORT = Number(process.env.MOCK_PORT ?? 4010);
const BASE = `http://127.0.0.1:${PORT}`;

const prism = spawn(
  "node_modules/.bin/prism",
  ["mock", "docs/openapi.yaml", "--port", String(PORT), "--host", "127.0.0.1", "--errors"],
  { stdio: ["ignore", "pipe", "pipe"] },
);
let log = "";
prism.stdout.on("data", (d) => (log += d));
prism.stderr.on("data", (d) => (log += d));

async function waitReady(timeoutMs = 30_000): Promise<void> {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    try {
      await fetch(`${BASE}/aggregate-types`);
      return;
    } catch {
      await new Promise((r) => setTimeout(r, 300));
    }
  }
  throw new Error(`Prism не поднялся за ${timeoutMs} мс:\n${log}`);
}

const checks: [string, () => Promise<void>][] = [];
const check = (name: string, fn: () => Promise<void>) => checks.push([name, fn]);

const anon = createApiClient(BASE);
const engineer = createApiClient(BASE, () => "mock-token");

check("без токена защищённая операция → 401", async () => {
  const { response } = await anon.GET("/tickets");
  assert.equal(response.status, 401);
});

check("listTickets → 200, {items, meta}", async () => {
  const { data, response } = await engineer.GET("/tickets", { params: { query: { page: 1 } } });
  assert.equal(response.status, 200);
  assert.ok(Array.isArray(data?.items));
  assert.equal(typeof data?.meta.total_pages, "number");
});

check("getCurrentUser → 200, UserPublic", async () => {
  const { data, response } = await engineer.GET("/me");
  assert.equal(response.status, 200);
  assert.ok(["client", "engineer", "admin"].includes(data!.role));
  assert.equal(typeof data!.is_active, "boolean");
});

check("коллекции пагинированы: searchVehicleModels", async () => {
  const { data, response } = await engineer.GET("/vehicle-models");
  assert.equal(response.status, 200);
  assert.ok(Array.isArray(data?.items) && data.meta);
});

check("невалидный VIN → 422 (валидация по контракту)", async () => {
  const { response } = await engineer.POST("/vehicles", { body: { vin: "BAD" } });
  assert.equal(response.status, 422);
});

check("аналитика без обязательного периода → 422", async () => {
  // @ts-expect-error — намеренно без обязательных date_from/date_to
  const { response } = await engineer.GET("/analytics/ticket-resolution", { params: { query: {} } });
  assert.equal(response.status, 422);
});

check("неизвестный путь → 404", async () => {
  const res = await fetch(`${BASE}/no-such-endpoint`, { headers: { Authorization: "Bearer x" } });
  assert.equal(res.status, 404);
});

let failed = 0;
try {
  await waitReady();
  for (const [name, fn] of checks) {
    try {
      await fn();
      console.log(`PASS  ${name}`);
    } catch (e) {
      failed++;
      console.log(`FAIL  ${name}\n      ${(e as Error).message}`);
    }
  }
} finally {
  prism.kill();
}
console.log(`\n${checks.length - failed}/${checks.length} проверок прошло`);
process.exit(failed ? 1 : 0);
