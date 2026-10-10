// Тесты дизайн-токенов (Глава 6, Issue #34, ADR 0010): контраст WCAG 2.1, тап-зоны,
// сетка отступов, радиусы, синхронность сгенерированных файлов.
// Запуск: npm run test:tokens (Node ≥ 22.18).
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import assert from "node:assert/strict";
import { describe, test } from "node:test";
import { loadTokens, outputs } from "./design_tokens.mts";

const ROOT = fileURLToPath(new URL("..", import.meta.url));
const t = loadTokens();

/** Относительная яркость sRGB (WCAG 2.1, 1.4.3). */
export function luminance(hex: string): number {
  const h = hex.replace("#", "");
  const [r, g, b] = [0, 2, 4].map((i) => {
    const c = parseInt(h.slice(i, i + 2), 16) / 255;
    return c <= 0.04045 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4;
  });
  return 0.2126 * r + 0.7152 * g + 0.0722 * b;
}

export function contrast(a: string, b: string): number {
  const [hi, lo] = [luminance(a), luminance(b)].sort((x, y) => y - x);
  return (hi + 0.05) / (lo + 0.05);
}

function hue(hex: string): number {
  const h = hex.replace("#", "");
  const [r, g, b] = [0, 2, 4].map((i) => parseInt(h.slice(i, i + 2), 16) / 255);
  const max = Math.max(r, g, b);
  const d = max - Math.min(r, g, b);
  if (d === 0) return 0;
  const raw = max === r ? ((g - b) / d) % 6 : max === g ? (b - r) / d + 2 : (r - g) / d + 4;
  return (raw * 60 + 360) % 360;
}

const TEXT = 4.5; // WCAG 1.4.3 AA, обычный текст (ТЗ раздел 6)
const NON_TEXT = 3; // WCAG 1.4.11 AA, иконки, границы полей, фокус, заливки статусов

const STATUSES = ["green", "yellow", "red", "unknown"] as const;
const BACKGROUNDS = ["canvas", "surface", "surface-subtle"] as const;

/** [передний план, фон, минимальный контраст] — одинаково для обеих тем. */
const PAIRS: [string, string, number][] = [
  ...BACKGROUNDS.flatMap((bg): [string, string, number][] => [
    ["fg", bg, TEXT],
    ["fg-muted", bg, TEXT],
    ["primary-text", bg, TEXT],
    ["danger-text", bg, TEXT],
    ["info-text", bg, TEXT],
    ["border-strong", bg, NON_TEXT],
    ["focus-ring", bg, NON_TEXT],
    ...STATUSES.map((s): [string, string, number] => [`status-${s}-solid`, bg, NON_TEXT]),
  ]),
  ["on-primary", "primary", TEXT],
  ["on-primary", "primary-hover", TEXT],
  ["on-danger", "danger", TEXT],
  ["on-danger", "danger-hover", TEXT],
  ...STATUSES.map((s): [string, string, number] => [`status-${s}-fg`, `status-${s}-bg`, TEXT]),
];

describe("контраст WCAG", () => {
  for (const [theme, colors] of Object.entries(t.themes)) {
    for (const [fg, bg, min] of PAIRS) {
      test(`${theme}: ${fg} на ${bg} ≥ ${min}:1`, () => {
        const ratio = contrast(colors[fg], colors[bg]);
        assert.ok(ratio >= min, `${colors[fg]} на ${colors[bg]} = ${ratio.toFixed(2)}:1`);
      });
    }
  }

  test("эталон формулы: чёрный на белом = 21:1, #767676 на белом ≈ 4.54:1", () => {
    assert.equal(contrast("#000000", "#ffffff"), 21);
    assert.equal(contrast("#767676", "#ffffff").toFixed(2), "4.54");
  });
});

describe("темы", () => {
  test("в светлой и тёмной теме одинаковый набор токенов", () => {
    assert.deepEqual(Object.keys(t.themes.dark), Object.keys(t.themes.light));
  });

  test("все цвета — #rrggbb", () => {
    for (const colors of Object.values(t.themes)) {
      for (const [name, v] of Object.entries(colors)) assert.match(v, /^#[0-9a-f]{6}$/, name);
    }
  });

  test("у каждого статуса светофора есть bg / fg / solid", () => {
    for (const s of STATUSES) {
      for (const part of ["bg", "fg", "solid"]) assert.ok(`status-${s}-${part}` in t.themes.light);
    }
  });

  test("статусы светофора различимы между собой (оттенок solid отличается ≥ 30°)", () => {
    for (const colors of Object.values(t.themes)) {
      const hues = ["green", "yellow", "red"].map((s) => hue(colors[`status-${s}-solid`]));
      for (let i = 0; i < hues.length; i++) {
        for (let j = i + 1; j < hues.length; j++) {
          const d = Math.abs(hues[i] - hues[j]);
          assert.ok(Math.min(d, 360 - d) >= 30, `${hues[i]}° vs ${hues[j]}°`);
        }
      }
    }
  });

  test("«скоро менять» не совпадает с брендовым жёлтым (оттенок отличается ≥ 10°)", () => {
    for (const colors of Object.values(t.themes)) {
      const d = Math.abs(hue(colors.primary) - hue(colors["status-yellow-solid"]));
      assert.ok(d >= 10, `primary ${colors.primary} vs status-yellow-solid ${colors["status-yellow-solid"]}: ${d.toFixed(1)}°`);
    }
  });
});

describe("размеры и сетка", () => {
  test("минимальная тап-зона ≥ 44 px (ТЗ раздел 6)", () => {
    assert.ok(t.size["tap-target-min"] >= 44);
  });

  test("мобильные контролы и нижняя навигация не меньше тап-зоны", () => {
    for (const k of ["control-mobile", "bottom-nav"]) {
      assert.ok(t.size[k] >= t.size["tap-target-min"], k);
    }
  });

  test("веб-контролы ≥ 24 px (WCAG 2.5.8)", () => {
    for (const k of ["control-web", "control-web-sm"]) assert.ok(t.size[k] >= 24, k);
  });

  test("отступы: кратны 4, ключ = значение / 4, по возрастанию", () => {
    const values = Object.entries(t.space);
    for (const [k, v] of values) {
      assert.equal(v % 4, 0, `space.${k} = ${v}`);
      assert.equal(Number(k) * 4, v, `space.${k} = ${v}`);
    }
    const sorted = values.map(([, v]) => v);
    assert.deepEqual(sorted, [...sorted].sort((a, b) => a - b));
  });

  test("размеры (size.*) кратны 4", () => {
    for (const [k, v] of Object.entries(t.size)) assert.equal(v % 4, 0, `size.${k} = ${v}`);
  });

  test("радиусы: фиксированный набор, по возрастанию", () => {
    assert.deepEqual(Object.keys(t.radius), ["none", "sm", "md", "lg", "xl", "full"]);
    const values = Object.values(t.radius);
    assert.deepEqual(values, [...values].sort((a, b) => a - b));
  });
});

describe("типографика", () => {
  for (const [platform, styles] of Object.entries(t.typography)) {
    test(`${platform}: межстрочный ≥ кегля, кегль ≥ 12, сетка 2 px`, () => {
      for (const [name, s] of Object.entries(styles)) {
        assert.ok(s.fontSize >= 12, `${name}: ${s.fontSize}`);
        assert.ok(s.lineHeight >= s.fontSize, `${name}: ${s.lineHeight} < ${s.fontSize}`);
        assert.equal(s.lineHeight % 2, 0, `${name}: line-height ${s.lineHeight}`);
      }
    });
  }

  test("мобильный основной текст ≥ 16", () => {
    assert.ok(t.typography.mobile.body.fontSize >= 16);
  });

  test("одинаковый набор стилей на mobile и web", () => {
    assert.deepEqual(Object.keys(t.typography.web), Object.keys(t.typography.mobile));
  });
});

describe("сгенерированные файлы", () => {
  for (const [path, content] of Object.entries(outputs(t))) {
    test(`${path} совпадает с design/tokens.json (npm run tokens)`, () => {
      assert.equal(readFileSync(ROOT + path, "utf8"), content);
    });
  }
});
