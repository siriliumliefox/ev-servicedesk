// Админ-панель на реальном API (глава 22, ADR 0026 п. 2): операции `AdminRepository` через `ApiSession`.
// Справочники (регламенты, прошивки, узлы дерева, версии статьи, рейтинг моделей) выгружаются всеми
// страницами; ленты (пользователи, публикации, тикеты) — постранично, страницу выбирает экран.
import type {
  AggregateStatusThresholds,
  AggregateStatusThresholdsUpdateRequest,
  AggregateType,
  AggregateTypeCreateRequest,
  DateRange,
  DecisionTreeNode,
  DecisionTreeNodeCreateRequest,
  DecisionTreeValidationResult,
  FirmwareRelease,
  FirmwareReleaseCreateRequest,
  KnowledgeArticle,
  KnowledgeArticleCreateRequest,
  KnowledgeArticleRevision,
  KnowledgeArticleRevisionSummary,
  KnowledgeArticleUpdateRequest,
  MaintenanceConversionStats,
  MaintenanceRegulation,
  MaintenanceRegulationCreateRequest,
  Notification,
  NotificationAudiencePreview,
  NotificationCreateRequest,
  ProblemModelStats,
  PublishedNotificationList,
  StaffUserCreateRequest,
  TicketDetail,
  TicketResolutionStats,
  UserList,
  UserPublic,
  UserUpdateRequest,
} from "../models.ts";
import type {
  AdminRepository,
  AnalyticsQuery,
  ListPublishedQuery,
  ListUsersQuery,
} from "../repository.ts";
import { fetchAllPages } from "../paging.ts";
import { HttpCommonRepository, PAGE_SIZE } from "./HttpCommonRepository.ts";

export class HttpAdminRepository extends HttpCommonRepository implements AdminRepository {
  // ---------- Справочник агрегатов, регламенты ТО, пороги ----------

  createAggregateType(body: AggregateTypeCreateRequest): Promise<AggregateType> {
    return this.session.request((c) => c.POST("/aggregate-types", { body }));
  }

  listMaintenanceRegulations(query: { vehicle_model_id?: number; include_archived?: boolean }): Promise<MaintenanceRegulation[]> {
    return fetchAllPages((page) =>
      this.session.request((c) =>
        c.GET("/maintenance-regulations", { params: { query: { ...query, page, page_size: PAGE_SIZE } } }),
      ),
    );
  }

  reviseMaintenanceRegulation(body: MaintenanceRegulationCreateRequest): Promise<MaintenanceRegulation> {
    return this.session.request((c) => c.POST("/maintenance-regulations", { body }));
  }

  archiveMaintenanceRegulation(regulationId: number): Promise<void> {
    return this.session.request((c) =>
      c.DELETE("/maintenance-regulations/{regulationId}", { params: { path: { regulationId } } }),
    );
  }

  getAggregateStatusThresholds(): Promise<AggregateStatusThresholds> {
    return this.session.request((c) => c.GET("/aggregate-status-thresholds"));
  }

  updateAggregateStatusThresholds(body: AggregateStatusThresholdsUpdateRequest): Promise<AggregateStatusThresholds> {
    return this.session.request((c) => c.PUT("/aggregate-status-thresholds", { body }));
  }

  // ---------- База знаний ----------

  getKnowledgeArticle(articleId: number): Promise<KnowledgeArticle> {
    return this.session.request((c) => c.GET("/knowledge-articles/{articleId}", { params: { path: { articleId } } }));
  }

  createKnowledgeArticle(body: KnowledgeArticleCreateRequest): Promise<KnowledgeArticle> {
    return this.session.request((c) => c.POST("/knowledge-articles", { body }));
  }

  updateKnowledgeArticle(articleId: number, body: KnowledgeArticleUpdateRequest): Promise<KnowledgeArticle> {
    return this.session.request((c) =>
      c.PATCH("/knowledge-articles/{articleId}", { params: { path: { articleId } }, body }),
    );
  }

  unpublishKnowledgeArticle(articleId: number): Promise<void> {
    return this.session.request((c) => c.DELETE("/knowledge-articles/{articleId}", { params: { path: { articleId } } }));
  }

  async listKnowledgeArticleRevisions(articleId: number): Promise<KnowledgeArticleRevisionSummary[]> {
    const items = await fetchAllPages((page) =>
      this.session.request((c) =>
        c.GET("/knowledge-articles/{articleId}/revisions", {
          params: { path: { articleId }, query: { page, page_size: PAGE_SIZE } },
        }),
      ),
    );
    return items.sort((a, b) => b.version - a.version);
  }

  getKnowledgeArticleRevision(articleId: number, version: number): Promise<KnowledgeArticleRevision> {
    return this.session.request((c) =>
      c.GET("/knowledge-articles/{articleId}/revisions/{version}", { params: { path: { articleId, version } } }),
    );
  }

  listDecisionTreeNodes(articleId: number): Promise<DecisionTreeNode[]> {
    return fetchAllPages((page) =>
      this.session.request((c) =>
        c.GET("/knowledge-articles/{articleId}/decision-tree", {
          params: { path: { articleId }, query: { page, page_size: PAGE_SIZE } },
        }),
      ),
    );
  }

  createDecisionTreeNode(articleId: number, body: DecisionTreeNodeCreateRequest): Promise<DecisionTreeNode> {
    return this.session.request((c) =>
      c.POST("/knowledge-articles/{articleId}/decision-tree", { params: { path: { articleId } }, body }),
    );
  }

  updateDecisionTreeNode(nodeId: number, body: DecisionTreeNodeCreateRequest): Promise<DecisionTreeNode> {
    return this.session.request((c) => c.PATCH("/decision-tree-nodes/{nodeId}", { params: { path: { nodeId } }, body }));
  }

  deleteDecisionTreeNode(nodeId: number): Promise<void> {
    return this.session.request((c) => c.DELETE("/decision-tree-nodes/{nodeId}", { params: { path: { nodeId } } }));
  }

  validateDecisionTree(articleId: number): Promise<DecisionTreeValidationResult> {
    return this.session.request((c) =>
      c.GET("/knowledge-articles/{articleId}/decision-tree/validate", { params: { path: { articleId } } }),
    );
  }

  // ---------- Публикации и прошивки ----------

  createNotification(body: NotificationCreateRequest): Promise<Notification> {
    return this.session.request((c) => c.POST("/notifications", { body }));
  }

  previewNotificationAudience(body: NotificationCreateRequest): Promise<NotificationAudiencePreview> {
    return this.session.request((c) => c.POST("/notifications/audience-preview", { body }));
  }

  listPublishedNotifications(query: ListPublishedQuery = {}): Promise<PublishedNotificationList> {
    return this.session.request((c) => c.GET("/notifications/published", { params: { query } }));
  }

  listFirmwareReleases(query: { vehicle_model_id?: number } = {}): Promise<FirmwareRelease[]> {
    return fetchAllPages((page) =>
      this.session.request((c) =>
        c.GET("/firmware-releases", { params: { query: { ...query, page, page_size: PAGE_SIZE } } }),
      ),
    );
  }

  createFirmwareRelease(body: FirmwareReleaseCreateRequest): Promise<FirmwareRelease> {
    return this.session.request((c) => c.POST("/firmware-releases", { body }));
  }

  // ---------- Пользователи и тикеты инженера ----------

  listUsers(query: ListUsersQuery = {}): Promise<UserList> {
    return this.session.request((c) => c.GET("/users", { params: { query } }));
  }

  getUser(userId: number): Promise<UserPublic> {
    return this.session.request((c) => c.GET("/users/{userId}", { params: { path: { userId } } }));
  }

  createStaffUser(body: StaffUserCreateRequest): Promise<UserPublic> {
    return this.session.request((c) => c.POST("/users", { body }));
  }

  updateUser(userId: number, body: UserUpdateRequest): Promise<UserPublic> {
    return this.session.request((c) => c.PATCH("/users/{userId}", { params: { path: { userId } }, body }));
  }

  resetUserPassword(userId: number, password: string): Promise<void> {
    return this.session.request((c) =>
      c.POST("/users/{userId}/password", { params: { path: { userId } }, body: { password } }),
    );
  }

  assignTicket(ticketId: number, engineerId: number | null): Promise<TicketDetail> {
    return this.session.request((c) =>
      c.PATCH("/tickets/{ticketId}/assign", {
        params: { path: { ticketId } },
        body: { assigned_engineer_id: engineerId },
      }),
    );
  }

  // ---------- Аналитика ----------

  getTicketResolutionStats(query: AnalyticsQuery): Promise<TicketResolutionStats> {
    return this.session.request((c) => c.GET("/analytics/ticket-resolution", { params: { query } }));
  }

  listProblemModels(range: DateRange): Promise<ProblemModelStats[]> {
    return fetchAllPages((page) =>
      this.session.request((c) =>
        c.GET("/analytics/problem-models", { params: { query: { ...range, page, page_size: PAGE_SIZE } } }),
      ),
    );
  }

  getMaintenanceConversionStats(query: Omit<AnalyticsQuery, "category">): Promise<MaintenanceConversionStats> {
    return this.session.request((c) => c.GET("/analytics/maintenance-conversion", { params: { query } }));
  }
}
