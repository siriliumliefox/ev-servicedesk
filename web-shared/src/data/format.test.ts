import { describe, expect, it } from "vitest";
import { plural } from "./format.ts";

describe("plural", () => {
  it.each([
    [1, "1 шаг"],
    [2, "2 шага"],
    [5, "5 шагов"],
    [11, "11 шагов"],
    [12, "12 шагов"],
    [21, "21 шаг"],
    [22, "22 шага"],
    [111, "111 шагов"],
    [0, "0 шагов"],
  ])("%i → %s", (n, text) => expect(plural(n, "шаг", "шага", "шагов")).toBe(text));
});
