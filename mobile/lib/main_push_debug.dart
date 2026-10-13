// Точка входа отладочного экрана push (Глава 15, ADR 0019 п. 18) — вне навигации приложения.
//   flutter run -t lib/main_push_debug.dart --dart-define-from-file=push_e2e.local.json
// Файл конфигурации создаёт scripts/push_e2e.py setup (docs/NOTIFICATIONS_E2E.md).
import 'package:flutter/material.dart';

import 'push/firebase_push_channel.dart';
import 'push/push_debug.dart';
import 'theme/app_theme.dart';

Future<void> main() async {
  WidgetsFlutterBinding.ensureInitialized();
  final config = PushDebugConfig.fromEnvironment();
  Widget home;
  if (config.missing.isNotEmpty) {
    home = Scaffold(
      body: Center(child: Text('Не заданы: ${config.missing.join(', ')}\nСм. docs/NOTIFICATIONS_E2E.md')),
    );
  } else {
    final channel = await FirebasePushChannel.init(config.firebase, systemBannerInForeground: true);
    home = PushDebugScreen(channel: channel, api: PushDebugApi(config));
  }
  runApp(MaterialApp(title: 'EV-ServiceDesk push', theme: evTheme(Brightness.light), home: home));
}
