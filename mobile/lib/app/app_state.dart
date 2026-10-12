// Состояние приложения клиента: сессия, авто на аккаунте, выбранное авто, непрочитанные уведомления.
// Без внешних пакетов: ChangeNotifier + InheritedNotifier (AppScope).
import 'dart:async';

import 'package:flutter/material.dart';

import '../data/api/error_text.dart';
import '../data/models.dart';
import '../data/prototype_repository.dart';
import '../data/repository.dart';

class AppState extends ChangeNotifier {
  AppState(this.repository, {bool signedIn = false}) : _signedIn = signedIn {
    _sessionEndedSubscription = repository.sessionEnded.listen((_) => _sessionEnded());
  }

  late final StreamSubscription<void> _sessionEndedSubscription;

  @override
  void dispose() {
    _sessionEndedSubscription.cancel();
    super.dispose();
  }

  final ClientRepository repository;

  /// Панель «Демо» доступна только в прототипе.
  PrototypeRepository? get prototype => repository is PrototypeRepository ? repository as PrototypeRepository : null;

  bool _signedIn;
  bool get signedIn => _signedIn;

  List<Vehicle> _vehicles = const [];
  List<Vehicle> get vehicles => _vehicles;

  int? _selectedVehicleId;
  Vehicle? get vehicle {
    for (final v in _vehicles) {
      if (v.id == _selectedVehicleId) return v;
    }
    return _vehicles.isEmpty ? null : _vehicles.first;
  }

  int _unread = 0;
  int get unreadNotifications => _unread;

  ThemeMode _themeMode = ThemeMode.system;
  ThemeMode get themeMode => _themeMode;

  /// Меняется при смене сценария/данных — экраны с данными перезагружаются (AsyncView.reloadKey).
  int _revision = 0;
  int get revision => _revision;

  /// Ошибка загрузки списка авто (нет сети) — главный экран показывает состояние ошибки.
  Object? _vehiclesError;
  Object? get vehiclesError => _vehiclesError;

  bool _loadingVehicles = false;
  bool get loadingVehicles => _loadingVehicles;

  /// Проверка сохранённой сессии при запуске — на это время экран загрузки вместо онбординга.
  bool _restoring = false;
  bool get restoring => _restoring;

  /// Сообщение на экране входа (сессия завершена сервером); показывается один раз.
  String? _notice;
  String? takeNotice() {
    final notice = _notice;
    _notice = null;
    return notice;
  }

  /// Сохранённая сессия — сразу главный экран; без сети он покажет «Нет подключения» (ADR 0022 п. 10).
  Future<void> restoreSession() async {
    _restoring = true;
    notifyListeners();
    final restored = await repository.restoreSession();
    _restoring = false;
    if (restored) {
      await signIn();
    } else {
      notifyListeners();
    }
  }

  Future<void> signIn() async {
    _signedIn = true;
    await refresh();
  }

  /// Выход с устройства.
  Future<void> signOut() async {
    await repository.signOut();
    _clearSession();
  }

  /// Отзыв согласия на обработку ПД: завершает все сессии пользователя.
  Future<void> withdrawPdConsent() async {
    await repository.withdrawPdConsent();
    _clearSession();
  }

  void _sessionEnded() {
    _notice = sessionEndedText;
    _clearSession();
  }

  void _clearSession() {
    _signedIn = false;
    _vehicles = const [];
    _selectedVehicleId = null;
    _vehiclesError = null;
    _unread = 0;
    _bump();
  }

  Future<void> refresh() async {
    _loadingVehicles = true;
    _vehiclesError = null;
    notifyListeners();
    try {
      _vehicles = await repository.vehicles();
      await refreshUnread();
    } on Exception catch (e) {
      // Сессия завершена во время загрузки — экран входа, а не ошибка главного экрана.
      if (_signedIn) _vehiclesError = e;
    }
    _loadingVehicles = false;
    _bump();
  }

  Future<void> refreshUnread() async {
    try {
      final items = await repository.notifications();
      _unread = items.where((n) => !n.isRead).length;
      notifyListeners();
    } on Exception {
      // Счётчик непрочитанных не критичен: при ошибке остаётся прежним.
    }
  }

  void selectVehicle(int vehicleId) {
    _selectedVehicleId = vehicleId;
    _bump();
  }

  void vehicleUpdated(Vehicle v) {
    _vehicles = [for (final old in _vehicles) old.id == v.id ? v : old];
    _bump();
  }

  void vehicleAdded(Vehicle v) {
    _vehicles = [..._vehicles, v];
    _selectedVehicleId = v.id;
    _bump();
  }

  void setThemeMode(ThemeMode mode) {
    _themeMode = mode;
    notifyListeners();
  }

  // ---------- Сценарии прототипа (панель «Демо») ----------

  Future<void> setOffline(bool value) async {
    prototype?.offline = value;
    await refresh();
  }

  Future<void> setAccountScenario(AccountScenario scenario) async {
    prototype?.reset(scenario);
    _selectedVehicleId = null;
    await refresh();
  }

  void _bump() {
    _revision++;
    notifyListeners();
  }
}

class AppScope extends InheritedNotifier<AppState> {
  const AppScope({super.key, required AppState state, required super.child}) : super(notifier: state);

  static AppState of(BuildContext context) => context.dependOnInheritedWidgetOfExactType<AppScope>()!.notifier!;

  /// Без подписки на изменения — для обработчиков нажатий.
  static AppState read(BuildContext context) => context.getInheritedWidgetOfExactType<AppScope>()!.notifier!;
}
