import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";
import { parse } from "yaml";
import { firmwareMessage } from "./notifications.ts";

const spec = parse(readFileSync(new URL("../../../docs/openapi.yaml", import.meta.url), "utf8"));

describe("firmwareMessage", () => {
  // #113: предпросмотр админ-панели = текст клиенту — шаблон из описания createFirmwareRelease (его же сверяет backend).
  it("совпадает с шаблоном контракта", () => {
    const description: string = spec.paths["/firmware-releases"].post.description.replace(/\s+/g, " ");
    const [title, call] = firmwareMessage("{version}", "{brand} {model}").split("\n");
    expect(description).toContain(`«${title}»`);
    expect(description).toContain(`«${call}»`);
  });

  it("тема — первая строка, призыв записаться — вторая", () => {
    expect(firmwareMessage("RU 3.1.0", "Zeekr 001")).toBe(
      "Доступна прошивка RU 3.1.0 для Zeekr 001\nЗапишитесь на обновление в сервисном центре.",
    );
  });
});
