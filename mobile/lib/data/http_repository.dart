// ClientRepository на реальном API (глава 18, ADR 0022): операции docs/openapi.yaml через ApiClient.
// Вложения (presign → S3), WebSocket-чат и push-токены — глава 20 (ADR 0024).
import 'dart:io';

import 'api/api_client.dart';
import 'api/contract_json.dart';
import 'attachments.dart';
import 'models.dart';
import 'repository.dart';
import 'ticket_live.dart';

class HttpClientRepository implements ClientRepository {
  HttpClientRepository(this.api);

  final ApiClient api;

  /// Списки без постраничной навигации на экране — первая страница максимального размера (контракт: page_size ≤ 100).
  static const _listPageSize = 100;

  @override
  Stream<void> get sessionEnded => api.sessionEnded;

  // ---------- Auth ----------

  @override
  Future<bool> restoreSession() => api.hasSession();

  @override
  Future<int> requestCode(String phone) async {
    final json = await api.post('/auth/phone/request-code', body: {'phone': phone}, auth: false) as Json;
    return json['ttl_seconds'] as int? ?? 120;
  }

  @override
  Future<void> verifyCode(String phone, String code, {String? pdPolicyVersion}) async {
    final json = await api.post(
      '/auth/phone/verify-code',
      body: {'phone': phone, 'code': code, if (pdPolicyVersion != null) 'pd_policy_version': pdPolicyVersion},
      auth: false,
    ) as Json;
    await api.startSession(json);
  }

  @override
  Future<Profile> me() async {
    final json = await api.get('/me') as Json;
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
      jsonItems(await api.get('/vehicle-models', query: {'page_size': _listPageSize})).map(parseVehicleModel).toList();

  @override
  Future<List<Vehicle>> vehicles() async =>
      jsonItems(await api.get('/vehicles', query: {'page_size': _listPageSize})).map(parseVehicle).toList();

  @override
  Future<Vehicle> addVehicle(String vin, {int? vehicleModelId}) async => parseVehicle(await api
      .post('/vehicles', body: {'vin': vin, if (vehicleModelId != null) 'vehicle_model_id': vehicleModelId}) as Json);

  @override
  Future<Vehicle> updateMileage(int vehicleId, int mileage) async =>
      parseVehicle(await api.patch('/vehicles/$vehicleId/mileage', body: {'mileage': mileage}) as Json);

  @override
  Future<List<AggregateStatusItem>> aggregateStatuses(int vehicleId) async =>
      jsonItems(await api.get('/vehicles/$vehicleId/aggregate-statuses', query: {'page_size': _listPageSize}))
          .map(parseAggregateStatus)
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
    return jsonPage(json, parseMaintenanceRecord);
  }

  // ---------- Knowledge base ----------

  @override
  Future<List<KnowledgeArticle>> articles(int? vehicleModelId, ArticleType type) async {
    final json = await api.get('/knowledge-articles', query: {
      'vehicle_model_id': vehicleModelId,
      'article_type': type.name,
      'page_size': _listPageSize,
    });
    final items = jsonItems(json).map(parseArticle);
    // Без фильтра сервер отдаёт статьи всех моделей — клиенту без авто нужны только общие.
    return (vehicleModelId == null ? items.where((a) => a.vehicleModelId == null) : items).toList();
  }

  @override
  Future<List<DecisionTreeNode>> decisionTree(int articleId) async =>
      // Дерево — не больше 100 узлов: page_size=100 — всё дерево (контракт).
      jsonItems(await api.get('/knowledge-articles/$articleId/decision-tree', query: {'page_size': _listPageSize}))
          .map(parseDecisionTreeNode)
          .toList();

  // ---------- Tickets ----------

  @override
  Future<List<Ticket>> tickets() async =>
      jsonItems(await api.get('/tickets', query: {'page_size': _listPageSize})).map(parseTicket).toList()
        ..sort((a, b) => b.createdAt.compareTo(a.createdAt));

  @override
  Future<Ticket> createTicket(TicketDraft draft) async => parseTicket(await api.post('/tickets', body: {
        'vehicle_id': draft.vehicleId,
        'category': categoryCode(draft.category),
        'description': draft.description,
        if (draft.sourceArticleId != null) 'source_article_id': draft.sourceArticleId,
        if (draft.sourceNodeId != null) 'source_node_id': draft.sourceNodeId,
        if (draft.attachments.isNotEmpty) 'attachments': _attachmentInputs(draft.attachments),
        if (draft.clientRequestId != null) 'client_request_id': draft.clientRequestId,
      }) as Json);

  @override
  Future<Ticket> ticket(int ticketId) async => parseTicket(await api.get('/tickets/$ticketId') as Json);

  @override
  Future<List<TicketMessage>> messages(int ticketId, {int? afterId}) async {
    // Переписка — постранично по возрастанию id: собираем все страницы (обычно одна).
    final all = <TicketMessage>[];
    for (var page = 1;; page++) {
      final json = await api.get('/tickets/$ticketId/messages', query: {
        'after_id': afterId,
        'page': page,
        'page_size': _listPageSize,
      });
      final chunk = jsonPage(json, parseTicketMessage);
      all.addAll(chunk.items);
      if (!chunk.hasMore) return all;
    }
  }

  @override
  Future<TicketMessage> sendMessage(int ticketId, String body,
          {List<UploadedAttachment> attachments = const [], String? clientRequestId}) async =>
      parseTicketMessage(await api.post('/tickets/$ticketId/messages', body: {
        'body': body,
        if (attachments.isNotEmpty) 'attachments': _attachmentInputs(attachments),
        if (clientRequestId != null) 'client_request_id': clientRequestId,
      }) as Json);

  @override
  Future<UploadedAttachment> uploadAttachment(LocalAttachment file,
      {void Function(double progress)? onProgress}) async {
    final presign = await api.post('/uploads/presign', body: {
      'file_name': file.fileName,
      'file_type': file.fileType.name,
    }) as Json;
    await api.putFile(
      Uri.parse(presign['upload_url']! as String),
      File(file.path),
      contentType: mimeType(file) ?? 'application/octet-stream',
      length: file.sizeBytes,
      onProgress: onProgress,
    );
    return UploadedAttachment(fileName: file.fileName, fileType: file.fileType, key: presign['file_url']! as String);
  }

  @override
  TicketLive watchTicket(int ticketId, {required int afterId}) => WsTicketLive(
        url: api.webSocketUrl('/tickets/$ticketId/ws'),
        connect: connectWebSocket,
        accessToken: api.accessToken,
        messagesAfter: (after) => messages(ticketId, afterId: after),
        ticket: () => ticket(ticketId),
        afterId: afterId,
      );

  static List<Json> _attachmentInputs(List<UploadedAttachment> attachments) => [
        for (final a in attachments) {'file_url': a.key, 'file_type': a.fileType.name},
      ];

  // ---------- Notifications ----------

  @override
  Future<List<NotificationItem>> notifications() async =>
      jsonItems(await api.get('/notifications', query: {'page_size': _listPageSize})).map(parseNotification).toList();

  @override
  Future<void> markNotificationRead(int notificationId) => api.patch('/notifications/$notificationId/read');

  @override
  Future<void> markNotificationOpened(int notificationId, String pushToken) =>
      api.post('/notifications/$notificationId/opened', body: {'token': pushToken});

  @override
  Future<void> registerPushToken(String token) => api.post('/push-tokens', body: {'token': token});

  @override
  Future<void> unregisterPushToken(String token) => api.delete('/push-tokens/${Uri.encodeComponent(token)}');
}
