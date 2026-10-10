// Модели клиентского приложения — подмножество схем docs/openapi.yaml (API v1, ADR 0007).
// Имена полей совпадают с контрактом; JSON-сериализация — глава 18 (реальный API).
import '../ui/status_badge.dart';

export '../ui/status_badge.dart' show AggregateStatus;

/// VehicleModel / VehicleModelInfo.
class VehicleModel {
  const VehicleModel({required this.id, required this.brand, required this.model, this.trim});

  final int id;
  final String brand;
  final String model;
  final String? trim;

  String get title => '$brand $model';
}

/// Vehicle.
class Vehicle {
  const Vehicle({
    required this.id,
    required this.vin,
    required this.mileage,
    required this.vehicleModel,
    this.currentFirmwareVersion,
  });

  final int id;
  final String vin;
  final int mileage;
  final VehicleModel vehicleModel;
  final String? currentFirmwareVersion;

  /// VIN — ПД (N-07): на экране показываются только последние 4 символа.
  String get vinMasked => '•••• ${vin.substring(vin.length - 4)}';
}

/// AggregateStatus (элемент /vehicles/{id}/aggregate-statuses). Расчёт — глава 5.
class AggregateStatusItem {
  const AggregateStatusItem({
    required this.aggregateTypeCode,
    required this.aggregateTypeName,
    required this.status,
    this.percentage,
    this.lastReplacedAt,
    this.lastReplacedMileage,
    this.remainingKm,
    this.remainingDays,
  });

  final String aggregateTypeCode;
  final String aggregateTypeName;
  final AggregateStatus status;
  final double? percentage;
  final DateTime? lastReplacedAt;
  final int? lastReplacedMileage;
  final int? remainingKm;
  final int? remainingDays;
}

/// MaintenanceRecord.
class MaintenanceRecord {
  const MaintenanceRecord({
    required this.id,
    required this.aggregateTypeCode,
    required this.performedAt,
    required this.mileageAtService,
    this.description,
  });

  final int id;
  final String? aggregateTypeCode;
  final DateTime performedAt;
  final int mileageAtService;
  final String? description;
}

/// Ticket.category.
enum TicketCategory {
  navigation('Навигация'),
  audio('Звук'),
  sim('SIM-связь'),
  appCrash('Сбой приложения'),
  maintenance('Агрегаты / ТО');

  const TicketCategory(this.label);

  final String label;
}

/// Ticket.status — подписи из глоссария.
enum TicketStatus {
  newTicket('Новый'),
  inProgress('В работе'),
  waitingVendor('Ожидает вендора'),
  resolved('Решено');

  const TicketStatus(this.label);

  final String label;
}

/// TicketAttachmentInput.file_type.
enum AttachmentType { photo, video }

class TicketAttachment {
  const TicketAttachment({required this.fileName, required this.fileType});

  final String fileName;
  final AttachmentType fileType;
}

/// Ticket / TicketDetail (поля, нужные клиенту).
class Ticket {
  const Ticket({
    required this.id,
    required this.vehicleId,
    required this.category,
    required this.status,
    required this.description,
    required this.createdAt,
    this.attachments = const [],
  });

  final int id;
  final int vehicleId;
  final TicketCategory category;
  final TicketStatus status;
  final String description;
  final DateTime createdAt;
  final List<TicketAttachment> attachments;
}

/// TicketCreateRequest.
class TicketDraft {
  const TicketDraft({
    required this.vehicleId,
    required this.category,
    required this.description,
    this.sourceArticleId,
    this.sourceNodeId,
    this.attachments = const [],
  });

  final int vehicleId;
  final TicketCategory category;
  final String description;
  final int? sourceArticleId;
  final int? sourceNodeId;
  final List<TicketAttachment> attachments;
}

/// TicketMessage.
class TicketMessage {
  const TicketMessage({
    required this.id,
    required this.fromClient,
    required this.authorName,
    required this.body,
    required this.createdAt,
    this.attachments = const [],
  });

  final int id;
  final bool fromClient;
  final String authorName;
  final String body;
  final DateTime createdAt;
  final List<TicketAttachment> attachments;
}

/// KnowledgeArticle.article_type.
enum ArticleType { guide, troubleshooting }

/// KnowledgeArticle.
class KnowledgeArticle {
  const KnowledgeArticle({
    required this.id,
    required this.vehicleModelId,
    required this.articleType,
    required this.title,
    required this.content,
    this.category,
  });

  final int id;
  final int? vehicleModelId;
  final ArticleType articleType;
  final String title;
  final String content;

  /// Категория тикета при эскалации из дерева решений (подстановка в форму, минимизация ввода).
  final TicketCategory? category;
}

/// DecisionTreeOption.
class DecisionTreeOption {
  const DecisionTreeOption({required this.label, this.nextNodeId});

  final String label;
  final int? nextNodeId;
}

/// DecisionTreeNode.
class DecisionTreeNode {
  const DecisionTreeNode({
    required this.id,
    required this.articleId,
    required this.questionText,
    this.options = const [],
    this.isRoot = false,
    this.isEscalation = false,
  });

  final int id;
  final int articleId;
  final String questionText;
  final List<DecisionTreeOption> options;
  final bool isRoot;
  final bool isEscalation;

  /// Лист без эскалации — проблема решена.
  bool get isResolved => options.isEmpty && !isEscalation;
}

/// Notification.type.
enum NotificationType {
  firmware('Прошивка'),
  maintenance('ТО'),
  news('Новости'),
  promo('Акции');

  const NotificationType(this.label);

  final String label;
}

/// NotificationListItem.
class NotificationItem {
  const NotificationItem({
    required this.id,
    required this.type,
    required this.message,
    required this.createdAt,
    this.readAt,
  });

  final int id;
  final NotificationType type;
  final String message;
  final DateTime createdAt;
  final DateTime? readAt;

  bool get isRead => readAt != null;

  /// В контракте только message: заголовок — первая строка, текст — остальное.
  String get title => message.split('\n').first;
  String get body => message.split('\n').skip(1).join('\n').trim();

  NotificationItem markRead(DateTime at) =>
      NotificationItem(id: id, type: type, message: message, createdAt: createdAt, readAt: at);
}
