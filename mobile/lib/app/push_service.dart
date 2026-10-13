// Push в приложении (ADR 0024 п. 4): регистрация FCM-токена после входа и при его обновлении, удаление до выхода,
// отметка открытия. Куда ведёт push — решает приложение (main.dart): тикет → чат, остальное → центр уведомлений.
import 'dart:async';

import 'package:flutter/foundation.dart';

import '../data/repository.dart';
import '../push/push_channel.dart';

class PushService {
  PushService(this.channel, this.repository);

  final PushChannel channel;
  final ClientRepository repository;

  String? _token;
  StreamSubscription<String>? _refresh;

  /// Токен, зарегистрированный для этого входа (нужен для отметки открытия).
  String? get token => _token;

  Stream<PushEvent> get received => channel.received;
  Stream<PushEvent> get opened => channel.opened;
  Future<PushEvent?> initialOpened() => channel.initialOpened();

  /// После входа: разрешение, токен, регистрация. Сбой push не мешает работе приложения.
  Future<void> register() async {
    try {
      await channel.permission();
      final token = await channel.token();
      if (token != null) await _register(token);
      _refresh ??= channel.tokenRefresh.listen((t) => unawaited(_register(t)));
    } on Object catch (e) {
      debugPrint('push: регистрация не удалась: $e');
    }
  }

  Future<void> _register(String token) async {
    try {
      await repository.registerPushToken(token);
      _token = token;
    } on Object catch (e) {
      debugPrint('push: токен не зарегистрирован: $e');
    }
  }

  /// До выхода, пока сессия действует: иначе push продолжат приходить на устройство без входа.
  Future<void> unregister() async {
    unawaited(_refresh?.cancel()); // ждать отписки незачем: выход не должен зависеть от неё
    _refresh = null;
    final token = _token;
    _token = null;
    if (token == null) return;
    try {
      await repository.unregisterPushToken(token);
    } on Object catch (e) {
      debugPrint('push: токен не удалён: $e');
    }
  }

  /// Клиент открыл push публикации или напоминания: журнал открываемости (и прочитано).
  Future<void> markOpened(int notificationId) async {
    final token = _token ?? await channel.token();
    if (token == null) return;
    try {
      await repository.markNotificationOpened(notificationId, token);
    } on Object catch (e) {
      debugPrint('push: открытие не отмечено: $e');
    }
  }
}
