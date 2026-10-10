// Репозиторий и часы кабинета инженера — через контекст: экраны зависят от интерфейса EngineerRepository,
// а не от прототипа (ADR 0012). Глава 21 подставит HTTP-реализацию.
import { createContext, useContext } from 'react'
import type { EngineerRepository } from '@ev-servicedesk/web-shared'

export interface EngineerEnv {
  repo: EngineerRepository
  now: () => Date
  /** id текущего инженера (`getCurrentUser`). */
  meId: number
}

export const EngineerContext = createContext<EngineerEnv | null>(null)

export function useEngineer(): EngineerEnv {
  const env = useContext(EngineerContext)
  if (!env) throw new Error('EngineerContext не задан')
  return env
}
