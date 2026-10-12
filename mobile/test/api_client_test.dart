// ApiClient (глава 18, ADR 0022 п. 6, 7, 12): обновление токена одним запросом, завершение сессии, ошибки сети
// и контракта. HTTP — MockClient из package:http.
import 'dart:convert';

import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';

import 'package:ev_servicedesk/data/api/api_client.dart';
import 'package:ev_servicedesk/data/api/error_text.dart';
import 'package:ev_servicedesk/data/api/token_store.dart';
import 'package:ev_servicedesk/data/repository.dart';

http.Response _json(int status, Object body, {Map<String, String> headers = const {}}) => http.Response.bytes(
      utf8.encode(jsonEncode(body)),
      status,
      headers: {'content-type': 'application/json', ...headers},
    );

http.Response _error(int status, String code,
        {Map<String, Object?>? details, Map<String, String> headers = const {}}) =>
    _json(
        status,
        {
          'error': {'code': code, 'message': 'server text', 'details': details},
        },
        headers: headers);

/// Сервер с одним действующим access-токеном и ротацией refresh: старый refresh — 401.
class _FakeServer {
  int refreshCalls = 0;
  String access = 'access-1';
  String refresh = 'refresh-1';
  final requests = <http.Request>[];

  /// Ответ refresh: по умолчанию — новая пара.
  Future<http.Response> Function()? onRefresh;

  Future<http.Response> handle(http.Request r) async {
    requests.add(r);
    if (r.url.path == '/v1/auth/refresh') {
      refreshCalls++;
      if (onRefresh != null) return onRefresh!();
      final presented = (jsonDecode(r.body) as Map)['refresh_token'];
      if (presented != refresh) return _error(401, 'UNAUTHORIZED');
      await Future<void>.delayed(const Duration(milliseconds: 20));
      access = 'access-${refreshCalls + 1}';
      refresh = 'refresh-${refreshCalls + 1}';
      return _json(200, {'access_token': access, 'refresh_token': refresh, 'expires_in': 900});
    }
    if (r.headers['Authorization'] != 'Bearer $access') return _error(401, 'UNAUTHORIZED');
    return _json(200, {'path': r.url.path});
  }
}

ApiClient _client(_FakeServer server, TokenStore tokens, {Duration timeout = const Duration(seconds: 5)}) => ApiClient(
      baseUrl: Uri.parse('http://api.test:8000'),
      tokens: tokens,
      httpClient: MockClient(server.handle),
      timeout: timeout,
    );

void main() {
  group('сессия', () {
    test('перезапуск: access нет в памяти — один refresh по сохранённому токену, новый refresh сохранён', () async {
      final server = _FakeServer();
      final tokens = MemoryTokenStore('refresh-1');
      final api = _client(server, tokens);

      expect(await api.get('/vehicles'), {'path': '/v1/vehicles'});
      expect(server.refreshCalls, 1);
      expect(tokens.token, 'refresh-2');
      await api.get('/tickets');
      expect(server.refreshCalls, 1, reason: 'access в памяти переиспользуется');
    });

    test('параллельные 401 — один запрос refresh, каждый запрос повторён один раз', () async {
      final server = _FakeServer();
      final tokens = MemoryTokenStore();
      final api = _client(server, tokens);
      await api.startSession({'access_token': 'access-1', 'refresh_token': 'refresh-1'});
      server.access = 'expired'; // access-1 истёк: сервер примет только access-2 после refresh
      final results = await Future.wait([
        for (final p in ['/a', '/b', '/c', '/d']) api.get(p)
      ]);

      expect(results, [
        for (final p in ['/a', '/b', '/c', '/d']) {'path': '/v1$p'}
      ]);
      expect(server.refreshCalls, 1);
      expect(server.requests.where((r) => r.url.path != '/v1/auth/refresh').length, 8,
          reason: '4 запроса × (401 + повтор)');
      expect(tokens.token, 'refresh-2');
    });

    test('refresh отклонён (401) — сессия завершена: токен стёрт, событие sessionEnded, UNAUTHORIZED', () async {
      final server = _FakeServer()..refresh = 'rotated-elsewhere';
      final tokens = MemoryTokenStore('refresh-1');
      final api = _client(server, tokens);
      var ended = 0;
      api.sessionEnded.listen((_) => ended++);

      await expectLater(
        api.get('/vehicles'),
        throwsA(isA<ApiException>()
            .having((e) => e.code, 'code', 'UNAUTHORIZED')
            .having((e) => e.message, 'message', sessionEndedText)),
      );
      expect(tokens.token, isNull);
      expect(ended, 1);
    });

    test('обрыв на refresh — OfflineException, сессия сохранена, refresh не повторяется сам', () async {
      final server = _FakeServer()..onRefresh = () => throw http.ClientException('connection reset');
      final tokens = MemoryTokenStore('refresh-1');
      final api = _client(server, tokens);
      var ended = 0;
      api.sessionEnded.listen((_) => ended++);

      await expectLater(api.get('/vehicles'), throwsA(isA<OfflineException>()));
      expect(server.refreshCalls, 1);
      expect(tokens.token, 'refresh-1');
      expect(ended, 0);

      // Связь вернулась: следующий запрос пользователя обновляет токен.
      server.onRefresh = null;
      expect(await api.get('/vehicles'), {'path': '/v1/vehicles'});
      expect(server.refreshCalls, 2);
    });

    test('5xx на refresh — ошибка сервера, сессия сохранена', () async {
      final server = _FakeServer()..onRefresh = () async => http.Response('<html>Bad Gateway</html>', 502);
      final tokens = MemoryTokenStore('refresh-1');
      final api = _client(server, tokens);

      await expectLater(
        api.get('/vehicles'),
        throwsA(isA<ApiException>().having((e) => e.code, 'code', 'SERVER_ERROR')),
      );
      expect(tokens.token, 'refresh-1');
    });

    test('без сохранённого токена — сессии нет', () async {
      final api = _client(_FakeServer(), MemoryTokenStore());
      expect(await api.hasSession(), isFalse);
      await expectLater(api.get('/vehicles'), throwsA(isA<ApiException>()));
    });
  });

  group('ошибки', () {
    ApiClient respond(Future<http.Response> Function(http.Request) handler, {Duration? timeout}) => ApiClient(
          baseUrl: Uri.parse('http://api.test:8000'),
          tokens: MemoryTokenStore(),
          httpClient: MockClient(handler),
          timeout: timeout ?? const Duration(seconds: 5),
        );

    test('CODE_INVALID — число оставшихся попыток; текст сервера не показывается', () async {
      final api = respond((_) async => _error(400, 'CODE_INVALID', details: {'attempts_left': 2}));
      await expectLater(
        api.post('/auth/phone/verify-code', body: {}, auth: false),
        throwsA(isA<ApiException>().having((e) => e.message, 'message', 'Неверный код. Осталось попыток: 2')),
      );
    });

    test('RATE_LIMITED — отсчёт из Retry-After', () async {
      final api = respond((_) async => _error(429, 'RATE_LIMITED', headers: {'retry-after': '90'}));
      await expectLater(
        api.post('/auth/phone/request-code', body: {}, auth: false),
        throwsA(isA<ApiException>()
            .having((e) => e.message, 'message', 'Слишком много попыток. Повторите через 2 мин')
            .having((e) => e.retryAfter, 'retryAfter', const Duration(seconds: 90))),
      );
    });

    test('неизвестный код — общий текст', () async {
      final api = respond((_) async => _error(409, 'SOMETHING_NEW'));
      await expectLater(
        api.post('/x', body: {}, auth: false),
        throwsA(isA<ApiException>().having((e) => e.message, 'message', 'Что-то пошло не так. Повторите позже')),
      );
    });

    test('тайм-аут — OfflineException, POST не повторяется', () async {
      var calls = 0;
      final api = respond((_) async {
        calls++;
        await Future<void>.delayed(const Duration(milliseconds: 200));
        return _json(200, {});
      }, timeout: const Duration(milliseconds: 50));
      await expectLater(api.post('/auth/phone/request-code', body: {}, auth: false), throwsA(isA<OfflineException>()));
      expect(calls, 1);
    });

    test('запрос: /v1, JSON UTF-8, query без null', () async {
      late http.Request seen;
      final api = respond((r) async {
        seen = r;
        return http.Response('', 204);
      });
      expect(await api.post('/auth/phone/request-code', body: {'phone': '+375291234567'}, auth: false), isNull);
      expect(seen.url.toString(), 'http://api.test:8000/v1/auth/phone/request-code');
      expect(seen.headers['Content-Type'], 'application/json; charset=utf-8');
      expect(jsonDecode(seen.body), {'phone': '+375291234567'});
      expect(seen.headers.containsKey('Authorization'), isFalse);
    });
  });
}
