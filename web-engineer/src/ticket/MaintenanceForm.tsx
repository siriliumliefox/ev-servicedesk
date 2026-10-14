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

export interface AggregateRef {
  code: string
  name: string
}

type Kind = 'replacement' | 'work'
type Field = 'date' | 'mileage' | 'description'

const KINDS: readonly { kind: Kind; label: string; hint: string }[] = [
  { kind: 'replacement', label: 'Замена', hint: 'Счётчик выработки сбросится' },
  { kind: 'work', label: 'Работа без замены', hint: 'Осмотр, долив — счётчик не меняется' },
]

/** Ошибки контракта, относящиеся к полю формы, показываются у поля; остальные — под формой. */
const FIELD_OF: Readonly<Record<string, Field>> = {
  REPLACED_AT_IN_FUTURE: 'date',
  PERFORMED_AT_IN_FUTURE: 'date',
  MILEAGE_AHEAD_OF_VEHICLE: 'mileage',
  MAINTENANCE_SUBJECT_REQUIRED: 'description',
}

const DESCRIPTION_MAX = 255

/** `aggregate` — замена или работа по агрегату; `null` — другая работа без агрегата (описание обязательно). */
export function MaintenanceForm({
  vehicle,
  aggregate,
  onSaved,
  onCancel,
}: {
  vehicle: Vehicle
  aggregate: AggregateRef | null
  onSaved: (message: string) => void
  onCancel: () => void
}) {
  const { repo, now } = useEngineer()
  const today = todayInMinsk(now())
  const [kind, setKind] = useState<Kind>(aggregate ? 'replacement' : 'work')
  const [date, setDate] = useState(today)
  const [mileage, setMileage] = useState(String(vehicle.mileage))
  const [description, setDescription] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<unknown>(null)

  const km = Number(mileage)
  const mileageValid = mileage.trim() !== '' && Number.isInteger(km) && km >= 0
  const ready = mileageValid && (aggregate !== null || description.trim() !== '')
  const field = error instanceof ApiError ? FIELD_OF[error.code] : undefined
  const errorAt = (name: Field) => (field === name ? errorText(error) : undefined)
  // Правка поля снимает прежнюю ошибку сервера.
  const edit = <T,>(set: (value: T) => void) => (value: T) => {
    set(value)
    setError(null)
  }

  const save = (note: string | null): Promise<string> => {
    if (aggregate && kind === 'replacement') {
      const body = { replaced_at: date, mileage_at_replacement: km, description: note }
      return repo.replaceAggregateStatus(vehicle.id, aggregate.code, body).then(() => `Замена сохранена: ${aggregate.name}`)
    }
    const body = { aggregate_type_code: aggregate?.code ?? null, performed_at: date, mileage_at_service: km, description: note }
    return repo.createMaintenanceRecord(vehicle.id, body).then(() => (aggregate ? `Работа сохранена: ${aggregate.name}` : 'Работа сохранена'))
  }

  const submit = async (event: FormEvent) => {
    event.preventDefault()
    if (busy || !ready) return
    setBusy(true)
    setError(null)
    try {
      onSaved(await save(description.trim() || null))
    } catch (e) {
      setError(e)
      setBusy(false)
    }
  }

  return (
    <form
      onSubmit={submit}
      aria-label={aggregate ? `Замена или работа: ${aggregate.name}` : 'Другая работа'}
      className="grid gap-3 rounded-md border border-border-strong bg-surface p-3"
    >
      {aggregate && (
        <fieldset className="grid gap-2">
          <legend className="pb-1 text-label">Что сделано</legend>
          {KINDS.map((k) => (
            <label key={k.kind} className="flex cursor-pointer items-start gap-2 text-body-sm">
              <input
                type="radio"
                name={`maintenance-kind-${aggregate.code}`}
                className="mt-1 size-4 accent-(--ev-fg)"
                checked={kind === k.kind}
                onChange={() => edit(setKind)(k.kind)}
              />
              <span>
                {k.label}
                <span className="block text-caption text-fg-muted">{k.hint}</span>
              </span>
            </label>
          ))}
        </fieldset>
      )}
      <TextField
        label={kind === 'replacement' ? 'Дата замены' : 'Дата работы'}
        type="date"
        required
        max={today}
        value={date}
        error={errorAt('date')}
        onChange={(e) => edit(setDate)(e.target.value)}
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
          kind === 'replacement'
            ? `Не больше текущего пробега авто (${formatKm(vehicle.mileage)})`
            : `Больше текущего (${formatKm(vehicle.mileage)}) — пробег авто обновится`
        }
        error={errorAt('mileage') ?? (mileageValid ? undefined : 'Целое число километров, не меньше 0')}
        onChange={(e) => edit(setMileage)(e.target.value)}
      />
      <TextArea
        label={aggregate ? 'Комментарий' : 'Что сделано'}
        hint={aggregate ? 'Необязательно' : 'Обязательно для работы без агрегата'}
        required={!aggregate}
        maxLength={DESCRIPTION_MAX}
        value={description}
        error={errorAt('description')}
        onChange={(e) => edit(setDescription)(e.target.value)}
      />
      <InlineError error={field ? null : error} />
      <div className="flex justify-end gap-2">
        <Button type="button" variant="ghost" size="sm" onClick={onCancel}>
          Отмена
        </Button>
        <Button type="submit" size="sm" disabled={busy || !ready}>
          {busy ? 'Сохраняем…' : 'Сохранить'}
        </Button>
      </div>
    </form>
  )
}
