// Вход администратора на реальном API (глава 22, ADR 0026 п. 1): общий вход сотрудника `StaffSessionGate`
// с ролью admin — инженер и клиент получают отказ и выход.
import { StaffSessionGate, type AdminRepository, type ApiSession, type UserRole } from '@ev-servicedesk/web-shared'
import App from '../App.tsx'

const wrongRole = (role: UserRole) =>
  role === 'engineer'
    ? 'Админ-панель — только для администраторов. Инженер работает в кабинете инженера.'
    : 'Админ-панель — только для администраторов.'

export function SessionGate({ session, repo }: { session: ApiSession; repo: AdminRepository }) {
  return (
    <StaffSessionGate
      session={session}
      repo={repo}
      role="admin"
      title="Админ-панель"
      wrongRoleText={wrongRole}
      themeFallback="system"
    >
      {(logout) => <App repo={repo} onLogout={logout} />}
    </StaffSessionGate>
  )
}
