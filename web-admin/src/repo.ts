// Репозиторий админ-панели — через контекст: экраны зависят от интерфейса AdminRepository, а не от
// реализации — прототип (ADR 0012) или реальный API (`HttpAdminRepository`, ADR 0026 п. 2).
import { createContext, useContext } from 'react'
import type { AdminRepository, UserPublic, VehicleModel } from '@ev-servicedesk/web-shared'

export interface AdminEnv {
  repo: AdminRepository
  now: () => Date
  /** Справочник моделей (`searchVehicleModels`) — нужен почти на каждом экране. */
  models: VehicleModel[]
  /** Кто вошёл: свою учётную запись нельзя понизить или заблокировать из UI (ADR 0026 п. 6). */
  me: UserPublic
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
