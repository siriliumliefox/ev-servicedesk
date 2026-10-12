import 'package:flutter/material.dart';

import 'app/app_state.dart';
import 'data/api/api_client.dart';
import 'data/api/token_store.dart';
import 'data/http_repository.dart';
import 'data/prototype_repository.dart';
import 'data/repository.dart';
import 'screens/home_shell.dart';
import 'screens/onboarding/phone_screen.dart';
import 'theme/app_theme.dart';

// Каркас — Глава 4; тема и компоненты — Глава 6; кликабельный прототип на фикстурах — Глава 7 (ADR 0011).
// Реальный API и авторизация — Глава 18 (ADR 0022): --dart-define=API_BASE_URL=http://host:8000;
// без него — прототип на фикстурах с панелью «Демо».
const apiBaseUrl = String.fromEnvironment('API_BASE_URL');

Future<void> main() async {
  WidgetsFlutterBinding.ensureInitialized();
  runApp(EvServiceDeskApp(repository: await createRepository()));
}

Future<ClientRepository> createRepository() async {
  if (apiBaseUrl.isEmpty) return PrototypeRepository();
  return HttpClientRepository(ApiClient(baseUrl: Uri.parse(apiBaseUrl), tokens: await SecureTokenStore.open()));
}

class EvServiceDeskApp extends StatefulWidget {
  const EvServiceDeskApp({super.key, required this.repository, this.signedIn = false});

  final ClientRepository repository;

  /// Сразу после входа (тесты, демонстрация главного экрана).
  final bool signedIn;

  @override
  State<EvServiceDeskApp> createState() => _EvServiceDeskAppState();
}

class _EvServiceDeskAppState extends State<EvServiceDeskApp> {
  late final AppState _state = AppState(widget.repository, signedIn: widget.signedIn);
  final _navigator = GlobalKey<NavigatorState>();
  late bool _signedIn;

  /// Возврат из фона — данные перечитываются: статусы агрегатов могли измениться после замены в сервисе
  /// (ADR 0023 п. 5). Загруженное остаётся на экране до ответа.
  late final _lifecycle = AppLifecycleListener(onResume: () {
    if (_state.signedIn) _state.refresh();
  });

  @override
  void initState() {
    super.initState();
    _signedIn = _state.signedIn;
    _state.addListener(_onState);
    _lifecycle; // создаётся сразу, а не при первом обращении
    if (_state.signedIn) {
      _state.refresh();
    } else {
      _state.restoreSession();
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
