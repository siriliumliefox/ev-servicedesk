// Подписи перечислений контракта для интерфейса (одинаковые в кабинете инженера и админ-панели).
import type { ArticleType, NotificationType, TicketCategory, TicketStatus } from "./models.ts";

export const TICKET_STATUS_LABELS: Record<TicketStatus, string> = {
  new: "Новые",
  in_progress: "В работе",
  waiting_vendor: "Ожидает вендора",
  resolved: "Решено",
};

export const TICKET_CATEGORY_LABELS: Record<TicketCategory, string> = {
  navigation: "Навигация",
  audio: "Аудио",
  sim: "SIM / связь",
  app_crash: "Сбой приложения",
  maintenance: "ТО",
};

export const ARTICLE_TYPE_LABELS: Record<ArticleType, string> = {
  guide: "Инструкция",
  troubleshooting: "Устранение неполадок",
};

export const NOTIFICATION_TYPE_LABELS: Record<NotificationType, string> = {
  news: "Новость",
  promo: "Акция",
  maintenance: "Регламент ТО",
  firmware: "Прошивка",
};
