// Цвета — только из дизайн-токенов (ADR 0010): tokens.css сбрасывает палитру Tailwind (`--color-*: initial`),
// поэтому класс стандартной палитры (`bg-black/50`, `text-gray-500`) молча не генерируется — так в главе 22
// нашёлся незатемнённый фон диалогов и просмотра фото. Нужен цвет вне токенов — явное значение `bg-[rgb(...)]`.
import { readFileSync, readdirSync, statSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";

const ROOT = new URL("../../../", import.meta.url).pathname;
const APPS = ["web-shared/src", "web-admin/src", "web-engineer/src"];
const PALETTE =
  /\b(?:[a-z]+:)*(?:bg|text|border|ring|from|via|to|fill|stroke|outline|shadow|decoration|accent|caret|divide|placeholder)-(?:black|white|slate|gray|zinc|neutral|stone|red|orange|amber|yellow|lime|green|emerald|teal|cyan|sky|blue|indigo|violet|purple|fuchsia|pink|rose)(?:-\d{2,3})?(?:\/\d{1,3})?\b/g;

function sources(dir: string): string[] {
  return readdirSync(dir).flatMap((name) => {
    const path = join(dir, name);
    if (statSync(path).isDirectory()) return sources(path);
    return /\.tsx?$/.test(name) && !/\.test\.tsx?$/.test(name) ? [path] : [];
  });
}

describe("цвета — только токены", () => {
  it("в коде приложений нет классов стандартной палитры Tailwind", () => {
    const found = APPS.flatMap((app) =>
      sources(join(ROOT, app)).flatMap((file) =>
        [...readFileSync(file, "utf8").matchAll(PALETTE)].map((m) => `${file.slice(ROOT.length)}: ${m[0]}`),
      ),
    );
    expect(found).toEqual([]);
  });
});
