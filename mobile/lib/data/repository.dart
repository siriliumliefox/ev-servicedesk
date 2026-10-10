// Доступ клиента к API (операции docs/openapi.yaml). Реализация на HTTP — глава 18;
// в прототипе (глава 7) — PrototypeRepository на фикстурах.
import 'models.dart';

/// Нет сети / сервер недоступен — экран показывает состояние ошибки с «Повторить».
class OfflineException implements Exception {
  const OfflineException();

  @override
  String toString() => 'Нет подключения к интернету';
}

/// Ошибка API (Error.error.code из контракта) с текстом для пользователя.
class ApiException implements Exception {
  const ApiException(this.code, this.message);

  final String code;
  final String message;

  @override
  String toString() => message;
}

abstract class ClientRepository {
  /// POST /auth/phone/request-code → ttl_seconds.
  Future<int> requestCode(String phone);

  /// POST /auth/phone/verify-code; pdPolicyVersion — согласие на обработку ПД (99-З).
  Future<void> verifyCode(String phone, String code, {String? pdPolicyVersion});

  /// GET /vehicle-models.
  Future<List<VehicleModel>> vehicleModels();

  /// GET /vehicles.
  Future<List<Vehicle>> vehicles();

  /// POST /vehicles; без vehicleModelId модель определяет VIN-декодер (422 VIN_DECODE_FAILED).
  Future<Vehicle> addVehicle(String vin, {int? vehicleModelId});

  /// GET /vehicles/{id}/aggregate-statuses.
  Future<List<AggregateStatusItem>> aggregateStatuses(int vehicleId);

  /// GET /vehicles/{id}/maintenance-records.
  Future<List<MaintenanceRecord>> maintenanceRecords(int vehicleId);

  /// GET /knowledge-articles?vehicle_model_id=&article_type=.
  Future<List<KnowledgeArticle>> articles(int vehicleModelId, ArticleType type);

  /// GET /knowledge-articles/{id}/decision-tree.
  Future<List<DecisionTreeNode>> decisionTree(int articleId);

  /// GET /tickets.
  Future<List<Ticket>> tickets();

  /// POST /tickets.
  Future<Ticket> createTicket(TicketDraft draft);

  /// GET /tickets/{id}/messages.
  Future<List<TicketMessage>> messages(int ticketId);

  /// POST /tickets/{id}/messages.
  Future<TicketMessage> sendMessage(int ticketId, String body, {List<TicketAttachment> attachments});

  /// GET /notifications.
  Future<List<NotificationItem>> notifications();

  /// POST /notifications/{id}/read.
  Future<void> markNotificationRead(int notificationId);
}
