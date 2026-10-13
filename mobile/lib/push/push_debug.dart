// Отладочный экран push (Глава 15, ADR 0019 п. 18): проверка FCM на реальном iPhone.
// Не входит в навигацию приложения — отдельная точка входа lib/main_push_debug.dart.
// Экраны центра уведомлений клиента — Глава 20.
//
// Экран получает FCM-токен, сам регистрирует его в backend (POST /v1/push-tokens) и
// показывает каждый push с временем получения и задержкой от момента, когда FCM принял
// сообщение (`sentTime`). Нажатие на push — POST /v1/notifications/{id}/opened (журнал
// открываемости). Конфигурация — --dart-define-from-file=push_e2e.local.json
// (создаёт scripts/push_e2e.py setup; файл в .gitignore).
import 'dart:async';
import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:http/http.dart' as http;

import 'push_channel.dart';

export 'push_channel.dart';

/// Значения --dart-define (scripts/push_e2e.py setup).
class PushDebugConfig {
  const PushDebugConfig({
    required this.apiBaseUrl,
    required this.accessToken,
    required this.firebaseApiKey,
    required this.firebaseAppId,
    required this.firebaseSenderId,
    required this.firebaseProjectId,
    required this.iosBundleId,
  });

  factory PushDebugConfig.fromEnvironment() => const PushDebugConfig(
        apiBaseUrl: String.fromEnvironment('API_BASE_URL'),
        accessToken: String.fromEnvironment('ACCESS_TOKEN'),
        firebaseApiKey: String.fromEnvironment('FIREBASE_API_KEY'),
        firebaseAppId: String.fromEnvironment('FIREBASE_APP_ID'),
        firebaseSenderId: String.fromEnvironment('FIREBASE_SENDER_ID'),
        firebaseProjectId: String.fromEnvironment('FIREBASE_PROJECT_ID'),
        iosBundleId: String.fromEnvironment('FIREBASE_IOS_BUNDLE_ID'),
      );

  final String apiBaseUrl;
  final String accessToken;
  final String firebaseApiKey;
  final String firebaseAppId;
  final String firebaseSenderId;
  final String firebaseProjectId;
  final String iosBundleId;

  FirebaseConfig get firebase => FirebaseConfig(
        apiKey: firebaseApiKey,
        appId: firebaseAppId,
        senderId: firebaseSenderId,
        projectId: firebaseProjectId,
        iosBundleId: iosBundleId,
      );

  /// Имена незаданных значений — экран показывает их вместо попытки подключиться.
  List<String> get missing => [
        if (apiBaseUrl.isEmpty) 'API_BASE_URL',
        if (accessToken.isEmpty) 'ACCESS_TOKEN',
        if (firebaseApiKey.isEmpty) 'FIREBASE_API_KEY',
        if (firebaseAppId.isEmpty) 'FIREBASE_APP_ID',
        if (firebaseSenderId.isEmpty) 'FIREBASE_SENDER_ID',
        if (firebaseProjectId.isEmpty) 'FIREBASE_PROJECT_ID',
      ];
}

/// Вызовы backend: регистрация токена и отметка открытия.
class PushDebugApi {
  PushDebugApi(this.config, {http.Client? client}) : _client = client ?? http.Client();

  final PushDebugConfig config;
  final http.Client _client;

  Map<String, String> get _headers => {
        'Authorization': 'Bearer ${config.accessToken}',
        'Content-Type': 'application/json',
      };

  Uri _uri(String path) => Uri.parse('${config.apiBaseUrl.replaceAll(RegExp(r'/+$'), '')}/v1$path');

  Future<int> register(String token) async {
    final r = await _client.post(_uri('/push-tokens'), headers: _headers, body: jsonEncode({'token': token}));
    return r.statusCode;
  }

  Future<int> opened(int notificationId, String token) async {
    final r = await _client.post(
      _uri('/notifications/$notificationId/opened'),
      headers: _headers,
      body: jsonEncode({'token': token}),
    );
    return r.statusCode;
  }
}

class PushDebugScreen extends StatefulWidget {
  const PushDebugScreen({super.key, required this.channel, required this.api, this.clock = DateTime.now});

  final PushChannel channel;
  final PushDebugApi api;
  final DateTime Function() clock;

  @override
  State<PushDebugScreen> createState() => _PushDebugScreenState();
}

class _PushDebugScreenState extends State<PushDebugScreen> {
  String _permission = '…';
  String? _token;
  String _registration = '…';
  final List<(PushEvent, String?)> _events = [];
  final List<StreamSubscription<Object>> _subs = [];

  @override
  void initState() {
    super.initState();
    _start();
  }

  Future<void> _start() async {
    final permission = await widget.channel.permission();
    if (!mounted) return;
    setState(() => _permission = permission);
    _subs
      ..add(widget.channel.tokenRefresh.listen(_register))
      ..add(widget.channel.received.listen((e) => _add(e, null)))
      ..add(widget.channel.opened.listen(_open));
    final token = await widget.channel.token();
    await _register(token);
    final initial = await widget.channel.initialOpened();
    if (initial != null) await _open(initial);
  }

  Future<void> _register(String? token) async {
    if (!mounted) return;
    setState(() {
      _token = token;
      _registration = token == null ? 'нет токена (APNs/разрешение?)' : 'регистрация…';
    });
    if (token == null) return;
    String result;
    try {
      final status = await widget.api.register(token);
      result = status == 201 ? 'зарегистрирован (201)' : 'ошибка регистрации: HTTP $status';
    } catch (e) {
      result = 'backend недоступен: ${e.runtimeType}';
    }
    if (mounted) setState(() => _registration = result);
  }

  void _add(PushEvent event, String? note) {
    if (mounted) setState(() => _events.insert(0, (event, note)));
  }

  Future<void> _open(PushEvent event) async {
    final id = event.notificationId;
    final token = _token;
    if (id == null || token == null) {
      _add(event, 'открыт (без notification_id — push по тикету)');
      return;
    }
    String note;
    try {
      final status = await widget.api.opened(id, token);
      note = status == 204 ? 'открыт → opened записан (204)' : 'открыт → opened: HTTP $status';
    } catch (e) {
      note = 'открыт → backend недоступен: ${e.runtimeType}';
    }
    _add(event, note);
  }

  @override
  void dispose() {
    for (final s in _subs) {
      s.cancel();
    }
    super.dispose();
  }

  static String _time(DateTime t) {
    final l = t.toLocal();
    String two(int v) => v.toString().padLeft(2, '0');
    return '${two(l.hour)}:${two(l.minute)}:${two(l.second)}.${l.millisecond.toString().padLeft(3, '0')}';
  }

  @override
  Widget build(BuildContext context) {
    final token = _token;
    return Scaffold(
      appBar: AppBar(title: const Text('Push: проверка на устройстве')),
      body: ListView(
        padding: const EdgeInsets.all(16),
        children: [
          Text('Разрешение: $_permission'),
          Text('Backend: ${widget.api.config.apiBaseUrl}'),
          Text('Токен: $_registration', key: const Key('registration')),
          if (token != null)
            Row(
              children: [
                Expanded(child: SelectableText(token, maxLines: 2, style: const TextStyle(fontSize: 11))),
                IconButton(
                  tooltip: 'Скопировать токен',
                  icon: const Icon(Icons.copy),
                  onPressed: () => Clipboard.setData(ClipboardData(text: token)),
                ),
              ],
            ),
          const Divider(),
          Text('Получено: ${_events.length}', style: Theme.of(context).textTheme.titleMedium),
          for (final (e, note) in _events)
            ListTile(
              key: ValueKey(e),
              title: Text('${e.title}: ${e.body}'),
              subtitle: Text([
                'получено ${_time(e.receivedAt)}',
                if (e.sentAt != null) 'FCM принял ${_time(e.sentAt!)}',
                if (e.latency != null) 'задержка ${e.latency!.inMilliseconds} мс',
                if (e.data.isNotEmpty) e.data.entries.map((d) => '${d.key}=${d.value}').join(' '),
                if (note != null) note,
              ].join(' · ')),
            ),
        ],
      ),
    );
  }
}
