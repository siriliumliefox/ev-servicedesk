// Пароль сотрудника (ADR 0026 п. 4–5): генерация криптостойким ГСЧ браузера. 16 символов из алфавита без
// похожих знаков (0/O, 1/l/I) — пароль передают сотруднику вслух или в мессенджере.
const ALPHABET = 'ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz23456789'
export const PASSWORD_LENGTH = 16
export const PASSWORD_MIN = 12
export const PASSWORD_MAX = 128

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

/** Ошибка длины пароля до запроса — как схема контракта (12–128). */
export function passwordProblem(password: string): string | null {
  if (password.length < PASSWORD_MIN) return `Пароль — не короче ${PASSWORD_MIN} символов`
  if (password.length > PASSWORD_MAX) return `Пароль — не длиннее ${PASSWORD_MAX} символов`
  return null
}
