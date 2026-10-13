// Доступ к данным веб-клиентов (Глава 8, ADR 0012). Методы — операции OpenAPI v1 (имя = operationId),
// роли — `x-required-roles`. Прототип: `PrototypeRepository` (фикстуры в памяти); HTTP —
// `HttpEngineerRepository` (глава 21, ADR 0025 п. 6), экраны от реализации не зависят.
import type {
  AggregateStatusThresholds,
  AggregateStatusThresholdsUpdateRequest,
  AggregateType,
  AggregateTypeCreateRequest,
  ArticleType,
  DateRange,
  DecisionTreeNode,
  DecisionTreeNodeCreateRequest,
  DecisionTreeValidationResult,
  FirmwareRelease,
  FirmwareReleaseCreateRequest,
  KnowledgeArticle,
  KnowledgeArticleCreateRequest,
  KnowledgeArticleList,
  KnowledgeArticleUpdateRequest,
  MaintenanceConversionStats,
  MaintenanceRecordList,
  MaintenanceRegulation,
  MaintenanceRegulationCreateRequest,
  Notification,
  NotificationCreateRequest,
  ProblemModelStats,
  TicketCategory,
  Ticket,
  TicketDetail,
  TicketList,
  TicketMessage,
  TicketResolutionStats,
  TicketStatus,
  UserPublic,
  VehicleModel,
} from "./models.ts";

/**
 * Ошибка API в едином формате `Error` контракта; `NETWORK` — запрос не дошёл до сервера.
 * `message` можно показывать в UI (прототип пишет его сам, HTTP-слой — текст по коду, `errors.ts`).
 */
export class ApiError extends Error {
  readonly code: string;
  readonly status: number;
  /** Поле, не прошедшее валидацию (`error.details.field` при 422). */
  readonly field?: string;
  /** Секунд до повтора (`Retry-After` при 429). */
  readonly retryAfter?: number;

  constructor(code: string, message: string, status: number, field?: string, retryAfter?: number) {
    super(message);
    this.name = "ApiError";
    this.code = code;
    this.status = status;
    this.field = field;
    this.retryAfter = retryAfter;
  }
}

export interface PageQuery {
  page?: number;
  page_size?: number;
}

export interface ListTicketsQuery extends PageQuery {
  status?: TicketStatus;
  category?: TicketCategory;
  assigned_engineer_id?: number;
  overdue?: boolean;
  /** Решённые не раньше момента (RFC 3339, контракт 1.10.0) — колонка «Решено». */
  resolved_since?: string;
}

/** Состояние подписки на события тикета: подключение, события идут, нет связи (переподключение). */
export type TicketLiveState = "connecting" | "live" | "offline";

/**
 * События тикета (WebSocket `/tickets/{id}/ws`, docs/asyncapi.yaml). Доставка не гарантирована:
 * после каждого `onReady` экран догружает пропущенное через REST (`after_id`), сообщения — по `id`.
 */
export interface TicketLiveHandlers {
  onReady(): void;
  onMessage(message: TicketMessage): void;
  onTicket(ticket: Ticket): void;
  /** Доступ к тикету потерян (переназначен, удалён) — подписка закрыта, переподключения не будет. */
  onLost(): void;
  onState?(state: TicketLiveState): void;
}

export interface ListArticlesQuery {
  vehicle_model_id?: number;
  article_type?: ArticleType;
  search?: string;
}

/** Общие операции: профиль и справочники (client/engineer/admin). */
export interface CommonRepository {
  getCurrentUser(): Promise<UserPublic>;
  searchVehicleModels(): Promise<VehicleModel[]>;
  listAggregateTypes(): Promise<AggregateType[]>;
  listKnowledgeArticles(query?: ListArticlesQuery): Promise<KnowledgeArticleList>;
}

/** Рабочее место инженера (ТЗ 4.3). */
export interface EngineerRepository extends CommonRepository {
  /** Одна страница: колонка доски выгружает страницы сама (`fetchPages`). */
  listTickets(query?: ListTicketsQuery): Promise<TicketList>;
  getTicket(ticketId: number): Promise<TicketDetail>;
  claimTicket(ticketId: number): Promise<TicketDetail>;
  updateTicketStatus(ticketId: number, status: TicketStatus): Promise<TicketDetail>;
  /** Вся история (все страницы) или только сообщения с `id > after_id` — догрузка после `ready`. */
  listTicketMessages(ticketId: number, query?: { after_id?: number }): Promise<TicketMessage[]>;
  createTicketMessage(ticketId: number, body: string): Promise<TicketMessage>;
  listMaintenanceRecords(vehicleId: number, query?: PageQuery): Promise<MaintenanceRecordList>;
  /** Подписка на события тикета; возвращает отписку. */
  watchTicket(ticketId: number, handlers: TicketLiveHandlers): () => void;
}

/** Администрирование, база знаний и аналитика (ТЗ 4.4). */
export interface AdminRepository extends CommonRepository {
  createAggregateType(body: AggregateTypeCreateRequest): Promise<AggregateType>;
  listMaintenanceRegulations(query: { vehicle_model_id?: number; include_archived?: boolean }): Promise<MaintenanceRegulation[]>;
  reviseMaintenanceRegulation(body: MaintenanceRegulationCreateRequest): Promise<MaintenanceRegulation>;
  archiveMaintenanceRegulation(regulationId: number): Promise<void>;
  getAggregateStatusThresholds(): Promise<AggregateStatusThresholds>;
  updateAggregateStatusThresholds(body: AggregateStatusThresholdsUpdateRequest): Promise<AggregateStatusThresholds>;

  getKnowledgeArticle(articleId: number): Promise<KnowledgeArticle>;
  createKnowledgeArticle(body: KnowledgeArticleCreateRequest): Promise<KnowledgeArticle>;
  updateKnowledgeArticle(articleId: number, body: KnowledgeArticleUpdateRequest): Promise<KnowledgeArticle>;
  unpublishKnowledgeArticle(articleId: number): Promise<void>;
  listDecisionTreeNodes(articleId: number): Promise<DecisionTreeNode[]>;
  createDecisionTreeNode(articleId: number, body: DecisionTreeNodeCreateRequest): Promise<DecisionTreeNode>;
  updateDecisionTreeNode(nodeId: number, body: DecisionTreeNodeCreateRequest): Promise<DecisionTreeNode>;
  deleteDecisionTreeNode(nodeId: number): Promise<void>;
  validateDecisionTree(articleId: number): Promise<DecisionTreeValidationResult>;

  createNotification(body: NotificationCreateRequest): Promise<Notification>;
  /**
   * Лента опубликованного для админа. В контракте v1 операции НЕТ (`GET /notifications` — только client):
   * открытый вопрос ADR 0012, решение — глава 15. Прототип отдаёт фикстуры и опубликованное в сессии.
   */
  listPublishedNotifications(): Promise<Notification[]>;
  listFirmwareReleases(query?: { vehicle_model_id?: number }): Promise<FirmwareRelease[]>;
  createFirmwareRelease(body: FirmwareReleaseCreateRequest): Promise<FirmwareRelease>;

  getTicketResolutionStats(range: DateRange): Promise<TicketResolutionStats>;
  listProblemModels(range: DateRange): Promise<ProblemModelStats[]>;
  getMaintenanceConversionStats(range: DateRange): Promise<MaintenanceConversionStats>;
}
