// Вход инженера на реальном API (глава 21, ADR 0025 п. 1, 3): общий вход сотрудника `StaffSessionGate`
// (web-shared, глава 22) с ролью engineer — client и admin получают отказ.
import { StaffSessionGate, type ApiSession, type EngineerRepository, type UserRole } from '@ev-servicedesk/web-shared'
import App from '../App.tsx'

const wrongRole = (role: UserRole) =>
  role === 'admin'
    ? 'Кабинет инженера — только для инженеров. Администратор работает в админ-панели.'
    : 'Кабинет инженера — только для инженеров.'

export function SessionGate({ session, repo }: { session: ApiSession; repo: EngineerRepository }) {
  return (
    <StaffSessionGate
      session={session}
      repo={repo}
      role="engineer"
      title="Кабинет инженера"
      wrongRoleText={wrongRole}
      themeFallback="dark"
    >
      {(logout, changePassword) => <App repo={repo} onLogout={logout} onChangePassword={changePassword} />}
    </StaffSessionGate>
  )
}
