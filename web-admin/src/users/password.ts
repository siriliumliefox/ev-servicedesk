// Пароль сотрудника (ADR 0026 п. 4–5): генерация криптостойким ГСЧ браузера. 16 символов из алфавита без
// похожих знаков (0/O, 1/l/I) — пароль передают сотруднику вслух или в мессенджере.
const ALPHABET = 'ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz23456789'
export const PASSWORD_LENGTH = 16
export { PASSWORD_MAX, PASSWORD_MIN, passwordProblem } from '@ev-servicedesk/web-shared'

export function generatePassword(random: (size: number) => Uint8Array = (size) => crypto.getRandomValues(new Uint8Array(size))): string {
  // Отбрасываем байты ≥ 228 (= 4 × 57): остаток по модулю алфавита без перекоса.
  const limit = 256 - (256 % ALPHABET.length)
  let out = ''
  while (out.length < PASSWORD_LENGTH) {
    for (const byte of random(PASSWORD_LENGTH * 2)) {
      if (byte < limit && out.length < PASSWORD_LENGTH) out += ALPHABET[byte % ALPHABET.length]
    }
  }
  return out
}
