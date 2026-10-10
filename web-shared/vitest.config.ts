// Юнит-тесты слоя данных (Глава 8): SLA, репозиторий прототипа. Без DOM.
import { defineConfig } from "vitest/config";

export default defineConfig({
  test: {
    environment: "node",
    include: ["src/**/*.test.ts"],
  },
});
