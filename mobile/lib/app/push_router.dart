// Куда ведёт push (ADR 0024 п. 4): на открытом приложении — баннер внутри приложения (по открытому чату — нет,
// его обновит сокет); нажатие — тикет → чат обращения, публикация или напоминание → центр уведомлений с этим
// уведомлением. Push, нажатый до входа (запуск закрытого приложения, проверка сессии), откроется после входа.
import 'dart:async';

import 'package:flutter/material.dart';

import '../push/push_channel.dart';
import '../screens/news/notification_feed.dart';
import '../screens/support/ticket_chat_screen.dart';
import 'app_state.dart';
import 'push_service.dart';

class PushRouter {
  PushRouter({required this.app, required this.push, required this.navigator, required this.messenger}) {
    _subscriptions
      ..add(push.channel.received.listen(_onForeground))
      ..add(push.channel.opened.listen(open));
    app.addListener(_onAppState);
    push.channel.initialOpened().then((e) => e == null ? null : open(e));
  }

  final AppState app;
  final GlobalKey<NavigatorState> navigator;
  final GlobalKey<ScaffoldMessengerState> messenger;
  final PushService push;
  final _subscriptions = <StreamSubscription<PushEvent>>[];
  PushEvent? _pending;

  void dispose() {
    app.removeListener(_onAppState);
    for (final s in _subscriptions) {
      unawaited(s.cancel());
    }
  }

  void _onAppState() {
    final pending = _pending;
    if (pending == null || !app.signedIn || app.restoring) return;
    _pending = null;
    // После кадра: корень приложения уже сменил экран входа на разделы.
    WidgetsBinding.instance.addPostFrameCallback((_) => open(pending));
  }

  void _onForeground(PushEvent e) {
    if (!app.signedIn) return;
    if (e.notificationId != null) app.refreshUnread();
    if (e.ticketId != null && e.ticketId == app.openChatTicketId) return;
    _banner(SnackBar(
      key: const Key('push-banner'),
      content: Text([e.title, e.body].where((t) => t.isNotEmpty).join('\n')),
      action: SnackBarAction(label: 'Открыть', onPressed: () => open(e)),
    ));
  }

  Future<void> open(PushEvent e) async {
    if (!app.signedIn || app.restoring) {
      _pending = e;
      return;
    }
    if (e.ticketId case final ticketId?) return _openTicket(ticketId);
    if (e.notificationId case final notificationId?) return _openNotification(notificationId);
  }

  Future<void> _openTicket(int ticketId) async {
    if (ticketId == app.openChatTicketId) return;
    try {
      final ticket = await app.repository.ticket(ticketId);
      navigator.currentState?.push(MaterialPageRoute<void>(builder: (_) => TicketChatScreen(ticket: ticket)));
    } on Exception {
      _banner(SnackBar(content: Text('Не удалось открыть обращение №$ticketId — оно есть в «Поддержке»')));
    }
  }

  /// Открытие отмечает уведомление прочитанным на сервере — лента центра покажет его прочитанным.
  Future<void> _openNotification(int notificationId) async {
    await push.markOpened(notificationId);
    unawaited(app.refreshUnread());
    final nav = navigator.currentState;
    if (nav == null) return;
    unawaited(nav.push(MaterialPageRoute<void>(builder: (_) => const NotificationCenterScreen())));
    try {
      final item = (await app.repository.notifications()).where((n) => n.id == notificationId).firstOrNull;
      if (item != null && nav.mounted) showNotificationSheet(nav.context, item);
    } on Exception {
      // Нет сети — центр покажет ошибку с «Повторить».
    }
  }

  void _banner(SnackBar bar) => messenger.currentState
    ?..hideCurrentSnackBar()
    ..showSnackBar(bar);
}
