// ClientRepository на реальном API (глава 18, ADR 0022): операции docs/openapi.yaml через ApiClient.
// Вложения тикета (presign → S3) и WebSocket-чат — глава 20; здесь вложения не отправляются.
import 'api/api_client.dart';
import 'models.dart';
import 'repository.dart';

typedef _Json = Map<String, Object?>;

class HttpClientRepository implements ClientRepository {
  HttpClientRepository(this.api);

  final ApiClient api;

  /// Списки без постраничной навигации на экране — первая страница максимального размера (контракт: page_size ≤ 100).
  static const _listPageSize = 100;

  @override
  bool get supportsAttachments => false;

  @override
  Stream<void> get sessionEnded => api.sessionEnded;

  // ---------- Auth ----------

  @override
  Future<bool> restoreSession() => api.hasSession();

  @override
  Future<int> requestCode(String phone) async {
    final json = await api.post('/auth/phone/request-code', body: {'phone': phone}, auth: false) as _Json;
    return json['ttl_seconds'] as int? ?? 120;
  }

  @override
  Future<void> verifyCode(String phone, String code, {String? pdPolicyVersion}) async {
    final json = await api.post(
      '/auth/phone/verify-code',
      body: {'phone': phone, 'code': code, if (pdPolicyVersion != null) 'pd_policy_version': pdPolicyVersion},
      auth: false,
    ) as _Json;
    await api.startSession(json);
  }

  @override
  Future<Profile> me() async {
    final json = await api.get('/me') as _Json;
    return Profile(phone: json['phone'] as String?);
  }

  @override
  Future<void> signOut() async {
    final refresh = await api.tokens.read();
    try {
      if (refresh != null) await api.post('/auth/logout', body: {'refresh_token': refresh});
    } on Exception {
      // Выход с устройства — best effort: без сети или с истёкшей сессией токен всё равно стирается.
    } finally {
      await api.endSession();
    }
  }

  @override
  Future<void> withdrawPdConsent() async {
    await api.delete('/auth/pd-consent');
    await api.endSession();
  }

  // ---------- Vehicles ----------

  @override
  Future<List<VehicleModel>> vehicleModels() async =>
      _items(await api.get('/vehicle-models', query: {'page_size': _listPageSize})).map(_vehicleModel).toList();

  @override
  Future<List<Vehicle>> vehicles() async =>
      _items(await api.get('/vehicles', query: {'page_size': _listPageSize})).map(_vehicle).toList();

  @override
  Future<Vehicle> addVehicle(String vin, {int? vehicleModelId}) async => _vehicle(await api
      .post('/vehicles', body: {'vin': vin, if (vehicleModelId != null) 'vehicle_model_id': vehicleModelId}) as _Json);

  @override
  Future<Vehicle> updateMileage(int vehicleId, int mileage) async =>
      _vehicle(await api.patch('/vehicles/$vehicleId/mileage', body: {'mileage': mileage}) as _Json);

  @override
  Future<List<AggregateStatusItem>> aggregateStatuses(int vehicleId) async =>
      _items(await api.get('/vehicles/$vehicleId/aggregate-statuses', query: {'page_size': _listPageSize}))
          .map(_aggregateStatus)
          .toList();

  @override
  Future<Page<MaintenanceRecord>> maintenanceRecordsPage(
    int vehicleId, {
    int page = 1,
    int pageSize = 20,
    String? aggregateTypeCode,
  }) async {
    final json = await api.get('/vehicles/$vehicleId/maintenance-records', query: {
      'page': page,
      'page_size': pageSize,
      if (aggregateTypeCode != null) 'aggregate_type_code': aggregateTypeCode,
    });
    return _page(json, _maintenanceRecord);
  }

  // ---------- Knowledge base ----------

  @override
  Future<List<KnowledgeArticle>> articles(int vehicleModelId, ArticleType type) async {
    final json = await api.get('/knowledge-articles', query: {
      'vehicle_model_id': vehicleModelId,
      'article_type': type.name,
      'page_size': _listPageSize,
    });
    return _items(json).map(_article).toList();
  }

  @override
  Future<List<DecisionTreeNode>> decisionTree(int articleId) async =>
      // Дерево — не больше 100 узлов: page_size=100 — всё дерево (контракт).
      _items(await api.get('/knowledge-articles/$articleId/decision-tree', query: {'page_size': _listPageSize}))
          .map(_node)
          .toList();

  // ---------- Tickets ----------

  @override
  Future<List<Ticket>> tickets() async =>
      _items(await api.get('/tickets', query: {'page_size': _listPageSize})).map(_ticket).toList()
        ..sort((a, b) => b.createdAt.compareTo(a.createdAt));

  @override
  Future<Ticket> createTicket(TicketDraft draft) async => _ticket(await api.post('/tickets', body: {
        'vehicle_id': draft.vehicleId,
        'category': _categoryCode(draft.category),
        'description': draft.description,
        if (draft.sourceArticleId != null) 'source_article_id': draft.sourceArticleId,
        if (draft.sourceNodeId != null) 'source_node_id': draft.sourceNodeId,
      }) as _Json);

  @override
  Future<List<TicketMessage>> messages(int ticketId) async =>
      _items(await api.get('/tickets/$ticketId/messages', query: {'page_size': _listPageSize})).map(_message).toList();

  @override
  Future<TicketMessage> sendMessage(int ticketId, String body, {List<TicketAttachment> attachments = const []}) async =>
      _message(await api.post('/tickets/$ticketId/messages', body: {'body': body}) as _Json);

  // ---------- Notifications ----------

  @override
  Future<List<NotificationItem>> notifications() async =>
      _items(await api.get('/notifications', query: {'page_size': _listPageSize})).map(_notification).toList();

  @override
  Future<void> markNotificationRead(int notificationId) => api.patch('/notifications/$notificationId/read');
}

// ---------- JSON → модели (имена полей — docs/openapi.yaml) ----------

List<_Json> _items(Object? json) => ((json! as _Json)['items']! as List).cast<_Json>();

Page<T> _page<T>(Object? json, T Function(_Json) item) {
  final map = json! as _Json;
  final meta = map['meta']! as _Json;
  return Page(
    items: (map['items']! as List).cast<_Json>().map(item).toList(),
    page: meta['page']! as int,
    totalPages: meta['total_pages']! as int,
  );
}

DateTime _dateTime(Object? v) => DateTime.parse(v! as String).toLocal();
DateTime? _dateOrNull(Object? v) => v == null ? null : DateTime.parse(v as String);

VehicleModel _vehicleModel(_Json j) => VehicleModel(
      id: j['id']! as int,
      brand: j['brand']! as String,
      model: j['model']! as String,
      trim: j['trim'] as String?,
    );

Vehicle _vehicle(_Json j) {
  final info = j['vehicle_model']! as _Json;
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

AggregateStatusItem _aggregateStatus(_Json j) => AggregateStatusItem(
      aggregateTypeCode: j['aggregate_type_code']! as String,
      aggregateTypeName: j['aggregate_type_name']! as String,
      status: AggregateStatus.values.byName(j['status']! as String),
      percentage: (j['percentage'] as num?)?.toDouble(),
      lastReplacedAt: _dateOrNull(j['last_replaced_at']),
      lastReplacedMileage: j['last_replaced_mileage'] as int?,
      remainingKm: j['remaining_km'] as int?,
      remainingDays: j['remaining_days'] as int?,
    );

MaintenanceRecord _maintenanceRecord(_Json j) => MaintenanceRecord(
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

String _categoryCode(TicketCategory c) => _categoryCodes[c]!;

TicketCategory _category(Object? code) => _categoryCodes.entries.firstWhere((e) => e.value == code).key;

const _statusCodes = {
  'new': TicketStatus.newTicket,
  'in_progress': TicketStatus.inProgress,
  'waiting_vendor': TicketStatus.waitingVendor,
  'resolved': TicketStatus.resolved,
};

List<TicketAttachment> _attachments(Object? list) => [
      for (final a in (list as List? ?? const []).cast<_Json>())
        TicketAttachment(
          fileName: (a['file_url']! as String).split('/').last,
          fileType: AttachmentType.values.byName(a['file_type']! as String),
        ),
    ];

Ticket _ticket(_Json j) => Ticket(
      id: j['id']! as int,
      vehicleId: j['vehicle_id']! as int,
      category: _category(j['category']),
      status: _statusCodes[j['status']]!,
      summary: j['summary']! as String,
      createdAt: _dateTime(j['created_at']),
      attachments: _attachments(j['attachments']),
    );

/// Имя и контакты сотрудника клиенту не отдаются (ADR 0017 п. 12).
TicketMessage _message(_Json j) {
  final fromClient = (j['author']! as _Json)['role'] == 'client';
  return TicketMessage(
    id: j['id']! as int,
    fromClient: fromClient,
    authorName: fromClient ? 'Вы' : 'Инженер поддержки',
    body: j['body']! as String,
    createdAt: _dateTime(j['created_at']),
    attachments: _attachments(j['attachments']),
  );
}

KnowledgeArticle _article(_Json j) => KnowledgeArticle(
      id: j['id']! as int,
      vehicleModelId: j['vehicle_model_id'] as int?,
      articleType: ArticleType.values.byName(j['article_type']! as String),
      title: j['title']! as String,
      content: j['content'] as String? ?? '',
      category: j['category'] == null ? null : _category(j['category']),
    );

DecisionTreeNode _node(_Json j) => DecisionTreeNode(
      id: j['id']! as int,
      articleId: j['article_id']! as int,
      questionText: j['question_text']! as String,
      options: [
        for (final o in (j['options'] as List? ?? const []).cast<_Json>())
          DecisionTreeOption(label: o['label']! as String, nextNodeId: o['next_node_id'] as int?),
      ],
      isRoot: j['is_root']! as bool,
      isEscalation: j['is_escalation']! as bool,
    );

NotificationItem _notification(_Json j) => NotificationItem(
      id: j['id']! as int,
      type: NotificationType.values.byName(j['type']! as String),
      message: j['message']! as String,
      createdAt: _dateTime(j['created_at']),
      readAt: j['read_at'] == null ? null : _dateTime(j['read_at']),
    );
