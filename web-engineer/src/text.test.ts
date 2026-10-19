import { describe, expect, it } from 'vitest'
import type { KnowledgeArticle } from '@ev-servicedesk/web-shared'
import { articleMessage } from './text.ts'

const article = (over: Partial<KnowledgeArticle>): KnowledgeArticle =>
  ({
    id: 1,
    title: 'Нет звука или не работает Bluetooth-аудио',
    content: 'Звук пропадает по разным причинам — причины и шаги разные.',
    article_type: 'troubleshooting',
    is_published: true,
    ...over,
  }) as KnowledgeArticle

describe('articleMessage — быстрый ответ статьёй', () => {
  it('руководство — заголовок и текст статьи', () => {
    expect(articleMessage(article({ article_type: 'guide', title: 'Настройка APN', content: 'APN — internet' }))).toBe(
      'Настройка APN\n\nAPN — internet',
    )
  })

  // #112: шаги «Устранения неполадок» — в дереве решений приложения, а не в тексте статьи.
  it('устранение неполадок — где пройти шаги в приложении', () => {
    const text = articleMessage(article({}))
    expect(text).toMatch(/^Нет звука или не работает Bluetooth-аудио\n\nЗвук пропадает/)
    expect(text).toContain('Поддержка → Неполадки → «Нет звука или не работает Bluetooth-аудио»')
    expect(text).toMatch(/напишите здесь/)
  })
})
