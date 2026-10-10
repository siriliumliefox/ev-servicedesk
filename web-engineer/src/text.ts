// Тексты кабинета инженера, общие для доски и карточки тикета.
import type { KnowledgeArticle } from '@ev-servicedesk/web-shared'

export function assigneeLabel(id: number | null | undefined, meId: number): string {
  if (id == null) return 'Не назначен'
  return id === meId ? 'Вы' : `Инженер #${id}`
}

/** Текст сообщения клиенту из статьи. Ссылки на статью в приложении нет в контракте — заголовок + текст. */
export function articleMessage(article: KnowledgeArticle): string {
  return `${article.title}\n\n${article.content ?? ''}`.trim()
}
