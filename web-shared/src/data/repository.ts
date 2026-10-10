// Доступ к данным веб-клиентов (Глава 8, ADR 0012). Методы — операции OpenAPI v1 (имя = operationId),
// роли — `x-required-roles`. Прототип: `PrototypeRepository` (фикстуры в памяти); главы 21–22 —
// реализация на `createApiClient` без изменения экранов.
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
  TicketDetail,
  TicketList,
  TicketMessage,
  TicketMessageList,
  TicketResolutionStats,
  TicketStatus,
  UserPublic,
  VehicleModel,
} from "./models.ts";

/** Ошибка API в едином формате `Error` контракта; `NETWORK` — запрос не дошёл до сервера. */
export class ApiError extends Error {
  readonly code: string;
  readonly status: number;
  /** Поле, не прошедшее валидацию (`error.details.field` при 422). */
  readonly field?: string;

  constructor(code: string, message: string, status: number, field?: string) {
    super(message);
    this.name = "ApiError";
    this.code = code;
    this.status = status;
    this.field = field;
  }
}

export interface ListTicketsQuery {
  status?: TicketStatus;
  category?: TicketCategory;
  assigned_engineer_id?: number;
  overdue?: boolean;
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
  listTickets(query?: ListTicketsQuery): Promise<TicketList>;
  getTicket(ticketId: number): Promise<TicketDetail>;
  claimTicket(ticketId: number): Promise<TicketDetail>;
  updateTicketStatus(ticketId: number, status: TicketStatus): Promise<TicketDetail>;
  listTicketMessages(ticketId: number): Promise<TicketMessageList>;
  createTicketMessage(ticketId: number, body: string): Promise<TicketMessage>;
  listMaintenanceRecords(vehicleId: number): Promise<MaintenanceRecordList>;
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
