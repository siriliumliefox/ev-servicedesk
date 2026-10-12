// Плохое соединение (глава 18, ADR 0022 п. 3, 10): медленные ответы, обрыв и тайм-аут на реальном HTTP-слое
// (HttpClientRepository + ApiClient, сервер — MockClient). Индикатор загрузки, понятная ошибка, «Повторить»,
// сессия не завершается из-за сети; завершённая сервером сессия — экран входа с сообщением.
import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';

import 'package:ev_servicedesk/data/api/api_client.dart';
import 'package:ev_servicedesk/data/api/token_store.dart';
import 'package:ev_servicedesk/data/http_repository.dart';
import 'package:ev_servicedesk/main.dart';
import 'package:ev_servicedesk/ui/format.dart';

enum _Net { ok, down }

/// Backend с одним авто клиента; сеть переключается, ответы можно задержать (2G/Edge — секунды).
class _Backend {
  _Net net = _Net.ok;
  Duration latency = Duration.zero;
  bool rejectRefresh = false;
  int mileage = 41250;
  int calls = 0;
  final paths = <String>[];

  static http.Response _json(int status, Object body) =>
      http.Response.bytes(utf8.encode(jsonEncode(body)), status, headers: {'content-type': 'application/json'});

  static Map<String, Object?> _list(List<Object?> items) => {
        'items': items,
        'meta': {'page': 1, 'page_size': 20, 'total_items': items.length, 'total_pages': items.isEmpty ? 0 : 1},
      };

  Map<String, Object?> get _vehicle => {
        'id': 7,
        'vin': 'L6TZ001AB12345678',
        'mileage': mileage,
        'is_active': true,
        'vehicle_model_id': 2,
        'vehicle_model': {'brand': 'Zeekr', 'model': '001', 'trim': null},
        'current_firmware_version': '5.1.0',
        'created_at': '2026-09-01T10:00:00Z',
      };

  Future<http.Response> handle(http.Request r) async {
    calls++;
    paths.add('${r.method} ${r.url.path}');
    if (latency > Duration.zero) await Future<void>.delayed(latency);
    if (net == _Net.down) throw http.ClientException('Network is unreachable');
    final path = r.url.path.replaceFirst('/v1', '');
    if (path == '/auth/refresh') {
      if (rejectRefresh) {
        return _json(401, {
          'error': {'code': 'UNAUTHORIZED', 'message': 'refresh revoked'},
        });
      }
      return _json(200, {'access_token': 'access', 'refresh_token': 'refresh-next', 'expires_in': 900});
    }
    return switch (path) {
      '/vehicles' => _json(200, _list([_vehicle])),
      '/notifications' => _json(200, _list([])),
      '/vehicles/7/aggregate-statuses' => _json(200, {
          'items': [
            {'aggregate_type_code': 'cabin_filter', 'aggregate_type_name': 'Салонный фильтр', 'status': 'unknown'},
          ],
        }),
      '/vehicles/7/maintenance-records' => _json(
          200,
          _list([
            {
              'id': 1,
              'aggregate_type_code': 'cabin_filter',
              'performed_at': '2026-05-14',
              'mileage_at_service': 30100,
              'kind': 'replacement',
            },
          ])),
      '/vehicles/7/mileage' => _mileage(r),
      _ => _json(404, {
          'error': {'code': 'NOT_FOUND', 'message': path},
        }),
    };
  }

  http.Response _mileage(http.Request r) {
    final value = (jsonDecode(r.body) as Map)['mileage'] as int;
    if (value < mileage) {
      return _json(409, {
        'error': {'code': 'MILEAGE_DECREASE', 'message': 'decrease'},
      });
    }
    mileage = value;
    return _json(200, _vehicle);
  }
}

Future<_Backend> _start(WidgetTester tester,
    {String? savedRefresh = 'refresh-1', void Function(_Backend)? setup}) async {
  tester.view.physicalSize = const Size(390, 844);
  tester.view.devicePixelRatio = 1;
  addTearDown(tester.view.reset);
  final backend = _Backend();
  setup?.call(backend);
  final api = ApiClient(
    baseUrl: Uri.parse('http://api.test:8000'),
    tokens: MemoryTokenStore(savedRefresh),
    httpClient: MockClient(backend.handle),
  );
  await tester.pumpWidget(EvServiceDeskApp(repository: HttpClientRepository(api)));
  return backend;
}

void main() {
  testWidgets('медленная сеть: индикатор загрузки, затем данные; сессия восстановлена без SMS', (tester) async {
    await _start(tester, setup: (b) => b.latency = const Duration(seconds: 3));
    await tester.pump();
    expect(find.byType(CircularProgressIndicator), findsOneWidget);
    expect(find.text('Получить код'), findsNothing, reason: 'сохранённая сессия — не онбординг');

    await tester.pump(const Duration(seconds: 3)); // refresh
    await tester.pump(const Duration(seconds: 3)); // список авто
    expect(find.byType(CircularProgressIndicator), findsWidgets, reason: 'статусы агрегатов ещё грузятся');
    await tester.pump(const Duration(seconds: 3));
    await tester.pumpAndSettle(const Duration(seconds: 1));
    expect(find.text('Салонный фильтр'), findsWidgets);
  });

  testWidgets('нет сети при запуске: главный экран «Нет подключения», «Повторить» после появления сети',
      (tester) async {
    final backend = await _start(tester, setup: (b) => b.net = _Net.down);
    await tester.pumpAndSettle();
    expect(find.text('Нет подключения к интернету'), findsOneWidget);
    expect(find.text('Получить код'), findsNothing, reason: 'потеря связи сессию не завершает');

    backend.net = _Net.ok;
    await tester.tap(find.text('Повторить'));
    await tester.pumpAndSettle();
    expect(find.text('Нет подключения к интернету'), findsNothing);
    expect(find.text('Салонный фильтр'), findsWidgets);
  });

  testWidgets('тайм-аут (20 с): ошибка вместо вечной загрузки', (tester) async {
    await _start(tester, setup: (b) => b.latency = const Duration(seconds: 60));
    await tester.pump();
    await tester.pump(const Duration(seconds: 21));
    await tester.pump();
    expect(find.text('Нет подключения к интернету'), findsOneWidget);
    await tester.pump(const Duration(seconds: 60)); // завершить отложенный ответ MockClient
  });

  testWidgets('сервер отклонил refresh: экран входа с сообщением «Сессия завершена»', (tester) async {
    await _start(tester, setup: (b) => b.rejectRefresh = true);
    await tester.pumpAndSettle();
    expect(find.text('Получить код'), findsOneWidget);
    expect(find.text('Сессия завершена — войдите снова'), findsOneWidget);
  });

  testWidgets('без сохранённой сессии — онбординг без запросов к серверу', (tester) async {
    final backend = await _start(tester, savedRefresh: null);
    await tester.pumpAndSettle();
    expect(find.text('Получить код'), findsOneWidget);
    expect(backend.calls, 0);
  });

  testWidgets('карточка авто: история ТО, пробег; обрыв при сохранении — ошибка в диалоге, без повтора', (
    tester,
  ) async {
    final backend = await _start(tester);
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const Key('open-vehicle-card')));
    await tester.pumpAndSettle();
    expect(find.text('14 мая 2026'), findsOneWidget);
    expect(find.text('Показать ещё'), findsNothing, reason: 'одна страница');

    await tester.tap(find.byKey(const Key('update-mileage')));
    await tester.pumpAndSettle();
    await tester.enterText(find.byKey(const Key('mileage-input')), '40000');
    await tester.tap(find.byKey(const Key('save-mileage')));
    await tester.pumpAndSettle();
    expect(find.textContaining('Не меньше текущего'), findsOneWidget, reason: 'проверка до запроса');

    backend.net = _Net.down;
    final before = backend.paths.where((p) => p == 'PATCH /v1/vehicles/7/mileage').length;
    await tester.enterText(find.byKey(const Key('mileage-input')), '42000');
    await tester.tap(find.byKey(const Key('save-mileage')));
    await tester.pumpAndSettle();
    expect(find.text('Нет подключения к интернету'), findsOneWidget);
    expect(backend.paths.where((p) => p == 'PATCH /v1/vehicles/7/mileage').length, before + 1);

    backend.net = _Net.ok;
    await tester.tap(find.byKey(const Key('save-mileage')));
    await tester.pumpAndSettle();
    expect(find.text('Пробег обновлён'), findsOneWidget);
    expect(find.byKey(const Key('mileage')), findsOneWidget);
    expect(tester.widget<Text>(find.byKey(const Key('mileage'))).data, formatKm(42000));
  });
}
