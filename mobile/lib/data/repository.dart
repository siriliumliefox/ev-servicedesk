// Доступ клиента к API (операции docs/openapi.yaml): HttpClientRepository — реальный backend (глава 18, ADR 0022),
// PrototypeRepository — фикстуры прототипа (глава 7, ADR 0011), если сборка без API_BASE_URL.
// Вложения, чат в реальном времени, push-токены — глава 20 (ADR 0024).
import 'models.dart';
import 'ticket_live.dart';

/// Нет сети / сервер недоступен — экран показывает состояние ошибки с «Повторить».
class OfflineException implements Exception {
  const OfflineException();

  @override
  String toString() => 'Нет подключения к интернету';
}

/// Ошибка API (Error.error.code из контракта) с текстом для пользователя.
class ApiException implements Exception {
  const ApiException(this.code, this.message, {this.retryAfter});

  final String code;
  final String message;

  /// 429: через сколько можно повторить (заголовок Retry-After).
  final Duration? retryAfter;

  @override
  String toString() => message;
}

/// Страница коллекции (PaginationMeta).
class Page<T> {
  const Page({required this.items, required this.page, required this.totalPages});

  final List<T> items;
  final int page;
  final int totalPages;

  bool get hasMore => page < totalPages;
}

/// UserPublic — то, что клиент видит о себе в профиле.
class Profile {
  const Profile({required this.phone});

  final String? phone;
}

abstract class ClientRepository {
  /// Сервер завершил сессию (refresh отклонён) — приложение возвращается к онбордингу.
  Stream<void> get sessionEnded;

  /// Есть сохранённая сессия (refresh-токен) — вход без SMS-кода.
  Future<bool> restoreSession();

  /// POST /auth/phone/request-code → ttl_seconds.
  Future<int> requestCode(String phone);

  /// POST /auth/phone/verify-code; pdPolicyVersion — согласие на обработку ПД (99-З).
  Future<void> verifyCode(String phone, String code, {String? pdPolicyVersion});

  /// GET /me.
  Future<Profile> me();

  /// POST /auth/logout — выход с устройства; токен на устройстве стирается и без сети.
  Future<void> signOut();

  /// DELETE /auth/pd-consent — отзыв согласия на обработку ПД (99-З, ст. 10) завершает все сессии.
  Future<void> withdrawPdConsent();

  /// GET /vehicle-models.
  Future<List<VehicleModel>> vehicleModels();

  /// GET /vehicles.
  Future<List<Vehicle>> vehicles();

  /// POST /vehicles; без vehicleModelId модель определяет VIN-декодер (422 VIN_DECODE_FAILED).
  Future<Vehicle> addVehicle(String vin, {int? vehicleModelId});

  /// PATCH /vehicles/{id}/mileage — только вверх (409 MILEAGE_DECREASE).
  Future<Vehicle> updateMileage(int vehicleId, int mileage);

  /// GET /vehicles/{id}/aggregate-statuses.
  Future<List<AggregateStatusItem>> aggregateStatuses(int vehicleId);

  /// GET /vehicles/{id}/maintenance-records — страница истории работ (новые сверху);
  /// aggregateTypeCode — история агрегата: его замены и работы по нему.
  Future<Page<MaintenanceRecord>> maintenanceRecordsPage(
    int vehicleId, {
    int page = 1,
    int pageSize = 20,
    String? aggregateTypeCode,
  });

  /// GET /knowledge-articles?article_type= — статьи модели и общие; без модели (нет авто) — только общие.
  Future<List<KnowledgeArticle>> articles(int? vehicleModelId, ArticleType type);

  /// GET /knowledge-articles/{id}/decision-tree.
  Future<List<DecisionTreeNode>> decisionTree(int articleId);

  /// GET /tickets.
  Future<List<Ticket>> tickets();

  /// POST /tickets.
  Future<Ticket> createTicket(TicketDraft draft);

  /// GET /tickets/{id} — открытие чата из push (в push только номер тикета).
  Future<Ticket> ticket(int ticketId);

  /// GET /tickets/{id}/messages — вся переписка; afterId — только сообщения новее (догрузка чата).
  Future<List<TicketMessage>> messages(int ticketId, {int? afterId});

  /// POST /tickets/{id}/messages; вложения — загруженные uploadAttachment.
  Future<TicketMessage> sendMessage(int ticketId, String body, {List<UploadedAttachment> attachments});

  /// POST /uploads/presign и PUT файла в S3: вложение готово к привязке к тикету или сообщению.
  Future<UploadedAttachment> uploadAttachment(LocalAttachment file, {void Function(double progress)? onProgress});

  /// Чат в реальном времени (WebSocket); afterId — последнее сообщение, уже загруженное экраном.
  TicketLive watchTicket(int ticketId, {required int afterId});

  /// GET /notifications — лента центра уведомлений.
  Future<List<NotificationItem>> notifications();

  /// PATCH /notifications/{id}/read.
  Future<void> markNotificationRead(int notificationId);

  /// POST /notifications/{id}/opened — клиент открыл push (журнал открываемости, заодно прочитано).
  Future<void> markNotificationOpened(int notificationId, String pushToken);

  /// POST /push-tokens — после входа и при обновлении токена.
  Future<void> registerPushToken(String token);

  /// DELETE /push-tokens/{token} — до выхода, пока сессия действует.
  Future<void> unregisterPushToken(String token);
}
