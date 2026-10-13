import 'dart:async';

import 'package:flutter/material.dart';

import 'app/app_state.dart';
import 'app/push_service.dart';
import 'data/api/api_client.dart';
import 'data/api/token_store.dart';
import 'data/attachments.dart';
import 'data/http_repository.dart';
import 'data/prototype_repository.dart';
import 'data/repository.dart';
import 'push/firebase_push_channel.dart';
import 'push/push_channel.dart';
import 'screens/home_shell.dart';
import 'ui/bottom_nav.dart';
import 'screens/news/notification_feed.dart';
import 'screens/onboarding/phone_screen.dart';
import 'screens/support/ticket_chat_screen.dart';
import 'theme/app_theme.dart';

// Каркас — Глава 4; тема и компоненты — Глава 6; кликабельный прототип на фикстурах — Глава 7 (ADR 0011).
// Реальный API и авторизация — Глава 18 (ADR 0022): --dart-define=API_BASE_URL=http://host:8000;
// без него — прототип на фикстурах с панелью «Демо». Push — Глава 20 (ADR 0024 п. 4): --dart-define FIREBASE_*
// (mobile/firebase.local.json); без них push выключен, центр уведомлений работает.
const apiBaseUrl = String.fromEnvironment('API_BASE_URL');

Future<void> main() async {
  WidgetsFlutterBinding.ensureInitialized();
  final repository = await createRepository();
  runApp(EvServiceDeskApp(repository: repository, push: await createPush(repository)));
}

Future<ClientRepository> createRepository() async {
  if (apiBaseUrl.isEmpty) return PrototypeRepository();
  return HttpClientRepository(ApiClient(baseUrl: Uri.parse(apiBaseUrl), tokens: await SecureTokenStore.open()));
}

Future<PushService?> createPush(ClientRepository repository) async {
  final config = FirebaseConfig.fromEnvironment();
  if (repository is! HttpClientRepository || !config.isComplete) return null;
  try {
    return PushService(await FirebasePushChannel.init(config), repository);
  } on Object catch (e) {
    debugPrint('push: Firebase не инициализирован: $e');
    return null;
  }
}

class EvServiceDeskApp extends StatefulWidget {
  const EvServiceDeskApp({
    super.key,
    required this.repository,
    this.signedIn = false,
    this.push,
    this.attachmentSource,
  });

  final ClientRepository repository;
  final PushService? push;

  /// Камера и галерея; в автотестах — фейк.
  final AttachmentSource? attachmentSource;

  /// Сразу после входа (тесты, демонстрация главного экрана).
  final bool signedIn;

  @override
  State<EvServiceDeskApp> createState() => _EvServiceDeskAppState();
}

class _EvServiceDeskAppState extends State<EvServiceDeskApp> {
  late final AppState _state = AppState(
    widget.repository,
    signedIn: widget.signedIn,
    push: widget.push,
    attachmentSource: widget.attachmentSource,
  );
  final _navigator = GlobalKey<NavigatorState>();
  final _messenger = GlobalKey<ScaffoldMessengerState>();
  late bool _signedIn;
  late final AppLifecycleListener _lifecycle;
  final _pushSubscriptions = <StreamSubscription<PushEvent>>[];

  /// Нажатие на push до входа (запуск закрытого приложения, проверка сессии) — откроется после входа.
  PushEvent? _pendingPush;

  @override
  void initState() {
    super.initState();
    _signedIn = _state.signedIn;
    _state.addListener(_onState);
    // Возврат из фона — данные перечитываются: статусы агрегатов могли измениться после замены в сервисе
    // (ADR 0023 п. 5). Загруженное остаётся на экране до ответа.
    _lifecycle = AppLifecycleListener(onResume: () {
      if (_state.signedIn) _state.refresh();
    });
    if (_state.signedIn) {
      _state.refresh();
      widget.push?.register();
    } else {
      _state.restoreSession();
    }
    final push = widget.push;
    if (push != null) {
      _pushSubscriptions
        ..add(push.received.listen(_onForegroundPush))
        ..add(push.opened.listen(_openPush));
      push.initialOpened().then((e) => e == null ? null : _openPush(e));
    }
  }

  /// Вход/выход меняет корневой экран — экраны онбординга (или открытые поверх) закрываются.
  void _onState() {
    if (_state.signedIn != _signedIn) {
      _signedIn = _state.signedIn;
      _navigator.currentState?.popUntil((r) => r.isFirst);
      final pending = _pendingPush;
      _pendingPush = null;
      if (_signedIn && pending != null) WidgetsBinding.instance.addPostFrameCallback((_) => _openPush(pending));
    }
  }

  /// Push при открытом приложении — баннер внутри приложения; по открытому чату — не показывается (его обновит
  /// сокет). Счётчик непрочитанных обновляется сразу.
  void _onForegroundPush(PushEvent e) {
    if (!_state.signedIn) return;
    if (e.notificationId != null) _state.refreshUnread();
    if (e.ticketId != null && e.ticketId == _state.openChatTicketId) return;
    _messenger.currentState
      ?..hideCurrentSnackBar()
      ..showSnackBar(SnackBar(
        key: const Key('push-banner'),
        content: Text([e.title, e.body].where((t) => t.isNotEmpty).join('\n')),
        action: SnackBarAction(label: 'Открыть', onPressed: () => _openPush(e)),
      ));
  }

  /// Нажатие на push: тикет — чат обращения, публикация или напоминание — центр уведомлений с этим уведомлением.
  Future<void> _openPush(PushEvent e) async {
    if (!_state.signedIn || _state.restoring) {
      _pendingPush = e;
      return;
    }
    final ticketId = e.ticketId;
    final notificationId = e.notificationId;
    final navigator = _navigator.currentState;
    if (navigator == null) return;
    if (ticketId != null) {
      if (ticketId == _state.openChatTicketId) return;
      try {
        final ticket = await _state.repository.ticket(ticketId);
        navigator.push(MaterialPageRoute<void>(builder: (_) => TicketChatScreen(ticket: ticket)));
      } on Exception {
        // Нет сети — открыть «Поддержку»: обращение в списке.
        _state.selectSection(EvSection.support);
      }
    } else if (notificationId != null) {
      await widget.push?.markOpened(notificationId);
      unawaited(_state.refreshUnread());
      navigator.push(MaterialPageRoute<void>(builder: (_) => NotificationCenterScreen(openId: notificationId)));
    }
  }

  @override
  void dispose() {
    _lifecycle.dispose();
    for (final s in _pushSubscriptions) {
      s.cancel();
    }
    _state.removeListener(_onState);
    _state.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return AppScope(
      state: _state,
      child: ListenableBuilder(
        listenable: _state,
        builder: (context, _) => MaterialApp(
          title: 'EV-ServiceDesk',
          navigatorKey: _navigator,
          scaffoldMessengerKey: _messenger,
          theme: evTheme(Brightness.light),
          darkTheme: evTheme(Brightness.dark),
          themeMode: _state.themeMode,
          home: const _Root(),
        ),
      ),
    );
  }
}

/// Корневой экран: онбординг или разделы приложения — по состоянию входа.
class _Root extends StatelessWidget {
  const _Root();

  @override
  Widget build(BuildContext context) {
    final app = AppScope.of(context);
    if (app.restoring) return const Scaffold(body: Center(child: CircularProgressIndicator()));
    return app.signedIn ? const HomeShell() : const PhoneScreen();
  }
}
