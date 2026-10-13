// Карточка пользователя (глава 22, ADR 0026 п. 4–7): роль сотрудника (инженер ↔ администратор),
// блокировка и разблокировка, сброс пароля, нерешённые тикеты инженера с переназначением. Своя учётная
// запись — только просмотр (п. 6); анонимизированный — «Данные удалены», без действий.
import { useState, type ReactNode } from 'react'
import {
  Button,
  Card,
  ConfirmDialog,
  EmptyState,
  ErrorState,
  InlineError,
  LoadingState,
  Select,
  TICKET_CATEGORY_LABELS,
  TICKET_STATUS_LABELS,
  USER_ROLE_LABELS,
  fetchAllPages,
  formatDate,
  formatDateTime,
  plural,
  useAsync,
  type AdminRepository,
  type AsyncState,
  type ButtonVariant,
  type Ticket,
  type UserPublic,
} from '@ev-servicedesk/web-shared'
import { useAdmin } from '../repo.ts'
import { passwordProblem } from './password.ts'
import { PasswordInput, PasswordReveal } from './PasswordParts.tsx'
import { UserStatus } from './Users.tsx'

/** Подтверждаемое действие: текст диалога и запрос собираются при нажатии кнопки — один диалог на все. */
interface Confirmation {
  title: string
  body: ReactNode
  label: string
  variant?: ButtonVariant
  act: () => Promise<unknown>
  /** После успеха (например, показать новый пароль). */
  done?: () => void
}

const PAGE = 100
/** Нерешённый тикет с исполнителем — только эти статусы: в `new` тикет попадает лишь со снятием исполнителя. */
const ASSIGNED_OPEN = ['in_progress', 'waiting_vendor'] as const

/** Нерешённые тикеты инженера — без истории решённых: по запросу на статус, параллельно, по сроку SLA. */
async function openTicketsOf(repo: AdminRepository, engineerId: number): Promise<Ticket[]> {
  const lists = await Promise.all(
    ASSIGNED_OPEN.map((status) =>
      fetchAllPages((page) => repo.listTickets({ assigned_engineer_id: engineerId, status, page, page_size: PAGE })),
    ),
  )
  return lists.flat().sort((a, b) => a.sla_due_at.localeCompare(b.sla_due_at))
}

export function UserCard({ userId, onBack }: { userId: number; onBack: () => void }) {
  const { repo } = useAdmin()
  const [version, setVersion] = useState(0)
  const user = useAsync(() => repo.getUser(userId), [repo, userId, version])
  // Тикеты есть у инженера и у бывшего инженера, ставшего администратором или заблокированного.
  const tickets = useAsync(
    () => (user.data && user.data.role !== 'client' ? openTicketsOf(repo, userId) : Promise.resolve<Ticket[]>([])),
    [repo, userId, user.data?.role, version],
  )
  const refresh = () => setVersion((v) => v + 1)

  return (
    <div className="grid gap-4">
      <div>
        <Button variant="ghost" size="sm" onClick={onBack}>
          ← К списку пользователей
        </Button>
      </div>
      {user.error ? (
        <ErrorState error={user.error} onRetry={user.reload} />
      ) : !user.data ? (
        <LoadingState />
      ) : (
        <div className="grid grid-cols-[minmax(0,1fr)_26rem] items-start gap-6">
          <EngineerTickets user={user.data} tickets={tickets} onChanged={refresh} />
          <UserActions key={`${user.data.role}-${user.data.is_active}`} user={user.data} openTickets={tickets.data?.length ?? 0} onChanged={refresh} />
        </div>
      )}
    </div>
  )
}

function UserActions({ user, openTickets, onChanged }: { user: UserPublic; openTickets: number; onChanged: () => void }) {
  const { repo, me } = useAdmin()
  const [pending, setPending] = useState<Confirmation | null>(null)
  const [role, setRole] = useState<'engineer' | 'admin'>(user.role === 'admin' ? 'admin' : 'engineer')
  const [password, setPassword] = useState('')
  const [problem, setProblem] = useState<string | null>(null)
  const [revealed, setRevealed] = useState<string | null>(null)
  const [error, setError] = useState<unknown>(null)
  const [busy, setBusy] = useState(false)
  const self = user.id === me.id
  const staff = user.role !== 'client'
  const deleted = user.phone === null
  const phone = user.phone ?? `#${user.id}`
  // Предупреждение о тикетах — при блокировке инженера и при смене его роли (ADR 0026 п. 7).
  const ticketsWarning = openTickets > 0 && (
    <p className="text-status-yellow-fg">
      У сотрудника {plural(openTickets, 'нерешённый тикет', 'нерешённых тикета', 'нерешённых тикетов')} — переназначьте{' '}
      {openTickets === 1 ? 'его' : 'их'} в списке слева.
    </p>
  )

  const confirm = async ({ act, done }: Confirmation) => {
    setBusy(true)
    setError(null)
    try {
      await act()
      done?.()
      onChanged()
    } catch (e) {
      setError(e)
    } finally {
      setPending(null)
      setBusy(false)
    }
  }

  const block = (): Confirmation => ({
    title: `Заблокировать ${phone}?`,
    label: 'Заблокировать',
    variant: 'danger',
    body: (
      <>
        <p>Вход будет запрещён, все сессии и push-уведомления на устройствах — отключены.</p>
        {ticketsWarning}
      </>
    ),
    act: () => repo.updateUser(user.id, { is_active: false }),
  })

  const unblock = (): Confirmation => ({
    title: `Разблокировать ${phone}?`,
    label: 'Разблокировать',
    body: <p>Пользователь снова сможет войти.</p>,
    act: () => repo.updateUser(user.id, { is_active: true }),
  })

  const changeRole = (next: 'engineer' | 'admin'): Confirmation => ({
    title: `Сделать ${phone} — ${USER_ROLE_LABELS[next].toLowerCase()}?`,
    label: 'Сменить роль',
    body: (
      <>
        <p>
          {next === 'admin'
            ? 'Администратор управляет регламентами, базой знаний, публикациями и пользователями; кабинет инженера ему недоступен.'
            : 'Инженер работает с тикетами в кабинете инженера; админ-панель ему недоступна.'}
        </p>
        <p>Роль меняется сразу, без повторного входа.</p>
        {next === 'admin' && ticketsWarning}
      </>
    ),
    act: () => repo.updateUser(user.id, { role: next }),
  })

  const resetPassword = (next: string): Confirmation => ({
    title: `Сбросить пароль ${phone}?`,
    label: 'Сбросить пароль',
    variant: 'danger',
    body: <p>Прежний пароль перестанет действовать, сотрудник выйдет на всех устройствах и войдёт с новым паролем.</p>,
    act: () => repo.resetUserPassword(user.id, next),
    done: () => {
      setRevealed(next)
      setPassword('')
    },
  })

  const askPassword = () => {
    const tooShort = passwordProblem(password)
    setProblem(tooShort)
    if (!tooShort) setPending(resetPassword(password))
  }

  return (
    <Card className="grid gap-4">
      <div className="grid gap-1">
        <h2 className="text-h3 tabular-nums">{phone}</h2>
        <p className="flex flex-wrap items-center gap-2 text-body-sm text-fg-muted">
          {USER_ROLE_LABELS[user.role]} · <UserStatus user={user} /> · с {formatDate(user.created_at)}
        </p>
      </div>

      {deleted ? (
        <p className="text-body-sm text-fg-muted">Данные пользователя удалены по отзыву согласия — действия недоступны.</p>
      ) : self ? (
        <p className="rounded-md bg-surface-subtle p-3 text-body-sm">
          Это ваша учётная запись. Роль, блокировку и пароль своей учётной записи меняет другой администратор.
        </p>
      ) : (
        <>
          {staff && (
            <section aria-labelledby="role-title" className="grid gap-2">
              <h3 id="role-title" className="text-label">
                Роль
              </h3>
              <div className="flex items-end gap-2">
                <Select label="Роль сотрудника" className="flex-1" value={role} onChange={(e) => setRole(e.target.value as 'engineer' | 'admin')}>
                  <option value="engineer">{USER_ROLE_LABELS.engineer}</option>
                  <option value="admin">{USER_ROLE_LABELS.admin}</option>
                </Select>
                <Button variant="secondary" disabled={busy || role === user.role} onClick={() => setPending(changeRole(role))}>
                  Сменить роль
                </Button>
              </div>
            </section>
          )}

          {staff && (
            <section aria-labelledby="password-title" className="grid gap-2">
              <h3 id="password-title" className="text-label">
                Пароль
              </h3>
              <PasswordInput label="Новый пароль" value={password} error={problem ?? undefined} onChange={setPassword} />
              <div>
                <Button variant="secondary" disabled={busy || !password} onClick={askPassword}>
                  Сбросить пароль
                </Button>
              </div>
              {revealed && <PasswordReveal phone={phone} password={revealed} onClose={() => setRevealed(null)} />}
            </section>
          )}

          <section aria-labelledby="access-title" className="grid gap-2">
            <h3 id="access-title" className="text-label">
              Доступ
            </h3>
            {user.is_active ? (
              <>
                <p className="text-body-sm text-fg-muted">
                  Заблокированный не сможет войти; его сессии завершатся сразу. Данные и тикеты сохранятся.
                </p>
                <div>
                  <Button variant="danger" disabled={busy} onClick={() => setPending(block())}>
                    Заблокировать
                  </Button>
                </div>
              </>
            ) : (
              <>
                <p className="text-body-sm text-fg-muted">Разблокированный снова сможет войти; прежние сессии не вернутся.</p>
                <div>
                  <Button variant="secondary" disabled={busy} onClick={() => setPending(unblock())}>
                    Разблокировать
                  </Button>
                </div>
              </>
            )}
          </section>
        </>
      )}

      <InlineError error={error} />

      {pending && (
        <ConfirmDialog
          title={pending.title}
          confirmLabel={pending.label}
          confirmVariant={pending.variant}
          busy={busy}
          onConfirm={() => void confirm(pending)}
          onCancel={() => setPending(null)}
        >
          {pending.body}
        </ConfirmDialog>
      )}
    </Card>
  )
}

function EngineerTickets({
  user,
  tickets,
  onChanged,
}: {
  user: UserPublic
  tickets: AsyncState<Ticket[]>
  onChanged: () => void
}) {
  const { repo } = useAdmin()
  const engineers = useAsync(
    () =>
      user.role === 'client'
        ? Promise.resolve<UserPublic[]>([])
        : fetchAllPages((page) => repo.listUsers({ role: 'engineer', is_active: true, page, page_size: PAGE })),
    [repo, user.role],
  )

  if (user.role === 'client') {
    return (
      <EmptyState title="Клиент">Клиент регистрируется в приложении сам; его авто и тикеты видны инженерам по тикетам.</EmptyState>
    )
  }

  return (
    <section aria-labelledby="tickets-title" className="grid gap-3">
      <h2 id="tickets-title" className="text-h3">
        Нерешённые тикеты сотрудника
      </h2>
      {tickets.error || engineers.error ? (
        <ErrorState error={tickets.error ?? engineers.error} onRetry={() => (tickets.error ? tickets.reload() : engineers.reload())} />
      ) : !tickets.data || !engineers.data ? (
        <LoadingState />
      ) : tickets.data.length === 0 ? (
        <EmptyState title="Нерешённых тикетов нет">Переназначать нечего.</EmptyState>
      ) : (
        <Card className="p-0">
          <table className="w-full text-body-sm">
            <thead className="text-left text-fg-muted">
              <tr className="border-b border-border">
                <th className="px-4 py-3 font-semibold">Тикет</th>
                <th className="px-4 py-3 font-semibold">Статус</th>
                <th className="px-4 py-3 font-semibold">Срок SLA</th>
                <th className="px-4 py-3 font-semibold">Переназначить</th>
              </tr>
            </thead>
            <tbody>
              {tickets.data.map((t) => (
                <ReassignRow
                  key={t.id}
                  ticket={t}
                  engineers={engineers.data!.filter((e) => e.id !== user.id)}
                  onDone={onChanged}
                />
              ))}
            </tbody>
          </table>
        </Card>
      )}
    </section>
  )
}

const QUEUE = 'queue'

function ReassignRow({ ticket, engineers, onDone }: { ticket: Ticket; engineers: UserPublic[]; onDone: () => void }) {
  const { repo } = useAdmin()
  const [target, setTarget] = useState('')
  const [error, setError] = useState<unknown>(null)
  const [busy, setBusy] = useState(false)

  const submit = async () => {
    setBusy(true)
    setError(null)
    try {
      await repo.assignTicket(ticket.id, target === QUEUE ? null : Number(target))
      onDone()
    } catch (e) {
      setError(e)
      setBusy(false)
    }
  }

  return (
    <tr className="border-b border-border last:border-b-0 align-top">
      <th scope="row" className="px-4 py-3 text-left font-normal">
        <span className="text-label">#{ticket.id}</span> · {TICKET_CATEGORY_LABELS[ticket.category]}
        <span className="block text-caption text-fg-muted">{ticket.summary}</span>
      </th>
      <td className="px-4 py-3">{TICKET_STATUS_LABELS[ticket.status]}</td>
      <td className={`px-4 py-3 ${ticket.is_overdue ? 'text-danger-text' : ''}`}>
        {formatDateTime(ticket.sla_due_at)}
        {ticket.is_overdue ? ' · просрочен' : ''}
      </td>
      <td className="px-4 py-3">
        <span className="flex items-end gap-2">
          <Select label={`Кому: тикет #${ticket.id}`} className="w-56" value={target} onChange={(e) => setTarget(e.target.value)}>
            <option value="">— выберите —</option>
            {engineers.map((e) => (
              <option key={e.id} value={e.id}>
                {e.phone ?? `Инженер #${e.id}`}
              </option>
            ))}
            <option value={QUEUE}>Вернуть в очередь</option>
          </Select>
          <Button size="sm" disabled={!target || busy} onClick={submit}>
            Переназначить
          </Button>
        </span>
        <InlineError error={error} />
      </td>
    </tr>
  )
}
