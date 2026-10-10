// Генератор дизайн-токенов (Глава 6, Issue #34, ADR 0010).
// Источник истины — design/tokens.json (W3C Design Tokens). Выход:
//   web-shared/src/theme/tokens.css   — Tailwind v4 (@theme) + светлая/тёмная тема на CSS-переменных;
//   mobile/lib/theme/tokens.g.dart    — константы и ThemeExtension для Flutter.
// Запуск: npm run tokens (запись) / npm run tokens -- --check (сверка, CI). Node ≥ 22.18.
import { readFileSync, writeFileSync } from "node:fs";
import { fileURLToPath } from "node:url";

const ROOT = fileURLToPath(new URL("..", import.meta.url));
export const TOKENS_PATH = "design/tokens.json";
export const CSS_PATH = "web-shared/src/theme/tokens.css";
export const DART_PATH = "mobile/lib/theme/tokens.g.dart";

type Json = Record<string, unknown>;
export type Typography = {
  fontFamily: string[];
  fontSize: number;
  lineHeight: number;
  fontWeight: number;
  letterSpacingEm: number;
};
export type Tokens = {
  themes: Record<string, Record<string, string>>;
  typography: Record<string, Record<string, Typography>>;
  fontFamily: Record<string, string[]>;
  space: Record<string, number>;
  radius: Record<string, number>;
  size: Record<string, number>;
  shadow: Record<string, string>;
  duration: Record<string, number>;
};

export function loadRaw(): Json {
  return JSON.parse(readFileSync(ROOT + TOKENS_PATH, "utf8")) as Json;
}

function lookup(raw: Json, path: string): unknown {
  let node: unknown = raw;
  for (const part of path.split(".")) {
    if (typeof node !== "object" || node === null || !(part in node)) {
      throw new Error(`Нет токена {${path}}`);
    }
    node = (node as Json)[part];
  }
  const value = (node as Json).$value;
  if (value === undefined) throw new Error(`{${path}} — группа, а не токен`);
  return resolve(raw, value);
}

function resolve(raw: Json, value: unknown): unknown {
  if (typeof value === "string") {
    const ref = /^\{([^}]+)\}$/.exec(value);
    return ref ? lookup(raw, ref[1]) : value;
  }
  if (Array.isArray(value)) return value;
  if (typeof value === "object" && value !== null) {
    return Object.fromEntries(Object.entries(value).map(([k, v]) => [k, resolve(raw, v)]));
  }
  return value;
}

/** Токены группы без служебных ключей ($type, $description) в порядке файла. */
function entries(group: unknown): [string, Json][] {
  return Object.entries(group as Json).filter(([k]) => !k.startsWith("$")) as [string, Json][];
}

function px(value: unknown): number {
  const m = /^(-?\d+(?:\.\d+)?)px$/.exec(String(value));
  if (!m) throw new Error(`Ожидалось значение в px: ${String(value)}`);
  return Number(m[1]);
}

function em(value: unknown): number {
  const m = /^(-?\d+(?:\.\d+)?)em$/.exec(String(value));
  if (!m) throw new Error(`Ожидалось значение в em: ${String(value)}`);
  return Number(m[1]);
}

export function loadTokens(raw: Json = loadRaw()): Tokens {
  const map = <T>(group: unknown, fn: (v: unknown) => T) =>
    Object.fromEntries(entries(group).map(([k, t]) => [k, fn(resolve(raw, t.$value))]));
  const themes = Object.fromEntries(
    entries(raw.theme).map(([name, group]) => [name, map(group, (v) => String(v).toLowerCase())]),
  );
  const typography = Object.fromEntries(
    entries(raw.typography).map(([platform, group]) => [
      platform,
      map(group, (v) => {
        const t = v as Json;
        return {
          fontFamily: t.fontFamily as string[],
          fontSize: px(t.fontSize),
          lineHeight: px(t.lineHeight),
          fontWeight: Number(t.fontWeight),
          letterSpacingEm: em(t.letterSpacing),
        };
      }),
    ]),
  );
  const font = raw.font as Json;
  return {
    themes,
    typography,
    fontFamily: map(font.family, (v) => v as string[]),
    space: map(raw.space, px),
    radius: map(raw.radius, px),
    size: map(raw.size, px),
    shadow: map(raw.shadow, (v) => {
      const s = v as Json;
      return `${s.offsetX} ${s.offsetY} ${s.blur} ${s.spread} ${s.color}`;
    }),
    duration: map(raw.duration, (v) => Number(String(v).replace(/ms$/, ""))),
  };
}

// ---------- CSS (Tailwind v4) ----------

const HEADER_CSS =
  "/* СГЕНЕРИРОВАНО scripts/design_tokens.mts из design/tokens.json — не редактировать.\n" +
  "   Обновление: npm run tokens. Глава 6, ADR 0010. */\n";

const fontStack = (families: string[]) =>
  families.map((f) => (/^[\w-]+$/.test(f) ? f : `"${f}"`)).join(", ");

export function renderCss(t: Tokens): string {
  const out: string[] = [HEADER_CSS];
  out.push(
    "/* Тёмная тема — атрибут data-theme=\"dark\" на <html> (или на поддереве).",
    "   Без атрибута тема следует системной настройке (prefers-color-scheme). */",
    '@custom-variant dark (&:where([data-theme="dark"], [data-theme="dark"] *));',
    "",
    "/* Палитра и шкалы Tailwind по умолчанию отключены: в разметке — только токены. */",
    "@theme {",
    "  --color-*: initial;",
    "  --text-*: initial;",
    "  --radius-*: initial;",
    "  --shadow-*: initial;",
    "  --font-*: initial;",
    "",
  );
  for (const [name, families] of Object.entries(t.fontFamily)) {
    out.push(`  --font-${name}: ${fontStack(families)};`);
  }
  out.push("", "  /* Типографика веба (кабинет инженера, админ-панель): text-h1, text-body, … */");
  for (const [name, s] of Object.entries(t.typography.web)) {
    out.push(
      `  --text-${name}: ${s.fontSize}px;`,
      `  --text-${name}--line-height: ${s.lineHeight}px;`,
      `  --text-${name}--font-weight: ${s.fontWeight};`,
      `  --text-${name}--letter-spacing: ${s.letterSpacingEm}em;`,
    );
  }
  out.push("", `  /* Отступы: p-1 = ${t.space["1"]}px, p-4 = ${t.space["4"]}px — шкала space в tokens.json. */`);
  out.push(`  --spacing: ${t.space["1"]}px;`, "");
  for (const [name, v] of Object.entries(t.radius)) out.push(`  --radius-${name}: ${v}px;`);
  out.push("");
  for (const [name, v] of Object.entries(t.shadow)) out.push(`  --shadow-${name}: ${v};`);
  out.push("");
  for (const [name, v] of Object.entries(t.size)) out.push(`  --size-${name}: ${v}px;`);
  out.push("");
  for (const [name, v] of Object.entries(t.duration)) out.push(`  --duration-${name}: ${v}ms;`);
  out.push("}", "");

  out.push(
    "/* Семантические цвета: bg-surface, text-fg, border-border-strong, bg-status-red-bg, … */",
    "@theme inline {",
  );
  for (const name of Object.keys(t.themes.light)) out.push(`  --color-${name}: var(--ev-${name});`);
  out.push("}", "");

  const block = (selector: string, theme: string, indent = "") => {
    out.push(`${indent}${selector} {`, `${indent}  color-scheme: ${theme};`);
    for (const [name, v] of Object.entries(t.themes[theme])) out.push(`${indent}  --ev-${name}: ${v};`);
    out.push(`${indent}}`);
  };
  block(':root,\n[data-theme="light"]', "light");
  out.push("");
  block('[data-theme="dark"]', "dark");
  out.push("", "@media (prefers-color-scheme: dark) {");
  block(":root:not([data-theme])", "dark", "  ");
  out.push("}", "");
  return out.join("\n");
}

// ---------- Dart (Flutter) ----------

const camel = (s: string) => s.replace(/-(\w)/g, (_, c: string) => c.toUpperCase());
const dartColor = (hex: string) => {
  const h = hex.replace("#", "");
  const rgba = h.length === 8 ? h : h + "ff";
  return `Color(0x${(rgba.slice(6, 8) + rgba.slice(0, 6)).toUpperCase()})`;
};
const num = (n: number) => (Number.isInteger(n) ? `${n}` : `${Number(n.toFixed(4))}`);

export function renderDart(t: Tokens): string {
  const colorNames = Object.keys(t.themes.light);
  const out: string[] = [
    "// СГЕНЕРИРОВАНО scripts/design_tokens.mts из design/tokens.json — не редактировать.",
    "// Обновление: npm run tokens. Глава 6, ADR 0010.",
    "import 'package:flutter/material.dart';",
    "",
    "/// Семантические цвета темы (design/tokens.json → theme.*).",
    "@immutable",
    "class EvColors extends ThemeExtension<EvColors> {",
    "  const EvColors({",
    ...colorNames.map((n) => `    required this.${camel(n)},`),
    "  });",
    "",
    ...colorNames.map((n) => `  final Color ${camel(n)};`),
    "",
    "  @override",
    "  EvColors copyWith({",
    ...colorNames.map((n) => `    Color? ${camel(n)},`),
    "  }) {",
    "    return EvColors(",
    ...colorNames.map((n) => `      ${camel(n)}: ${camel(n)} ?? this.${camel(n)},`),
    "    );",
    "  }",
    "",
    "  @override",
    "  EvColors lerp(ThemeExtension<EvColors>? other, double t) {",
    "    if (other is! EvColors) return this;",
    "    return EvColors(",
    ...colorNames.map((n) => `      ${camel(n)}: Color.lerp(${camel(n)}, other.${camel(n)}, t)!,`),
    "    );",
    "  }",
    "}",
    "",
  ];
  for (const [theme, colors] of Object.entries(t.themes)) {
    out.push(`const EvColors evColors${theme[0].toUpperCase()}${theme.slice(1)} = EvColors(`);
    for (const [n, v] of Object.entries(colors)) out.push(`  ${camel(n)}: ${dartColor(v)},`);
    out.push(");", "");
  }

  const constClass = (name: string, doc: string, values: Record<string, number>, prefix: string) => {
    out.push(`/// ${doc}`, `abstract final class ${name} {`);
    for (const [k, v] of Object.entries(values)) out.push(`  static const double ${prefix}${camel(k)} = ${num(v)};`);
    out.push("}", "");
  };
  constClass("EvSpace", "Шкала отступов, сетка 4 (space.*).", t.space, "s");
  constClass("EvRadius", "Радиусы скругления (radius.*).", t.radius, "");
  constClass("EvSize", "Размеры: тап-зоны, контролы, иконки (size.*).", t.size, "");

  out.push("/// Длительности анимаций (duration.*).", "abstract final class EvDuration {");
  for (const [k, v] of Object.entries(t.duration)) {
    out.push(`  static const Duration ${camel(k)} = Duration(milliseconds: ${v});`);
  }
  out.push("}", "");

  const sans = t.fontFamily.sans;
  out.push(
    "/// Типографика мобильного приложения (typography.mobile.*).",
    "/// Шрифт Inter подключается ассетом в главе 18; до этого — системный (SF Pro).",
    "abstract final class EvTypeMobile {",
    `  static const String fontFamily = '${sans[1]}';`,
  );
  for (const [k, s] of Object.entries(t.typography.mobile)) {
    out.push(
      `  static const TextStyle ${camel(k)} = TextStyle(`,
      "    fontFamily: fontFamily,",
      `    fontSize: ${num(s.fontSize)},`,
      `    height: ${num(s.lineHeight / s.fontSize)},`,
      `    fontWeight: FontWeight.w${s.fontWeight},`,
      `    letterSpacing: ${num(s.letterSpacingEm * s.fontSize)},`,
      "  );",
    );
  }
  out.push("}", "");
  return out.join("\n");
}

// ---------- CLI ----------

export function outputs(t: Tokens = loadTokens()): Record<string, string> {
  return { [CSS_PATH]: renderCss(t), [DART_PATH]: renderDart(t) };
}

if (import.meta.url === `file://${process.argv[1]}`) {
  const check = process.argv.includes("--check");
  let stale = 0;
  for (const [path, content] of Object.entries(outputs())) {
    let current = "";
    try {
      current = readFileSync(ROOT + path, "utf8");
    } catch {
      /* файла ещё нет */
    }
    if (current === content) {
      console.log(`OK     ${path}`);
    } else if (check) {
      console.error(`STALE  ${path} — запустите npm run tokens`);
      stale++;
    } else {
      writeFileSync(ROOT + path, content);
      console.log(`WRITE  ${path}`);
    }
  }
  process.exit(stale ? 1 : 0);
}
