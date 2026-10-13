// «Новости»: новости и акции из ленты уведомлений (ADR 0024 п. 6). Прошивки и напоминания о ТО — в центре
// уведомлений (колокольчик в шапке).
import 'package:flutter/material.dart';

import '../../data/models.dart';
import '../../ui/demo_panel.dart';
import '../../ui/notification_bell.dart';
import 'notification_feed.dart';

class NewsScreen extends StatelessWidget {
  const NewsScreen({super.key});

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text('Новости'), actions: const [NotificationBell(), DemoButton()]),
      body: NotificationFeed(
        types: [for (final t in NotificationType.values) if (t.isNews) t],
        emptyTitle: 'Пока нет новостей',
        emptyMessage: 'Здесь появятся новости и акции для вашего авто',
      ),
    );
  }
}
