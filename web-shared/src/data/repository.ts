// Доступ к данным веб-клиентов (Глава 8, ADR 0012). Методы — операции OpenAPI v1 (имя = operationId),
// роли — `x-required-roles`. Прототип: `PrototypeRepository` (фикстуры в памяти); HTTP —
// `HttpEngineerRepository` (глава 21, ADR 0025 п. 6) и `HttpAdminRepository` (глава 22, ADR 0026 п. 2),
// экраны от реализации не зависят.
import type {
  AggregateReplaceRequest,
  AggregateStatus,
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
  KnowledgeArticleRevision,
  KnowledgeArticleRevisionSummary,
  KnowledgeArticleUpdateRequest,
  MaintenanceConversionStats,
  MaintenanceRecord,
  MaintenanceRecordCreateRequest,
  MaintenanceRecordList,
  MaintenanceRegulation,
  MaintenanceRegulationCreateRequest,
  Notification,
  NotificationAudiencePreview,
  NotificationCreateRequest,
  ProblemModelStats,
  PublicationType,
  PublishedNotificationList,
  StaffUserCreateRequest,
  TicketCategory,
  Ticket,
  TicketDetail,
  TicketList,
  TicketMessage,
  TicketResolutionStats,
  TicketStatus,
  UserList,
  UserPublic,
  UserRole,
  UserUpdateRequest,
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

export interface ListArticlesQuery extends PageQuery {
  vehicle_model_id?: number;
  article_type?: ArticleType;
  /** Только персонал (admin видит и черновики). */
  is_published?: boolean;
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
  /**
   * `clientRequestId` — ключ повтора (ADR 0031): повтор той же отправки после сбоя сети с тем же
   * ключом возвращает уже записанное сообщение, а не дубль.
   */
  createTicketMessage(ticketId: number, body: string, clientRequestId?: string): Promise<TicketMessage>;
  listMaintenanceRecords(vehicleId: number, query?: PageQuery): Promise<MaintenanceRecordList>;
  /** Замена агрегата (E-05): сброс счётчика «светофора» и запись в истории ТО одним вызовом. */
  replaceAggregateStatus(vehicleId: number, aggregateTypeCode: string, body: AggregateReplaceRequest): Promise<AggregateStatus>;
  /** Работа без замены (осмотр, долив) или общая работа без агрегата — счётчик не сбрасывает. */
  createMaintenanceRecord(vehicleId: number, body: MaintenanceRecordCreateRequest): Promise<MaintenanceRecord>;
  /** Подписка на события тикета; возвращает отписку. */
  watchTicket(ticketId: number, handlers: TicketLiveHandlers): () => void;
}

export interface ListUsersQuery extends PageQuery {
  role?: UserRole;
  is_active?: boolean;
  /** Подстрока телефона (до 16 символов). */
  search?: string;
}

export interface ListPublishedQuery extends PageQuery {
  type?: PublicationType;
  target_vehicle_model_id?: number;
}

/** Фильтры дашборда: период и то, что поддерживает операция (ADR 0026 п. 11). */
export interface AnalyticsQuery extends DateRange {
  vehicle_model_id?: number;
  category?: TicketCategory;
}

/** Администрирование, база знаний, пользователи и аналитика (ТЗ 4.4; глава 22, ADR 0026). */
export interface AdminRepository extends CommonRepository {
  createAggregateType(body: AggregateTypeCreateRequest): Promise<AggregateType>;
  /** Все страницы. */
  listMaintenanceRegulations(query: { vehicle_model_id?: number; include_archived?: boolean }): Promise<MaintenanceRegulation[]>;
  reviseMaintenanceRegulation(body: MaintenanceRegulationCreateRequest): Promise<MaintenanceRegulation>;
  archiveMaintenanceRegulation(regulationId: number): Promise<void>;
  getAggregateStatusThresholds(): Promise<AggregateStatusThresholds>;
  updateAggregateStatusThresholds(body: AggregateStatusThresholdsUpdateRequest): Promise<AggregateStatusThresholds>;

  getKnowledgeArticle(articleId: number): Promise<KnowledgeArticle>;
  createKnowledgeArticle(body: KnowledgeArticleCreateRequest): Promise<KnowledgeArticle>;
  updateKnowledgeArticle(articleId: number, body: KnowledgeArticleUpdateRequest): Promise<KnowledgeArticle>;
  unpublishKnowledgeArticle(articleId: number): Promise<void>;
  /** История опубликованных версий (все страницы), новые — первыми. */
  listKnowledgeArticleRevisions(articleId: number): Promise<KnowledgeArticleRevisionSummary[]>;
  getKnowledgeArticleRevision(articleId: number, version: number): Promise<KnowledgeArticleRevision>;
  listDecisionTreeNodes(articleId: number): Promise<DecisionTreeNode[]>;
  createDecisionTreeNode(articleId: number, body: DecisionTreeNodeCreateRequest): Promise<DecisionTreeNode>;
  updateDecisionTreeNode(nodeId: number, body: DecisionTreeNodeCreateRequest): Promise<DecisionTreeNode>;
  deleteDecisionTreeNode(nodeId: number): Promise<void>;
  validateDecisionTree(articleId: number): Promise<DecisionTreeValidationResult>;

  createNotification(body: NotificationCreateRequest): Promise<Notification>;
  /** Сколько клиентов и устройств получат публикацию — ничего не записывает (U-45). */
  previewNotificationAudience(body: NotificationCreateRequest): Promise<NotificationAudiencePreview>;
  /** Лента опубликованного со статистикой доставки — одна страница, новые первыми. */
  listPublishedNotifications(query?: ListPublishedQuery): Promise<PublishedNotificationList>;
  /** Все страницы. */
  listFirmwareReleases(query?: { vehicle_model_id?: number }): Promise<FirmwareRelease[]>;
  createFirmwareRelease(body: FirmwareReleaseCreateRequest): Promise<FirmwareRelease>;

  listUsers(query?: ListUsersQuery): Promise<UserList>;
  getUser(userId: number): Promise<UserPublic>;
  createStaffUser(body: StaffUserCreateRequest): Promise<UserPublic>;
  updateUser(userId: number, body: UserUpdateRequest): Promise<UserPublic>;
  resetUserPassword(userId: number, password: string): Promise<void>;
  /** Тикеты инженера в карточке пользователя — переназначение (ADR 0026 п. 7). */
  listTickets(query?: ListTicketsQuery): Promise<TicketList>;
  /** null — вернуть тикет в очередь. */
  assignTicket(ticketId: number, engineerId: number | null): Promise<TicketDetail>;

  getTicketResolutionStats(query: AnalyticsQuery): Promise<TicketResolutionStats>;
  /** Все страницы рейтинга. */
  listProblemModels(range: DateRange): Promise<ProblemModelStats[]>;
  getMaintenanceConversionStats(query: Omit<AnalyticsQuery, "category">): Promise<MaintenanceConversionStats>;
}
