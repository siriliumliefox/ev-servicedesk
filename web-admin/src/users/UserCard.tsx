// Карточка пользователя (глава 22, ADR 0026 п. 4–7): роль сотрудника (инженер ↔ администратор),
// блокировка и разблокировка, сброс пароля, нерешённые тикеты инженера с переназначением. Своя учётная
// запись — только просмотр (п. 6); анонимизированный — «Данные удалены», без действий.
import { useState } from 'react'
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
  useAsync,
  type AsyncState,
  type Ticket,
  type UserPublic,
} from '@ev-servicedesk/web-shared'
import { useAdmin } from '../repo.ts'
import { passwordProblem } from './password.ts'
import { PasswordInput, PasswordReveal } from './PasswordParts.tsx'
import { UserStatus } from './Users.tsx'

type Pending = { kind: 'block' | 'unblock' } | { kind: 'role'; role: 'engineer' | 'admin' } | { kind: 'password' }

const PAGE = 100

/** Нерешённые тикеты, назначенные инженеру (`assigned_engineer_id`), — все страницы. */
async function openTicketsOf(repo: ReturnType<typeof useAdmin>['repo'], engineerId: number): Promise<Ticket[]> {
  const all = await fetchAllPages((page) => repo.listTickets({ assigned_engineer_id: engineerId, page, page_size: PAGE }))
  return all.filter((t) => t.status !== 'resolved')
}

function ticketsLabel(n: number): string {
  const mod10 = n % 10
  const mod100 = n % 100
  if (mod10 === 1 && mod100 !== 11) return `${n} нерешённый тикет`
  if (mod10 >= 2 && mod10 <= 4 && (mod100 < 12 || mod100 > 14)) return `${n} нерешённых тикета`
  return `${n} нерешённых тикетов`
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
  const [pending, setPending] = useState<Pending | null>(null)
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
  const ticketsWarning =
    openTickets > 0 ? `У сотрудника ${ticketsLabel(openTickets)} — переназначьте их в списке слева.` : null

  const run = async (action: () => Promise<unknown>, after?: () => void) => {
    setBusy(true)
    setError(null)
    try {
      await action()
      setPending(null)
      after?.()
      onChanged()
    } catch (e) {
      setError(e)
      setPending(null)
    } finally {
      setBusy(false)
    }
  }

  const confirm = () => {
    if (!pending) return
    if (pending.kind === 'block') void run(() => repo.updateUser(user.id, { is_active: false }))
    if (pending.kind === 'unblock') void run(() => repo.updateUser(user.id, { is_active: true }))
    if (pending.kind === 'role') void run(() => repo.updateUser(user.id, { role: pending.role }))
    if (pending.kind === 'password') {
      const next = password
      void run(
        () => repo.resetUserPassword(user.id, next),
        () => {
          setRevealed(next)
          setPassword('')
        },
      )
    }
  }

  const askPassword = () => {
    const tooShort = passwordProblem(password)
    setProblem(tooShort)
    if (!tooShort) setPending({ kind: 'password' })
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
                <Button variant="secondary" disabled={busy || role === user.role} onClick={() => setPending({ kind: 'role', role })}>
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
                  <Button variant="danger" disabled={busy} onClick={() => setPending({ kind: 'block' })}>
                    Заблокировать
                  </Button>
                </div>
              </>
            ) : (
              <>
                <p className="text-body-sm text-fg-muted">Разблокированный снова сможет войти; прежние сессии не вернутся.</p>
                <div>
                  <Button variant="secondary" disabled={busy} onClick={() => setPending({ kind: 'unblock' })}>
                    Разблокировать
                  </Button>
                </div>
              </>
            )}
          </section>
        </>
      )}

      <InlineError error={error} />

      {pending?.kind === 'block' && (
        <ConfirmDialog title={`Заблокировать ${phone}?`} confirmLabel="Заблокировать" confirmVariant="danger" busy={busy} onConfirm={confirm} onCancel={() => setPending(null)}>
          <p>Вход будет запрещён, все сессии и push-уведомления на устройствах — отключены.</p>
          {ticketsWarning && <p className="text-status-yellow-fg">{ticketsWarning}</p>}
        </ConfirmDialog>
      )}
      {pending?.kind === 'unblock' && (
        <ConfirmDialog title={`Разблокировать ${phone}?`} confirmLabel="Разблокировать" busy={busy} onConfirm={confirm} onCancel={() => setPending(null)}>
          <p>Пользователь снова сможет войти.</p>
        </ConfirmDialog>
      )}
      {pending?.kind === 'role' && (
        <ConfirmDialog
          title={`Сделать ${phone} — ${USER_ROLE_LABELS[pending.role].toLowerCase()}?`}
          confirmLabel="Сменить роль"
          busy={busy}
          onConfirm={confirm}
          onCancel={() => setPending(null)}
        >
          <p>
            {pending.role === 'admin'
              ? 'Администратор управляет регламентами, базой знаний, публикациями и пользователями; кабинет инженера ему недоступен.'
              : 'Инженер работает с тикетами в кабинете инженера; админ-панель ему недоступна.'}
          </p>
          <p>Роль меняется сразу, без повторного входа.</p>
          {pending.role === 'admin' && ticketsWarning && <p className="text-status-yellow-fg">{ticketsWarning}</p>}
        </ConfirmDialog>
      )}
      {pending?.kind === 'password' && (
        <ConfirmDialog title={`Сбросить пароль ${phone}?`} confirmLabel="Сбросить пароль" confirmVariant="danger" busy={busy} onConfirm={confirm} onCancel={() => setPending(null)}>
          <p>Прежний пароль перестанет действовать, сотрудник выйдет на всех устройствах и войдёт с новым паролем.</p>
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
