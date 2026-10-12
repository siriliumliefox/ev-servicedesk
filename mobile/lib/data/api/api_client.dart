// HTTP-транспорт клиента (ADR 0022): JSON, тайм-аут, ошибки контракта, сессия и обновление токенов.
import 'dart:async';
import 'dart:convert';
import 'dart:io' show IOException;

import 'package:http/http.dart' as http;

import '../repository.dart';
import 'error_text.dart';
import 'token_store.dart';

class ApiClient {
  ApiClient({
    required this.baseUrl,
    required this.tokens,
    http.Client? httpClient,
    this.timeout = const Duration(seconds: 20),
  }) : _http = httpClient ?? http.Client();

  /// Адрес backend без /v1, например http://192.168.1.10:8000.
  final Uri baseUrl;
  final TokenStore tokens;
  final Duration timeout;
  final http.Client _http;

  // sync: подписчик (AppState) узнаёт о завершении сессии до того, как запрос вернёт ошибку экрану.
  final _sessionEnded = StreamController<void>.broadcast(sync: true);

  /// Сессия завершена сервером (refresh отклонён) — приложение возвращается к онбордингу.
  Stream<void> get sessionEnded => _sessionEnded.stream;

  String? _access;
  Future<String>? _refreshing;

  Future<bool> hasSession() async => await tokens.read() != null;

  /// Пара токенов из verify-code: refresh — в хранилище до того, как access станет доступен запросам.
  Future<void> startSession(Map<String, Object?> authTokens) async {
    await tokens.write(authTokens['refresh_token']! as String);
    _access = authTokens['access_token']! as String;
  }

  Future<void> endSession({bool notify = false}) async {
    _access = null;
    await tokens.clear();
    if (notify) _sessionEnded.add(null);
  }

  Future<Object?> get(String path, {Map<String, Object?>? query}) => send('GET', path, query: query);

  Future<Object?> post(String path, {Object? body, bool auth = true}) => send('POST', path, body: body, auth: auth);

  Future<Object?> patch(String path, {Object? body}) => send('PATCH', path, body: body);

  Future<Object?> delete(String path) => send('DELETE', path);

  /// Запрос с авторизацией: на 401 — обновление токена и один повтор; повторный 401 завершает сессию.
  Future<Object?> send(String method, String path,
      {Object? body, Map<String, Object?>? query, bool auth = true}) async {
    if (!auth) return _decode(await _raw(method, path, body: body, query: query));
    var access = _access ?? await _refresh(null);
    var response = await _raw(method, path, body: body, query: query, access: access);
    if (response.statusCode == 401) {
      access = await _refresh(access);
      response = await _raw(method, path, body: body, query: query, access: access);
      if (response.statusCode == 401) {
        await endSession(notify: true);
        throw const ApiException('UNAUTHORIZED', sessionEndedText);
      }
    }
    return _decode(response);
  }

  /// Один запрос refresh на все параллельные 401 (ADR 0022 п. 6): если access уже обновил другой запрос — берём его.
  Future<String> _refresh(String? stale) {
    final current = _access;
    if (current != null && current != stale) return Future.value(current);
    return _refreshing ??= _doRefresh().whenComplete(() => _refreshing = null);
  }

  /// Не повторяется автоматически: повтор уже ротированного токена backend считает кражей и завершает все сессии.
  /// Ошибка сети или 5xx сессию не завершает — пользователь повторит, когда связь вернётся.
  Future<String> _doRefresh() async {
    final refresh = await tokens.read();
    if (refresh == null) {
      await endSession(notify: true);
      throw const ApiException('UNAUTHORIZED', sessionEndedText);
    }
    final response = await _raw('POST', '/auth/refresh', body: {'refresh_token': refresh});
    if (response.statusCode == 200) {
      final pair = _decode(response)! as Map<String, Object?>;
      await startSession(pair);
      return _access!;
    }
    if (response.statusCode >= 400 && response.statusCode < 500) {
      await endSession(notify: true);
      throw const ApiException('UNAUTHORIZED', sessionEndedText);
    }
    throw _error(response);
  }

  Future<http.Response> _raw(
    String method,
    String path, {
    Object? body,
    Map<String, Object?>? query,
    String? access,
  }) async {
    final params = {
      for (final e in (query ?? const <String, Object?>{}).entries)
        if (e.value != null) e.key: '${e.value}',
    };
    final uri = baseUrl.replace(path: '${baseUrl.path}/v1$path', queryParameters: params.isEmpty ? null : params);
    final request = http.Request(method, uri)
      ..headers['Accept'] = 'application/json'
      ..followRedirects = false;
    if (access != null) request.headers['Authorization'] = 'Bearer $access';
    if (body != null) {
      request.headers['Content-Type'] = 'application/json; charset=utf-8';
      request.bodyBytes = utf8.encode(jsonEncode(body));
    }
    try {
      return await http.Response.fromStream(await _http.send(request).timeout(timeout)).timeout(timeout);
    } on TimeoutException {
      throw const OfflineException();
    } on IOException {
      throw const OfflineException(); // сокет, DNS, TLS
    } on http.ClientException {
      throw const OfflineException();
    }
  }

  Object? _decode(http.Response response) {
    if (response.statusCode < 200 || response.statusCode >= 300) throw _error(response);
    if (response.bodyBytes.isEmpty) return null;
    return jsonDecode(utf8.decode(response.bodyBytes));
  }

  static ApiException _error(http.Response response) {
    var code = response.statusCode >= 500 ? 'SERVER_ERROR' : 'HTTP_${response.statusCode}';
    Map<String, Object?>? details;
    try {
      final error =
          (jsonDecode(utf8.decode(response.bodyBytes)) as Map<String, Object?>)['error']! as Map<String, Object?>;
      code = error['code']! as String;
      details = error['details'] as Map<String, Object?>?;
    } on Object {
      // Ответ не по контракту (прокси, HTML) — общий текст по статусу.
    }
    final retryAfter = int.tryParse(response.headers['retry-after'] ?? '');
    return ApiException(
      code,
      errorText(code, details: details, retryAfterSeconds: retryAfter),
      retryAfter: retryAfter == null ? null : Duration(seconds: retryAfter),
    );
  }
}
