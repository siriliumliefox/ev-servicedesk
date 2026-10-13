// Колокольчик в шапке разделов (ADR 0024 п. 6): счётчик непрочитанных, открывает центр уведомлений.
import 'package:flutter/material.dart';

import '../app/app_state.dart';
import '../screens/news/notification_feed.dart';

class NotificationBell extends StatelessWidget {
  const NotificationBell({super.key});

  @override
  Widget build(BuildContext context) {
    final unread = AppScope.of(context).unreadNotifications;
    final icon = Icon(unread > 0 ? Icons.notifications : Icons.notifications_outlined);
    return IconButton(
      key: const Key('notification-bell'),
      tooltip: unread > 0 ? 'Уведомления: непрочитанных $unread' : 'Уведомления',
      icon: unread > 0 ? Badge(label: Text('$unread'), child: icon) : icon,
      onPressed: () =>
          Navigator.of(context).push(MaterialPageRoute<void>(builder: (_) => const NotificationCenterScreen())),
    );
  }
}
