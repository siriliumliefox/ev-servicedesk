// Тексты кабинета инженера, общие для доски и карточки тикета.
import type { KnowledgeArticle } from '@ev-servicedesk/web-shared'

export function assigneeLabel(id: number | null | undefined, meId: number): string {
  if (id == null) return 'Не назначен'
  return id === meId ? 'Вы' : `Инженер #${id}`
}

/**
 * Текст сообщения клиенту из статьи. Ссылки на статью в приложении нет в контракте — заголовок + текст.
 * У «Устранения неполадок» шаги — в дереве решений, а текст — только вводный абзац (#112): ответ говорит,
 * где пройти шаги в приложении клиента (Поддержка → вкладка «Неполадки» → статья).
 */
export function articleMessage(article: KnowledgeArticle): string {
  const text = `${article.title}\n\n${article.content ?? ''}`.trim()
  if (article.article_type !== 'troubleshooting') return text
  return (
    `${text}\n\nПошаговая проверка — в приложении: Поддержка → Неполадки → «${article.title}». ` +
    'Если не поможет, напишите здесь, на каком шаге остановились.'
  )
}
