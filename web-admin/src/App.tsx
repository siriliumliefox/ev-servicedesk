// Админ-панель (Глава 8, прототип; ADR 0012): конструктор регламентов ТО, конструктор статей базы знаний,
// лента публикаций, дашборд аналитики (ТЗ 4.4, раздел 9). Раздел — в адресе: `#/regulations`.
import { useCallback, useMemo, useState } from 'react'
import {
  Button,
  DemoPanel,
  ErrorState,
  LoadingState,
  useAsync,
  useHashRoute,
  useTheme,
  type AdminRepository,
  type PrototypeRepository,
} from '@ev-servicedesk/web-shared'
import { ArticleEditor } from './articles/ArticleEditor.tsx'
import { ArticleList } from './articles/ArticleList.tsx'
import { Dashboard } from './dashboard/Dashboard.tsx'
import { Publications } from './publications/Publications.tsx'
import { Regulations } from './regulations/Regulations.tsx'
import { AdminContext, type AdminEnv } from './repo.ts'

const systemNow = () => new Date()

const SECTIONS = [
  { path: '/', label: 'Дашборд' },
  { path: '/regulations', label: 'Регламенты ТО' },
  { path: '/articles', label: 'База знаний' },
  { path: '/publications', label: 'Публикации' },
] as const

export default function App({
  repo,
  now = systemNow,
  demo,
}: {
  repo: AdminRepository
  now?: () => Date
  /** Панель «Демо» — только для прототипа. */
  demo?: PrototypeRepository
}) {
  const { theme, toggle } = useTheme('light')
  const [path, navigate] = useHashRoute()
  const [version, setVersion] = useState(0)
  const bump = useCallback(() => setVersion((v) => v + 1), [])
  const models = useAsync(() => repo.searchVehicleModels(), [repo, version])

  const env = useMemo<AdminEnv | null>(
    () => (models.data ? { repo, now, models: models.data } : null),
    [repo, now, models.data],
  )

  const section = SECTIONS.slice(1).find((s) => path.startsWith(s.path)) ?? SECTIONS[0]
  const article = /^\/articles\/(new|\d+)$/.exec(path)?.[1]

  return (
    <div className="grid min-h-screen grid-cols-[15rem_minmax(0,1fr)] bg-canvas text-fg">
      <nav aria-label="Разделы админ-панели" className="flex flex-col gap-1 border-r border-border bg-surface p-4">
        <p className="flex items-center gap-2 px-3 pb-4 text-h3">
          <span aria-hidden="true" className="size-3 rounded-full bg-primary" />
          EV-ServiceDesk
        </p>
        {SECTIONS.map((s) => (
          <a
            key={s.path}
            href={`#${s.path}`}
            aria-current={s === section ? 'page' : undefined}
            className={`rounded-md px-3 py-2 text-label no-underline ${
              s === section ? 'bg-fg text-canvas' : 'text-fg hover:bg-surface-subtle'
            }`}
          >
            {s.label}
          </a>
        ))}
      </nav>

      <div className="flex min-w-0 flex-col">
        <header className="flex items-center justify-between gap-4 border-b border-border bg-surface px-8 py-3">
          <h1 className="text-h2">Админ-панель · {section.label}</h1>
          <div className="flex items-center gap-3">
            {demo && <DemoPanel repo={demo} theme={theme} onToggleTheme={toggle} onChange={bump} />}
            <Button variant="secondary" size="sm" onClick={toggle} aria-pressed={theme === 'dark'}>
              {theme === 'dark' ? 'Светлая тема' : 'Тёмная тема'}
            </Button>
          </div>
        </header>

        <main className="mx-auto w-full max-w-400 p-8">
          {models.error ? (
            <ErrorState error={models.error} onRetry={models.reload} />
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
                    <ArticleEditor
                      articleId={article === 'new' ? null : Number(article)}
                      onSaved={(id) => navigate(`/articles/${id}`)}
                      onBack={() => navigate('/articles')}
                    />
                  ) : (
                    <ArticleList onOpen={(id) => navigate(`/articles/${id}`)} onCreate={() => navigate('/articles/new')} />
                  ))}
                {section.path === '/publications' && <Publications />}
              </div>
            </AdminContext.Provider>
          )}
        </main>
      </div>
    </div>
  )
}
