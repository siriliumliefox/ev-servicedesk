// Push на устройстве (Глава 15 — отладочный экран, ADR 0019 п. 18; Глава 20 — приём в приложении, ADR 0024 п. 4):
// seam над firebase_messaging — в тестах фейк, на устройстве FirebasePushChannel.

/// Параметры Firebase из --dart-define (FIREBASE_*): без них push в приложении выключен.
class FirebaseConfig {
  const FirebaseConfig({
    required this.apiKey,
    required this.appId,
    required this.senderId,
    required this.projectId,
    this.iosBundleId = '',
  });

  factory FirebaseConfig.fromEnvironment() => const FirebaseConfig(
        apiKey: String.fromEnvironment('FIREBASE_API_KEY'),
        appId: String.fromEnvironment('FIREBASE_APP_ID'),
        senderId: String.fromEnvironment('FIREBASE_SENDER_ID'),
        projectId: String.fromEnvironment('FIREBASE_PROJECT_ID'),
        iosBundleId: String.fromEnvironment('FIREBASE_IOS_BUNDLE_ID'),
      );

  final String apiKey;
  final String appId;
  final String senderId;
  final String projectId;
  final String iosBundleId;

  bool get isComplete => apiKey.isNotEmpty && appId.isNotEmpty && senderId.isNotEmpty && projectId.isNotEmpty;
}

/// Push, полученный или открытый на устройстве.
class PushEvent {
  const PushEvent({
    required this.title,
    required this.body,
    required this.data,
    required this.receivedAt,
    this.sentAt,
    this.opened = false,
  });

  final String title;
  final String body;

  /// data сообщения FCM: публикации и напоминания — notification_id и type (firmware|maintenance|news|promo),
  /// события тикетов — type=ticket и ticket_id (ADR 0019 п. 13).
  final Map<String, String> data;
  final DateTime receivedAt;

  /// Когда FCM принял сообщение (RemoteMessage.sentTime).
  final DateTime? sentAt;
  final bool opened;

  int? get notificationId => int.tryParse(data['notification_id'] ?? '');

  /// Push по тикету: новое сообщение персонала или смена статуса.
  int? get ticketId => data['type'] == 'ticket' ? int.tryParse(data['ticket_id'] ?? '') : null;

  Duration? get latency => sentAt == null ? null : receivedAt.difference(sentAt!);
}

abstract class PushChannel {
  /// Запрос разрешения на уведомления (iOS, Android 13+) — статус словом.
  Future<String> permission();

  /// FCM-токен устройства; null — получить нельзя (iOS без APNs).
  Future<String?> token();
  Stream<String> get tokenRefresh;

  /// Push при открытом приложении.
  Stream<PushEvent> get received;

  /// Нажатие на push, когда приложение было свёрнуто.
  Stream<PushEvent> get opened;

  /// Нажатие на push, которое запустило закрытое приложение.
  Future<PushEvent?> initialOpened();
}
