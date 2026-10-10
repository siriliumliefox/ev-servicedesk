// Репозиторий админ-панели — через контекст: экраны зависят от интерфейса AdminRepository, а не от
// прототипа (ADR 0012). Глава 22 подставит HTTP-реализацию.
import { createContext, useContext } from 'react'
import type { AdminRepository, VehicleModel } from '@ev-servicedesk/web-shared'

export interface AdminEnv {
  repo: AdminRepository
  now: () => Date
  /** Справочник моделей (`searchVehicleModels`) — нужен почти на каждом экране. */
  models: VehicleModel[]
}

export const AdminContext = createContext<AdminEnv | null>(null)

export function useAdmin(): AdminEnv {
  const env = useContext(AdminContext)
  if (!env) throw new Error('AdminContext не задан')
  return env
}

export function modelName(models: VehicleModel[], id: number | null | undefined): string {
  if (id == null) return 'Все модели'
  const m = models.find((x) => x.id === id)
  return m ? `${m.brand} ${m.model}` : `Модель #${id}`
}
