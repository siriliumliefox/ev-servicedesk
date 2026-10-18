// Заголовки безопасности статики кабинетов (глава 25, ADR 0029 п. 8; ZAP-2): единый список для dev, preview
// и nginx главы 26 — clickjacking, nosniff, Referer, разрешения браузера, изоляция окна.
import { describe, expect, it } from "vitest";
import { SECURITY_HEADERS } from "../vite.ts";

describe("SECURITY_HEADERS", () => {
  it("запрещает встраивание во фрейм и угадывание типа", () => {
    expect(SECURITY_HEADERS["X-Frame-Options"]).toBe("DENY");
    expect(SECURITY_HEADERS["Content-Security-Policy"]).toContain("frame-ancestors 'none'");
    expect(SECURITY_HEADERS["X-Content-Type-Options"]).toBe("nosniff");
    expect(SECURITY_HEADERS["Referrer-Policy"]).toBe("no-referrer");
    expect(SECURITY_HEADERS["Permissions-Policy"]).toMatch(/camera=\(\).*geolocation=\(\)/);
    expect(SECURITY_HEADERS["Cross-Origin-Opener-Policy"]).toBe("same-origin");
  });
});
