// Состояние приложения клиента: сессия, авто на аккаунте, выбранное авто, непрочитанные уведомления.
// Без внешних пакетов: ChangeNotifier + InheritedNotifier (AppScope).
import 'package:flutter/material.dart';

import '../data/models.dart';
import '../data/prototype_repository.dart';
import '../data/repository.dart';

class AppState extends ChangeNotifier {
  AppState(this.repository, {bool signedIn = false}) : _signedIn = signedIn;

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

  Future<void> signIn() async {
    _signedIn = true;
    await refresh();
  }

  void signOut() {
    _signedIn = false;
    _vehicles = const [];
    _selectedVehicleId = null;
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
      _vehiclesError = e;
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
