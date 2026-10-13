// Ответы API (имена полей — docs/openapi.yaml) → модели клиента: общий разбор для REST и WebSocket (ADR 0024 п. 8).
import '../models.dart';
import '../repository.dart';

typedef Json = Map<String, Object?>;

List<Json> jsonItems(Object? json) => ((json! as Json)['items']! as List).cast<Json>();

Page<T> jsonPage<T>(Object? json, T Function(Json) item) {
  final map = json! as Json;
  final meta = map['meta']! as Json;
  return Page(
    items: (map['items']! as List).cast<Json>().map(item).toList(),
    page: meta['page']! as int,
    totalPages: meta['total_pages']! as int,
  );
}

DateTime _dateTime(Object? v) => DateTime.parse(v! as String).toLocal();
DateTime? _dateOrNull(Object? v) => v == null ? null : DateTime.parse(v as String);

VehicleModel parseVehicleModel(Json j) => VehicleModel(
      id: j['id']! as int,
      brand: j['brand']! as String,
      model: j['model']! as String,
      trim: j['trim'] as String?,
    );

Vehicle parseVehicle(Json j) {
  final info = j['vehicle_model']! as Json;
  return Vehicle(
    id: j['id']! as int,
    vin: j['vin']! as String,
    mileage: j['mileage']! as int,
    vehicleModel: VehicleModel(
      id: j['vehicle_model_id']! as int,
      brand: info['brand']! as String,
      model: info['model']! as String,
      trim: info['trim'] as String?,
    ),
    currentFirmwareVersion: j['current_firmware_version'] as String?,
  );
}

AggregateStatusItem parseAggregateStatus(Json j) => AggregateStatusItem(
      aggregateTypeCode: j['aggregate_type_code']! as String,
      aggregateTypeName: j['aggregate_type_name']! as String,
      status: AggregateStatus.values.byName(j['status']! as String),
      percentage: (j['percentage'] as num?)?.toDouble(),
      lastReplacedAt: _dateOrNull(j['last_replaced_at']),
      lastReplacedMileage: j['last_replaced_mileage'] as int?,
      remainingKm: j['remaining_km'] as int?,
      remainingDays: j['remaining_days'] as int?,
    );

MaintenanceRecord parseMaintenanceRecord(Json j) => MaintenanceRecord(
      id: j['id']! as int,
      aggregateTypeCode: j['aggregate_type_code'] as String?,
      performedAt: DateTime.parse(j['performed_at']! as String),
      mileageAtService: j['mileage_at_service']! as int,
      kind: MaintenanceKind.values.byName(j['kind']! as String),
      description: j['description'] as String?,
    );

const _categoryCodes = {
  TicketCategory.navigation: 'navigation',
  TicketCategory.audio: 'audio',
  TicketCategory.sim: 'sim',
  TicketCategory.appCrash: 'app_crash',
  TicketCategory.maintenance: 'maintenance',
};

String categoryCode(TicketCategory c) => _categoryCodes[c]!;

TicketCategory _category(Object? code) => _categoryCodes.entries.firstWhere((e) => e.value == code).key;

const _statusCodes = {
  'new': TicketStatus.newTicket,
  'in_progress': TicketStatus.inProgress,
  'waiting_vendor': TicketStatus.waitingVendor,
  'resolved': TicketStatus.resolved,
};

/// Вложение в ответе: file_url — ссылка на скачивание на 15 минут; имя файла — последний сегмент пути без подписи.
List<TicketAttachment> _attachments(Object? list) => [
      for (final a in (list as List? ?? const []).cast<Json>())
        TicketAttachment(
          fileName: Uri.parse(a['file_url']! as String).pathSegments.lastOrNull ?? '',
          fileType: AttachmentType.values.byName(a['file_type']! as String),
          url: a['file_url']! as String,
        ),
    ];

Ticket parseTicket(Json j) => Ticket(
      id: j['id']! as int,
      vehicleId: j['vehicle_id']! as int,
      category: _category(j['category']),
      status: _statusCodes[j['status']]!,
      summary: j['summary']! as String,
      createdAt: _dateTime(j['created_at']),
      attachments: _attachments(j['attachments']),
    );

/// Имя и контакты сотрудника клиенту не отдаются (ADR 0017 п. 12).
TicketMessage parseTicketMessage(Json j) {
  final fromClient = (j['author']! as Json)['role'] == 'client';
  return TicketMessage(
    id: j['id']! as int,
    fromClient: fromClient,
    authorName: fromClient ? 'Вы' : 'Инженер поддержки',
    body: j['body']! as String,
    createdAt: _dateTime(j['created_at']),
    attachments: _attachments(j['attachments']),
  );
}

KnowledgeArticle parseArticle(Json j) => KnowledgeArticle(
      id: j['id']! as int,
      vehicleModelId: j['vehicle_model_id'] as int?,
      articleType: ArticleType.values.byName(j['article_type']! as String),
      title: j['title']! as String,
      content: j['content'] as String? ?? '',
      category: j['category'] == null ? null : _category(j['category']),
    );

DecisionTreeNode parseDecisionTreeNode(Json j) => DecisionTreeNode(
      id: j['id']! as int,
      articleId: j['article_id']! as int,
      questionText: j['question_text']! as String,
      options: [
        for (final o in (j['options'] as List? ?? const []).cast<Json>())
          DecisionTreeOption(label: o['label']! as String, nextNodeId: o['next_node_id'] as int?),
      ],
      isRoot: j['is_root']! as bool,
      isEscalation: j['is_escalation']! as bool,
    );

NotificationItem parseNotification(Json j) => NotificationItem(
      id: j['id']! as int,
      type: NotificationType.values.byName(j['type']! as String),
      message: j['message']! as String,
      createdAt: _dateTime(j['created_at']),
      readAt: j['read_at'] == null ? null : _dateTime(j['read_at']),
      vehicleId: j['vehicle_id'] as int?,
    );
