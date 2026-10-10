// Тесты прототипа (Глава 8, ADR 0012): Vitest + Testing Library в jsdom. Стили не нужны — Tailwind не подключён.
import react from '@vitejs/plugin-react'
import { defineConfig } from 'vitest/config'

export default defineConfig({
  plugins: [react()],
  test: {
    environment: 'jsdom',
    setupFiles: ['./src/test/setup.ts'],
    include: ['src/**/*.test.{ts,tsx}'],
  },
})
