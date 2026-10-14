// Фиксация замены агрегата и работы по нему (E-05, глава 23, ADR 0027 п. 14). Замена — replaceAggregateStatus:
// сбрасывает счётчик «светофора» и пишет историю ТО одним вызовом; работа без замены (осмотр, долив) и общая
// работа без агрегата — createMaintenanceRecord, счётчик не трогает (ADR 0016 п. 1, ADR 0023).
import { useState, type FormEvent } from 'react'
import {
  ApiError,
  Button,
  InlineError,
  TextArea,
  TextField,
  errorText,
  formatKm,
  todayInMinsk,
  type Vehicle,
} from '@ev-servicedesk/web-shared'
import { useEngineer } from '../repo.ts'

type Kind = 'replacement' | 'work'

const DESCRIPTION_MAX = 255

export interface MaintenanceTarget {
  /** Агрегат; `null` — общая работа без агрегата (описание обязательно). */
  code: string | null
  name: string
}

export function MaintenanceForm({
  vehicle,
  target,
  onSaved,
  onCancel,
}: {
  vehicle: Vehicle
  target: MaintenanceTarget
  onSaved: (message: string) => void
  onCancel: () => void
}) {
  const { repo, now } = useEngineer()
  const today = todayInMinsk(now())
  const [kind, setKind] = useState<Kind>(target.code === null ? 'work' : 'replacement')
  const [date, setDate] = useState(today)
  const [mileage, setMileage] = useState(String(vehicle.mileage))
  const [description, setDescription] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<unknown>(null)

  const replacement = kind === 'replacement'
  const km = Number(mileage)
  const mileageValid = mileage.trim() !== '' && Number.isInteger(km) && km >= 0
  const needsDescription = target.code === null && !description.trim()

  // Ошибка сервера показывается у поля, к которому относится; остальное — под формой.
  const code = error instanceof ApiError ? error.code : null
  const dateError = code === 'REPLACED_AT_IN_FUTURE' || code === 'PERFORMED_AT_IN_FUTURE' ? errorText(error) : undefined
  const mileageError = code === 'MILEAGE_AHEAD_OF_VEHICLE' ? errorText(error) : undefined
  const descriptionError = code === 'MAINTENANCE_SUBJECT_REQUIRED' ? errorText(error) : undefined
  const formError = dateError || mileageError || descriptionError ? null : error

  const submit = async (event: FormEvent) => {
    event.preventDefault()
    if (busy || !mileageValid || needsDescription) return
    setBusy(true)
    setError(null)
    const note = description.trim() || null
    try {
      if (replacement && target.code !== null) {
        await repo.replaceAggregateStatus(vehicle.id, target.code, {
          replaced_at: date,
          mileage_at_replacement: km,
          description: note,
        })
        onSaved(`Замена сохранена: ${target.name}`)
      } else {
        await repo.createMaintenanceRecord(vehicle.id, {
          aggregate_type_code: target.code,
          performed_at: date,
          mileage_at_service: km,
          description: note,
        })
        onSaved(`Работа сохранена: ${target.name}`)
      }
    } catch (e) {
      setError(e)
      setBusy(false)
    }
  }

  return (
    <form
      onSubmit={submit}
      aria-label={`${target.code === null ? 'Другая работа' : 'Замена или работа'}: ${target.name}`}
      className="grid gap-3 rounded-md border border-border-strong bg-surface p-3"
    >
      {target.code !== null && (
        <fieldset className="grid gap-2">
          <legend className="pb-1 text-label">Что сделано</legend>
          {(
            [
              ['replacement', 'Замена', 'Счётчик выработки сбросится'],
              ['work', 'Работа без замены', 'Осмотр, долив — счётчик не меняется'],
            ] as const
          ).map(([value, label, hint]) => (
            <label key={value} className="flex cursor-pointer items-start gap-2 text-body-sm">
              <input
                type="radio"
                name={`maintenance-kind-${target.code}`}
                className="mt-1 size-4 accent-(--ev-fg)"
                checked={kind === value}
                onChange={() => {
                  setKind(value)
                  setError(null)
                }}
              />
              <span>
                {label}
                <span className="block text-caption text-fg-muted">{hint}</span>
              </span>
            </label>
          ))}
        </fieldset>
      )}
      <TextField
        label={replacement ? 'Дата замены' : 'Дата работы'}
        type="date"
        required
        max={today}
        value={date}
        error={dateError}
        onChange={(e) => {
          setDate(e.target.value)
          setError(null)
        }}
      />
      <TextField
        label="Пробег, км"
        type="number"
        inputMode="numeric"
        required
        min={0}
        step={1}
        value={mileage}
        hint={
          replacement
            ? `Не больше текущего пробега авто (${formatKm(vehicle.mileage)})`
            : `Больше текущего (${formatKm(vehicle.mileage)}) — пробег авто обновится`
        }
        error={mileageError ?? (mileageValid ? undefined : 'Целое число километров, не меньше 0')}
        onChange={(e) => {
          setMileage(e.target.value)
          setError(null)
        }}
      />
      <TextArea
        label={target.code === null ? 'Что сделано' : 'Комментарий'}
        hint={target.code === null ? 'Обязательно для работы без агрегата' : 'Необязательно'}
        required={target.code === null}
        maxLength={DESCRIPTION_MAX}
        value={description}
        error={descriptionError}
        onChange={(e) => {
          setDescription(e.target.value)
          setError(null)
        }}
      />
      <InlineError error={formError} />
      <div className="flex justify-end gap-2">
        <Button type="button" variant="ghost" size="sm" onClick={onCancel}>
          Отмена
        </Button>
        <Button type="submit" size="sm" disabled={busy || !mileageValid || needsDescription}>
          {busy ? 'Сохраняем…' : 'Сохранить'}
        </Button>
      </div>
    </form>
  )
}
