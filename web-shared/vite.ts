// Сборка и dev-сервер кабинетов сотрудников (главы 21–22, ADR 0025 п. 2, 4; ADR 0026 п. 1) — одна политика
// для кабинета инженера и админ-панели. Подключается в vite.config.ts приложения:
// `@ev-servicedesk/web-shared/vite` (только Node, в браузерную сборку не попадает).
import type { Plugin, ProxyOptions } from "vite";

/**
 * API на том же origin: dev и preview проксируют `/v1` (REST и WebSocket) на backend — EV_API_PROXY, по
 * умолчанию локальный uvicorn. В production то же делает nginx (глава 26).
 */
export function apiProxy(target = "http://127.0.0.1:8000"): Record<string, ProxyOptions> {
  return { "/v1": { target, ws: true, changeOrigin: false } };
}

/**
 * CSP сборки — `<meta>` в index.html: скрипты, стили и запросы — только свой origin; изображения и видео —
 * свой origin, `blob:`/`data:` и origin S3 (`mediaOrigin`: presigned GET вложений кабинета инженера).
 * В dev не ставится: HMR Vite работает через inline-скрипты. frame-ancestors в <meta> не действует —
 * заголовок nginx.
 */
export function contentSecurityPolicy(mediaOrigin = ""): Plugin {
  const media = ["'self'", "blob:", "data:", ...(mediaOrigin ? [mediaOrigin] : [])].join(" ");
  const policy = [
    "default-src 'self'",
    "script-src 'self'",
    "style-src 'self'",
    "font-src 'self'",
    "connect-src 'self'",
    `img-src ${media}`,
    `media-src ${media}`,
    "object-src 'none'",
    "base-uri 'self'",
    "form-action 'self'",
  ].join("; ");
  return {
    name: "ev-csp",
    apply: "build",
    transformIndexHtml: () => [
      { tag: "meta", attrs: { "http-equiv": "Content-Security-Policy", content: policy }, injectTo: "head-prepend" },
    ],
  };
}
