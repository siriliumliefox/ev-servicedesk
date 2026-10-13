// Пользователи и роли (ТЗ 4.4; глава 22, ADR 0026 п. 4): список с фильтрами роли и блокировки, поиск по
// телефону, создание сотрудника (инженер или администратор). Клиенты регистрируются сами — их здесь можно
// только найти и заблокировать (в карточке). Глоссарий: «Учётная запись сотрудника», «Блокировка пользователя».
import { useState, type FormEvent } from 'react'
import {
  Badge,
  Button,
  Card,
  Chip,
  EmptyState,
  ErrorState,
  InlineError,
  LoadingState,
  Select,
  TextField,
  USER_ROLE_LABELS,
  formatDate,
  useAsync,
  type UserPublic,
  type UserRole,
} from '@ev-servicedesk/web-shared'
import { useAdmin } from '../repo.ts'
import { passwordProblem } from './password.ts'
import { PasswordInput, PasswordReveal } from './PasswordParts.tsx'

type RoleFilter = UserRole | 'all'
type ActiveFilter = 'all' | 'active' | 'blocked'

const ROLE_FILTERS: [RoleFilter, string][] = [
  ['all', 'Все'],
  ['engineer', 'Инженеры'],
  ['admin', 'Администраторы'],
  ['client', 'Клиенты'],
]
const ACTIVE_FILTERS: [ActiveFilter, string][] = [
  ['all', 'Все'],
  ['active', 'Активные'],
  ['blocked', 'Заблокированные'],
]
const PAGE_SIZE = 20

/** Телефон для поиска: только цифры и «+», до 16 символов (search контракта). */
const searchValue = (raw: string) => raw.replace(/[^\d+]/g, '').slice(0, 16)

export function UserStatus({ user }: { user: UserPublic }) {
  if (user.phone === null) return <Badge>Данные удалены</Badge>
  return user.is_active ? <Badge tone="success">Активен</Badge> : <Badge tone="danger">Заблокирован</Badge>
}

export function Users({ onOpen }: { onOpen: (id: number) => void }) {
  const { repo } = useAdmin()
  const [role, setRole] = useState<RoleFilter>('all')
  const [active, setActive] = useState<ActiveFilter>('all')
  const [search, setSearch] = useState('')
  const [page, setPage] = useState(1)
  const [version, setVersion] = useState(0)
  const query = {
    page,
    page_size: PAGE_SIZE,
    ...(role === 'all' ? {} : { role }),
    ...(active === 'all' ? {} : { is_active: active === 'active' }),
    ...(searchValue(search) ? { search: searchValue(search) } : {}),
  }
  const data = useAsync(() => repo.listUsers(query), [repo, role, active, search, page, version])
  // Смена фильтра — с первой страницы.
  const filter = <T,>(set: (v: T) => void) => (value: T) => {
    set(value)
    setPage(1)
  }

  return (
    <div className="grid grid-cols-[minmax(0,1fr)_24rem] items-start gap-6">
      <section aria-labelledby="users-title" className="grid gap-4">
        <h2 id="users-title" className="sr-only">
          Список пользователей
        </h2>
        <div className="flex flex-wrap items-end gap-x-6 gap-y-3">
          <TextField
            label="Поиск по телефону"
            type="search"
            inputMode="tel"
            className="w-64"
            placeholder="+375 29…"
            value={search}
            onChange={(e) => filter(setSearch)(e.target.value)}
          />
          <div role="group" aria-label="Роль" className="flex items-center gap-2">
            <span className="text-label text-fg-muted">Роль</span>
            {ROLE_FILTERS.map(([value, label]) => (
              <Chip key={value} selected={role === value} onClick={() => filter(setRole)(value)}>
                {label}
              </Chip>
            ))}
          </div>
          <div role="group" aria-label="Статус" className="flex items-center gap-2">
            <span className="text-label text-fg-muted">Статус</span>
            {ACTIVE_FILTERS.map(([value, label]) => (
              <Chip key={value} selected={active === value} onClick={() => filter(setActive)(value)}>
                {label}
              </Chip>
            ))}
          </div>
        </div>

        {data.error ? (
          <ErrorState error={data.error} onRetry={data.reload} />
        ) : !data.data ? (
          <LoadingState />
        ) : data.data.items.length === 0 ? (
          <EmptyState title="Никого не найдено">Измените фильтры или поиск.</EmptyState>
        ) : (
          <>
            <Card className="p-0">
              <table className="w-full text-body-sm">
                <thead className="text-left text-fg-muted">
                  <tr className="border-b border-border">
                    <th className="px-4 py-3 font-semibold">Телефон</th>
                    <th className="px-4 py-3 font-semibold">Роль</th>
                    <th className="px-4 py-3 font-semibold">Статус</th>
                    <th className="px-4 py-3 font-semibold">Создан</th>
                  </tr>
                </thead>
                <tbody>
                  {data.data.items.map((u) => (
                    <tr key={u.id} className="border-b border-border last:border-b-0 hover:bg-surface-subtle">
                      <th scope="row" className="px-4 py-3 text-left font-normal">
                        <a
                          href={`#/users/${u.id}`}
                          onClick={(e) => {
                            e.preventDefault()
                            onOpen(u.id)
                          }}
                          className="text-label text-fg tabular-nums"
                        >
                          {u.phone ?? `Пользователь #${u.id}`}
                        </a>
                      </th>
                      <td className="px-4 py-3">{USER_ROLE_LABELS[u.role]}</td>
                      <td className="px-4 py-3">
                        <UserStatus user={u} />
                      </td>
                      <td className="px-4 py-3">{formatDate(u.created_at)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </Card>
            {data.data.meta.total_pages > 1 && (
              <nav aria-label="Страницы" className="flex items-center gap-3 text-body-sm">
                <Button size="sm" variant="secondary" disabled={page <= 1} onClick={() => setPage((p) => p - 1)}>
                  Назад
                </Button>
                <span>
                  Страница {data.data.meta.page} из {data.data.meta.total_pages} · всего {data.data.meta.total_items}
                </span>
                <Button
                  size="sm"
                  variant="secondary"
                  disabled={page >= data.data.meta.total_pages}
                  onClick={() => setPage((p) => p + 1)}
                >
                  Вперёд
                </Button>
              </nav>
            )}
          </>
        )}
      </section>

      <NewStaffForm onCreated={() => setVersion((v) => v + 1)} />
    </div>
  )
}

function NewStaffForm({ onCreated }: { onCreated: () => void }) {
  const { repo } = useAdmin()
  const [phone, setPhone] = useState('+375')
  const [role, setRole] = useState<'engineer' | 'admin'>('engineer')
  const [password, setPassword] = useState('')
  const [problem, setProblem] = useState<string | null>(null)
  const [error, setError] = useState<unknown>(null)
  const [busy, setBusy] = useState(false)
  const [created, setCreated] = useState<{ phone: string; password: string } | null>(null)

  const submit = async (e: FormEvent) => {
    e.preventDefault()
    setError(null)
    const tooShort = passwordProblem(password)
    setProblem(tooShort)
    if (tooShort) return
    setBusy(true)
    const normalized = phone.replace(/[\s()-]/g, '')
    try {
      await repo.createStaffUser({ phone: normalized, role, password })
      setCreated({ phone: normalized, password })
      setPhone('+375')
      setPassword('')
      onCreated()
    } catch (err) {
      setError(err)
    } finally {
      setBusy(false)
    }
  }

  return (
    <Card>
      <form onSubmit={submit} className="grid gap-4" aria-labelledby="new-staff-title">
        <h2 id="new-staff-title" className="text-h3">
          Новый сотрудник
        </h2>
        <p className="text-body-sm text-fg-muted">
          Сотрудник входит в кабинет инженера или админ-панель по телефону и паролю. Клиента сотрудником сделать нельзя —
          у сотрудника должен быть свой номер.
        </p>
        <TextField
          label="Телефон"
          type="tel"
          inputMode="tel"
          autoComplete="off"
          hint="Формат +375XXXXXXXXX"
          required
          value={phone}
          onChange={(e) => setPhone(e.target.value)}
        />
        <Select label="Роль сотрудника" value={role} onChange={(e) => setRole(e.target.value as 'engineer' | 'admin')}>
          <option value="engineer">{USER_ROLE_LABELS.engineer}</option>
          <option value="admin">{USER_ROLE_LABELS.admin}</option>
        </Select>
        <PasswordInput label="Пароль" value={password} error={problem ?? undefined} onChange={setPassword} />
        <InlineError error={error} />
        {created && <PasswordReveal phone={created.phone} password={created.password} onClose={() => setCreated(null)} />}
        <Button type="submit" disabled={busy}>
          Создать сотрудника
        </Button>
      </form>
    </Card>
  )
}
