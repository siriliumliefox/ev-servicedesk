// Модели веб-клиентов — алиасы схем OpenAPI v1 (`schema.ts`, `npm run gen:api`), без собственных полей.
// Прототип (Глава 8, ADR 0012) и HTTP-клиент (главы 21–22) работают с одними и теми же типами.
import type { components } from "../api/schema.ts";

type S = components["schemas"];

export type UserPublic = S["UserPublic"];
export type UserRole = UserPublic["role"];
export type UserList = S["UserList"];
export type StaffUserCreateRequest = S["StaffUserCreateRequest"];
export type UserUpdateRequest = S["UserUpdateRequest"];
export type VehicleModel = S["VehicleModel"];
export type Vehicle = S["Vehicle"];
export type MaintenanceRecord = S["MaintenanceRecord"];
export type MaintenanceRecordList = S["MaintenanceRecordList"];
export type AggregateType = S["AggregateType"];
export type AggregateTypeCreateRequest = S["AggregateTypeCreateRequest"];
export type MaintenanceRegulation = S["MaintenanceRegulation"];
export type MaintenanceRegulationCreateRequest = S["MaintenanceRegulationCreateRequest"];
export type AggregateStatus = S["AggregateStatus"];
export type AggregateStatusThresholds = S["AggregateStatusThresholds"];
export type AggregateStatusThresholdsUpdateRequest = S["AggregateStatusThresholdsUpdateRequest"];
export type Ticket = S["Ticket"];
export type TicketDetail = S["TicketDetail"];
export type TicketList = S["TicketList"];
export type TicketMessage = S["TicketMessage"];
export type TicketMessageList = S["TicketMessageList"];
export type TicketCategory = Ticket["category"];
export type TicketStatus = Ticket["status"];
export type KnowledgeArticle = S["KnowledgeArticle"];
export type KnowledgeArticleList = S["KnowledgeArticleList"];
export type KnowledgeArticleCreateRequest = S["KnowledgeArticleCreateRequest"];
export type KnowledgeArticleUpdateRequest = S["KnowledgeArticleUpdateRequest"];
export type ArticleType = KnowledgeArticle["article_type"];
export type KnowledgeArticleRevisionSummary = S["KnowledgeArticleRevisionSummary"];
export type KnowledgeArticleRevision = S["KnowledgeArticleRevision"];
export type DecisionTreeNode = S["DecisionTreeNode"];
export type DecisionTreeNodeCreateRequest = S["DecisionTreeNodeCreateRequest"];
export type DecisionTreeValidationResult = S["DecisionTreeValidationResult"];
export type NotificationCreateRequest = S["NotificationCreateRequest"];
export type Notification = S["Notification"];
export type NotificationType = Notification["type"];
export type PublishedNotification = S["PublishedNotification"];
export type PublishedNotificationList = S["PublishedNotificationList"];
export type NotificationAudiencePreview = S["NotificationAudiencePreview"];
export type FirmwareRelease = S["FirmwareRelease"];
export type FirmwareReleaseCreateRequest = S["FirmwareReleaseCreateRequest"];
export type TicketResolutionStats = S["TicketResolutionStats"];
export type ProblemModelStats = S["ProblemModelStats"];
export type MaintenanceConversionStats = S["MaintenanceConversionStats"];

export const TICKET_STATUSES: readonly TicketStatus[] = ["new", "in_progress", "waiting_vendor", "resolved"];
export const TICKET_CATEGORIES: readonly TicketCategory[] = ["navigation", "audio", "sim", "app_crash", "maintenance"];
export const NOTIFICATION_TYPES: readonly NotificationType[] = ["news", "promo", "maintenance", "firmware"];
/** Что публикует администратор: напоминания о ТО создаёт только система (`NOTIFICATION_TYPE_RESERVED`, ADR 0019). */
export type PublicationType = Exclude<NotificationType, "maintenance">;
export const PUBLICATION_TYPES: readonly PublicationType[] = ["news", "promo", "firmware"];
export const USER_ROLES: readonly UserRole[] = ["client", "engineer", "admin"];

/** Период аналитики — `date_from`/`date_to` включительно (DateFromParam/DateToParam). */
export interface DateRange {
  date_from: string;
  date_to: string;
}
