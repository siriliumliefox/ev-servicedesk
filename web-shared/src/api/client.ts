// Типизированный клиент EV-ServiceDesk API v1 (Глава 3, ADR 0007).
// Типы — web-shared/src/api/schema.ts, генерируются из docs/openapi.yaml: `npm run gen:api`.
import createClient, { type Middleware } from "openapi-fetch";
import type { paths } from "./schema.ts";

export type { components, operations, paths } from "./schema.ts";

/** Адрес mock-сервера Prism (`npm run mock`) — значение по умолчанию для разработки. */
export const MOCK_API_BASE_URL = "http://localhost:4010";

export function createApiClient(baseUrl: string, getAccessToken?: () => string | null) {
  const client = createClient<paths>({ baseUrl });
  const auth: Middleware = {
    onRequest({ request }) {
      const token = getAccessToken?.();
      if (token) request.headers.set("Authorization", `Bearer ${token}`);
      return request;
    },
  };
  client.use(auth);
  return client;
}

export type ApiClient = ReturnType<typeof createApiClient>;
