import 'package:flutter/material.dart';

import 'app/app_state.dart';
import 'data/prototype_repository.dart';
import 'data/repository.dart';
import 'screens/home_shell.dart';
import 'screens/onboarding/phone_screen.dart';
import 'theme/app_theme.dart';

// Каркас — Глава 4; тема и компоненты — Глава 6; кликабельный прототип на фикстурах — Глава 7 (ADR 0011).
// Реальный API и авторизация — Глава 18: ClientRepository на HTTP вместо PrototypeRepository.
void main() {
  runApp(EvServiceDeskApp(repository: PrototypeRepository()));
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

  @override
  void initState() {
    super.initState();
    _signedIn = _state.signedIn;
    _state.addListener(_onState);
    if (_state.signedIn) _state.refresh();
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
  Widget build(BuildContext context) => AppScope.of(context).signedIn ? const HomeShell() : const PhoneScreen();
}
