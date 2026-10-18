// PushChannel на firebase_messaging (Глава 15, ADR 0019 п. 18; Глава 20, ADR 0024 п. 4–5). Только для устройства:
// в flutter test не используется (там — фейк).
import 'package:firebase_core/firebase_core.dart';
import 'package:firebase_messaging/firebase_messaging.dart';
import 'package:flutter/foundation.dart';

import 'push_channel.dart';

class FirebasePushChannel implements PushChannel {
  FirebasePushChannel._(this._messaging);

  final FirebaseMessaging _messaging;

  /// systemBannerInForeground — системный баннер и при открытом приложении (отладочный экран: видно, что push
  /// дошёл); в приложении push на открытом экране показывает баннер внутри приложения (ADR 0024 п. 4).
  static Future<FirebasePushChannel> init(FirebaseConfig config, {bool systemBannerInForeground = false}) async {
    await Firebase.initializeApp(
      options: FirebaseOptions(
        apiKey: config.apiKey,
        appId: config.appId,
        messagingSenderId: config.senderId,
        projectId: config.projectId,
        iosBundleId: config.iosBundleId.isEmpty ? null : config.iosBundleId,
      ),
    );
    final messaging = FirebaseMessaging.instance;
    await messaging.setForegroundNotificationPresentationOptions(
      alert: systemBannerInForeground,
      badge: systemBannerInForeground,
      sound: systemBannerInForeground,
    );
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
    // FCM-токен на iOS появляется после APNs-токена; без платного Apple Developer — null (глава 27).
    if (defaultTargetPlatform == TargetPlatform.iOS && await _messaging.getAPNSToken() == null) {
      await Future<void>.delayed(const Duration(seconds: 2));
      if (await _messaging.getAPNSToken() == null) return null;
    }
    // firebase_messaging 17: getToken/onTokenRefresh устарели в пользу register()/onRegistered, но те выдают
    // FID для direct-send, а backend шлёт FCM HTTP v1 по registration token (message.token, ADR 0019).
    // Переход на FID — отдельное решение вместе с backend; до него — токен, как раньше.
    // ignore: deprecated_member_use
    return _messaging.getToken();
  }

  @override
  // ignore: deprecated_member_use
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
