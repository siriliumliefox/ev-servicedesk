// Уведомление о результате действия — из любого места кабинета (провайдер — NoticeProvider).
import { createContext, useContext } from 'react'

export type NoticeTone = 'info' | 'error'

export const NoticeContext = createContext<(text: string, tone?: NoticeTone) => void>(() => undefined)

export function useNotify() {
  return useContext(NoticeContext)
}
