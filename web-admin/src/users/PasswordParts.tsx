// Ввод и показ пароля сотрудника (ADR 0026 п. 4–5): поле с кнопкой «Сгенерировать» и одноразовый показ
// пароля для передачи сотруднику — после ухода с экрана его больше не увидеть.
import { useState } from 'react'
import { Button, PASSWORD_MAX, PASSWORD_MIN, TextField } from '@ev-servicedesk/web-shared'
import { generatePassword } from './password.ts'

export function PasswordInput({
  label,
  value,
  error,
  onChange,
}: {
  label: string
  value: string
  error?: string
  onChange: (value: string) => void
}) {
  return (
    <div className="flex items-start gap-2">
      <TextField
        label={label}
        className="flex-1"
        autoComplete="new-password"
        spellCheck={false}
        maxLength={PASSWORD_MAX}
        hint={`От ${PASSWORD_MIN} символов. Пароль видите только вы — передайте его сотруднику.`}
        error={error}
        value={value}
        onChange={(e) => onChange(e.target.value)}
      />
      <Button type="button" variant="secondary" className="mt-7" onClick={() => onChange(generatePassword())}>
        Сгенерировать
      </Button>
    </div>
  )
}

/** Пароль после создания или сброса: показан один раз, копируется в буфер. */
export function PasswordReveal({ phone, password, onClose }: { phone: string; password: string; onClose: () => void }) {
  const [copied, setCopied] = useState(false)
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(password)
      setCopied(true)
    } catch {
      setCopied(false)
    }
  }
  return (
    <div role="status" className="grid gap-2 rounded-md bg-status-green-bg p-3 text-body-sm text-status-green-fg">
      <p>
        Пароль для {phone} — передайте его сотруднику. Больше он нигде не показывается: потеряется — сбросьте снова.
      </p>
      <p className="flex flex-wrap items-center gap-2">
        <code className="rounded bg-surface px-2 py-1 font-mono text-body text-fg" aria-label="Пароль">
          {password}
        </code>
        <Button type="button" size="sm" variant="secondary" onClick={copy}>
          {copied ? 'Скопировано' : 'Копировать'}
        </Button>
        <Button type="button" size="sm" variant="ghost" onClick={onClose}>
          Готово
        </Button>
      </p>
    </div>
  )
}
