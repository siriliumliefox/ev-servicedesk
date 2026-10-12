// PushChannel на firebase_messaging (Глава 15, ADR 0019 п. 18). Только для устройства:
// в flutter test не используется (там — фейк).
import 'package:firebase_core/firebase_core.dart';
import 'package:firebase_messaging/firebase_messaging.dart';

import 'push_debug.dart';

class FirebasePushChannel implements PushChannel {
  FirebasePushChannel._(this._messaging);

  final FirebaseMessaging _messaging;

  static Future<FirebasePushChannel> init(PushDebugConfig config) async {
    await Firebase.initializeApp(
      options: FirebaseOptions(
        apiKey: config.firebaseApiKey,
        appId: config.firebaseAppId,
        messagingSenderId: config.firebaseSenderId,
        projectId: config.firebaseProjectId,
        iosBundleId: config.iosBundleId.isEmpty ? null : config.iosBundleId,
      ),
    );
    final messaging = FirebaseMessaging.instance;
    // Баннер и при открытом приложении — видно, что push дошёл.
    await messaging.setForegroundNotificationPresentationOptions(alert: true, badge: true, sound: true);
    return FirebasePushChannel._(messaging);
  }

  PushEvent _event(RemoteMessage m, {bool opened = false}) => PushEvent(
        title: m.notification?.title ?? '',
        body: m.notification?.body ?? '',
        data: m.data.map((k, v) => MapEntry(k, '$v')),
        receivedAt: DateTime.now(),
        sentAt: m.sentTime,
        opened: opened,
      );

  @override
  Future<String> permission() async {
    final s = await _messaging.requestPermission();
    return s.authorizationStatus.name;
  }

  @override
  Future<String?> token() async {
    // FCM-токен на iOS появляется после APNs-токена; без платного Apple Developer — null.
    if (await _messaging.getAPNSToken() == null) {
      await Future<void>.delayed(const Duration(seconds: 2));
      if (await _messaging.getAPNSToken() == null) return null;
    }
    return _messaging.getToken();
  }

  @override
  Stream<String> get tokenRefresh => _messaging.onTokenRefresh;

  @override
  Stream<PushEvent> get received => FirebaseMessaging.onMessage.map(_event);

  @override
  Stream<PushEvent> get opened => FirebaseMessaging.onMessageOpenedApp.map((m) => _event(m, opened: true));

  @override
  Future<PushEvent?> initialOpened() async {
    final m = await _messaging.getInitialMessage();
    return m == null ? null : _event(m, opened: true);
  }
}
