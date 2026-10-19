// Заголовки статики кабинетов в nginx (глава 26, ADR 0030 п. 18) — тот же список, что SECURITY_HEADERS
// dev и preview, и CSP сборки с frame-ancestors: расхождение — падение теста, а не тихая разница стендов.
import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";
import { SECURITY_HEADERS, cspPolicy } from "../vite.ts";

const SNIPPET = new URL("../../deploy/nginx/templates/snippets/cabinet-headers.conf.template", import.meta.url);

function nginxHeaders(): Record<string, string> {
  const headers: Record<string, string> = {};
  for (const match of readFileSync(SNIPPET, "utf8").matchAll(/^add_header (\S+) "([^"]*)" always;$/gm)) {
    headers[match[1]] = match[2];
  }
  return headers;
}

describe("заголовки кабинетов в nginx", () => {
  const headers = nginxHeaders();

  it("совпадают с SECURITY_HEADERS (кроме CSP)", () => {
    for (const [name, value] of Object.entries(SECURITY_HEADERS)) {
      if (name === "Content-Security-Policy") continue;
      expect(headers[name], name).toBe(value);
    }
  });

  it("CSP — политика сборки с origin S3 и frame-ancestors заголовком", () => {
    expect(headers["Content-Security-Policy"]).toBe(`${cspPolicy("${EV_MEDIA_ORIGIN}")}; frame-ancestors 'none'`);
    expect(SECURITY_HEADERS["Content-Security-Policy"]).toBe("frame-ancestors 'none'");
  });

  it("HSTS и ничего лишнего", () => {
    expect(headers["Strict-Transport-Security"]).toBe("max-age=31536000");
    expect(Object.keys(headers).sort()).toEqual([...Object.keys(SECURITY_HEADERS), "Strict-Transport-Security"].sort());
  });
});
