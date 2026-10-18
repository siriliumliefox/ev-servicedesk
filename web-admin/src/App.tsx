// Админ-панель (Глава 8 — прототип, ADR 0012; глава 22 — реальный API, ADR 0026): конструктор регламентов
// ТО, конструктор статей базы знаний, публикации, пользователи и роли, дашборд аналитики (ТЗ 4.4,
// раздел 9). Раздел — в адресе: `#/regulations`, карточка пользователя — `#/users/7`.
import { useCallback, useMemo, useState } from 'react'
import {
  Button,
  DemoPanel,
  ErrorState,
  LoadingState,
  ThemeSelect,
  ChangePasswordButton,
  useAsync,
  useHashRoute,
  useTheme,
  type AdminRepository,
  type PrototypeRepository,
} from '@ev-servicedesk/web-shared'
import { ArticleEditor, type Notice } from './articles/ArticleEditor.tsx'
import { ArticleList } from './articles/ArticleList.tsx'
import { Dashboard } from './dashboard/Dashboard.tsx'
import { Publications } from './publications/Publications.tsx'
import { Regulations } from './regulations/Regulations.tsx'
import { AdminContext, type AdminEnv } from './repo.ts'
import { UserCard } from './users/UserCard.tsx'
import { Users } from './users/Users.tsx'

const systemNow = () => new Date()

// hint — что в разделе (юзабилити-тест, U-08: «где публикация, а где руководство по проблеме»).
const SECTIONS = [
  { path: '/', label: 'Дашборд', hint: 'показатели поддержки' },
  { path: '/regulations', label: 'Регламенты ТО', hint: 'интервалы замены и пороги' },
  { path: '/articles', label: 'База знаний', hint: 'статьи и деревья неполадок' },
  { path: '/publications', label: 'Публикации', hint: 'рассылки: новости, акции, прошивки' },
  { path: '/users', label: 'Пользователи', hint: 'сотрудники, роли, блокировка' },
] as const

export default function App({
  repo,
  now = systemNow,
  demo,
  onLogout,
  onChangePassword,
}: {
  repo: AdminRepository
  now?: () => Date
  /** Панель «Демо» — только для прототипа. */
  demo?: PrototypeRepository
  /** Выход — только на реальном API (SessionGate). */
  onLogout?: () => void
  /** Смена своего пароля — только на реальном API (SessionGate, ADR 0029 п. 14). */
  onChangePassword?: (current: string, next: string) => Promise<void>
}) {
  // ADR 0026 п. 3: «как в системе» по умолчанию, выбор — в шапке.
  const { theme, preference, setPreference, toggle } = useTheme('system')
  const [path, navigate] = useHashRoute()
  const [version, setVersion] = useState(0)
  const bump = useCallback(() => setVersion((v) => v + 1), [])
  const base = useAsync(() => Promise.all([repo.searchVehicleModels(), repo.getCurrentUser()]), [repo, version])

  const env = useMemo<AdminEnv | null>(
    () => (base.data ? { repo, now, models: base.data[0], me: base.data[1] } : null),
    [repo, now, base.data],
  )

  const section = SECTIONS.slice(1).find((s) => path.startsWith(s.path)) ?? SECTIONS[0]
  const article = /^\/articles\/(new|\d+)$/.exec(path)?.[1]
  const userId = /^\/users\/(\d+)$/.exec(path)?.[1]
  // Итог «Сохранить и опубликовать» новой статьи — для редактора по её адресу; на другом адресе сбрасывается.
  const [flash, setFlash] = useState<{ id: string; notice: Notice } | null>(null)
  // Ушли с адреса статьи — итог устарел (сброс во время рендера, без эффекта: React перерисует сразу).
  if (flash && article !== flash.id) setFlash(null)

  return (
    <div className="grid min-h-screen grid-cols-[15rem_minmax(0,1fr)] bg-canvas text-fg">
      <nav aria-label="Разделы админ-панели" className="flex flex-col gap-1 border-r border-border bg-surface p-4">
        <p className="flex items-center gap-2 px-3 pb-4 text-h3">
          <span aria-hidden="true" className="size-3 rounded-full bg-primary" />
          EV-ServiceDesk
        </p>
        {SECTIONS.map((s, i) => (
          // Имя ссылки — название раздела, пояснение — описание (aria-describedby).
          <a
            key={s.path}
            href={`#${s.path}`}
            aria-current={s === section ? 'page' : undefined}
            aria-labelledby={`nav-${i}-label`}
            aria-describedby={`nav-${i}-hint`}
            className={`grid rounded-md px-3 py-2 no-underline ${
              s === section ? 'bg-fg text-canvas' : 'text-fg hover:bg-surface-subtle'
            }`}
          >
            <span id={`nav-${i}-label`} className="text-label">
              {s.label}
            </span>
            <span id={`nav-${i}-hint`} className={`text-caption ${s === section ? 'opacity-80' : 'text-fg-muted'}`}>
              {s.hint}
            </span>
          </a>
        ))}
      </nav>

      <div className="flex min-w-0 flex-col">
        <header className="flex items-center justify-between gap-4 border-b border-border bg-surface px-8 py-3">
          <h1 className="text-h2">Админ-панель · {section.label}</h1>
          <div className="flex items-center gap-3">
            {env && <span className="text-body-sm text-fg-muted">Администратор {env.me.phone ?? `#${env.me.id}`}</span>}
            {demo && <DemoPanel repo={demo} theme={theme} onToggleTheme={toggle} onChange={bump} />}
            <ThemeSelect value={preference} onChange={setPreference} />
            {onChangePassword && <ChangePasswordButton onChange={onChangePassword} />}
            {onLogout && (
              <Button variant="secondary" size="sm" onClick={onLogout}>
                Выйти
              </Button>
            )}
          </div>
        </header>

        <main className="mx-auto w-full max-w-400 p-8">
          {base.error ? (
            <ErrorState error={base.error} onRetry={base.reload} />
          ) : !env ? (
            <LoadingState />
          ) : (
            <AdminContext.Provider value={env}>
              {/* key: панель «Демо» сбрасывает данные — экран монтируется заново и перечитывает их. */}
              <div key={version}>
                {section.path === '/' && <Dashboard />}
                {section.path === '/regulations' && <Regulations />}
                {section.path === '/articles' &&
                  (article ? (
                    // key: другая статья (в т. ч. «Назад»/«Вперёд» браузера) — редактор с чистого листа,
                    // без итога публикации прошлой статьи.
                    <ArticleEditor
                      key={article}
                      articleId={article === 'new' ? null : Number(article)}
                      initialNotice={flash?.id === article ? flash.notice : null}
                      onSaved={(id, notice) => {
                        if (notice) setFlash({ id: String(id), notice })
                        navigate(`/articles/${id}`)
                      }}
                      onBack={() => navigate('/articles')}
                    />
                  ) : (
                    <ArticleList onOpen={(id) => navigate(`/articles/${id}`)} onCreate={() => navigate('/articles/new')} />
                  ))}
                {section.path === '/publications' && <Publications />}
                {section.path === '/users' &&
                  (userId ? (
                    <UserCard key={userId} userId={Number(userId)} onBack={() => navigate('/users')} />
                  ) : (
                    <Users onOpen={(id) => navigate(`/users/${id}`)} />
                  ))}
              </div>
            </AdminContext.Provider>
          )}
        </main>
      </div>
    </div>
  )
}
