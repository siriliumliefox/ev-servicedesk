// Отладочный экран push (Глава 15, ADR 0019 п. 18): регистрация токена, задержка, opened.
import 'dart:async';
import 'dart:convert';

import 'package:ev_servicedesk/push/push_debug.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';

const config = PushDebugConfig(
  apiBaseUrl: 'http://192.168.1.10:8000/',
  accessToken: 'access',
  firebaseApiKey: 'k',
  firebaseAppId: 'a',
  firebaseSenderId: 's',
  firebaseProjectId: 'p',
  iosBundleId: 'com.etsavtogomel.evServicedesk',
);

class FakeChannel implements PushChannel {
  FakeChannel(this._token);

  final String? _token;
  final received$ = StreamController<PushEvent>.broadcast();
  final opened$ = StreamController<PushEvent>.broadcast();

  @override
  Future<String> permission() async => 'authorized';
  @override
  Future<String?> token() async => _token;
  @override
  Stream<String> get tokenRefresh => const Stream.empty();
  @override
  Stream<PushEvent> get received => received$.stream;
  @override
  Stream<PushEvent> get opened => opened$.stream;
  @override
  Future<PushEvent?> initialOpened() async => null;
}

void main() {
  final requests = <http.Request>[];
  late MockClient backend;

  setUp(() {
    requests.clear();
    backend = MockClient((r) async {
      requests.add(r);
      return http.Response('', r.url.path.endsWith('/opened') ? 204 : 201);
    });
  });

  testWidgets('регистрирует токен, показывает задержку и пишет opened', (tester) async {
    final channel = FakeChannel('fcm-token-1');
    await tester
        .pumpWidget(MaterialApp(home: PushDebugScreen(channel: channel, api: PushDebugApi(config, client: backend))));
    await tester.pumpAndSettle();

    expect(find.text('Токен: зарегистрирован (201)'), findsOneWidget);
    expect(requests.single.url.toString(), 'http://192.168.1.10:8000/v1/push-tokens');
    expect(requests.single.headers['Authorization'], 'Bearer access');
    expect(jsonDecode(requests.single.body), {'token': 'fcm-token-1'});

    final sent = DateTime(2026, 10, 12, 12, 0, 0);
    channel.received$.add(PushEvent(
      title: 'Новости',
      body: 'Акция',
      data: const {'notification_id': '42', 'type': 'news'},
      receivedAt: sent.add(const Duration(milliseconds: 850)),
      sentAt: sent,
    ));
    await tester.pumpAndSettle();
    expect(find.textContaining('задержка 850 мс'), findsOneWidget);

    channel.opened$.add(PushEvent(
      title: 'Новости',
      body: 'Акция',
      data: const {'notification_id': '42', 'type': 'news'},
      receivedAt: sent.add(const Duration(seconds: 5)),
      opened: true,
    ));
    await tester.pumpAndSettle();
    expect(requests.last.url.path, '/v1/notifications/42/opened');
    expect(jsonDecode(requests.last.body), {'token': 'fcm-token-1'});
    expect(find.textContaining('opened записан (204)'), findsOneWidget);
  });

  testWidgets('без APNs-токена — подсказка, запросов нет', (tester) async {
    await tester.pumpWidget(
        MaterialApp(home: PushDebugScreen(channel: FakeChannel(null), api: PushDebugApi(config, client: backend))));
    await tester.pumpAndSettle();
    expect(find.text('Токен: нет токена (APNs/разрешение?)'), findsOneWidget);
    expect(requests, isEmpty);
  });

  test('незаданные значения конфигурации перечисляются', () {
    const empty = PushDebugConfig(
      apiBaseUrl: '',
      accessToken: '',
      firebaseApiKey: '',
      firebaseAppId: '',
      firebaseSenderId: '',
      firebaseProjectId: '',
      iosBundleId: '',
    );
    expect(empty.missing, contains('ACCESS_TOKEN'));
    expect(config.missing, isEmpty);
  });
}
