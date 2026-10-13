import 'package:flutter/material.dart';

import 'app/app_state.dart';
import 'app/push_router.dart';
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
import 'screens/onboarding/phone_screen.dart';
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
  PushRouter? _pushRouter;

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
      _state.signIn();
    } else {
      _state.restoreSession();
    }
    if (widget.push case final push?) {
      _pushRouter = PushRouter(app: _state, push: push, navigator: _navigator, messenger: _messenger);
    }
  }

  /// Вход/выход меняет корневой экран — экраны онбординга (или открытые поверх) закрываются.
  void _onState() {
    if (_state.signedIn != _signedIn) {
      _signedIn = _state.signedIn;
      _navigator.currentState?.popUntil((r) => r.isFirst);
    }
  }

  @override
  void dispose() {
    _lifecycle.dispose();
    _pushRouter?.dispose();
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
