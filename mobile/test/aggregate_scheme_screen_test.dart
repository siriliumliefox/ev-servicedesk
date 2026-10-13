// Схема агрегатов на экране «Авто» (глава 19, ADR 0023): доступность (статус не только цветом, метки скринридера,
// тап-зоны), история агрегата (замена / работа), сбой загрузки ≠ «нет данных», модель без регламента ТО,
// таблица 5 тестовых авто согласована с порогами главы 5. Ширины 360–430 и крупный шрифт — layout_real_font_test.
import 'dart:convert';
import 'dart:io';

import 'package:flutter/material.dart';
import 'package:flutter/rendering.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';

import 'package:ev_servicedesk/data/api/api_client.dart';
import 'package:ev_servicedesk/data/api/token_store.dart';
import 'package:ev_servicedesk/data/http_repository.dart';
import 'package:ev_servicedesk/data/prototype_repository.dart';
import 'package:ev_servicedesk/main.dart';
import 'package:ev_servicedesk/screens/car/aggregate_scheme.dart';
import 'package:ev_servicedesk/ui/format.dart';
import 'package:ev_servicedesk/ui/status_badge.dart';

const _size = Size(390, 844);

/// Агрегаты на схеме у первого авто прототипа (Li Auto L7 — все шесть мест схемы).
const _codes = ['engine_oil', 'oil_filter', 'air_filter', 'ac_refrigerant', 'cabin_filter', 'gearbox_oil'];

Future<void> _pumpPrototype(WidgetTester tester) async {
  tester.view.physicalSize = _size;
  tester.view.devicePixelRatio = 1;
  addTearDown(tester.view.reset);
  await tester.pumpWidget(EvServiceDeskApp(repository: PrototypeRepository(latency: Duration.zero), signedIn: true));
  await tester.pumpAndSettle();
}

/// Backend с одним авто: ответ статусов агрегатов задаёт тест; запросы записываются.
Future<List<Uri>> _pumpHttp(WidgetTester tester, http.Response Function() statuses) async {
  tester.view.physicalSize = _size;
  tester.view.devicePixelRatio = 1;
  addTearDown(tester.view.reset);
  final requests = <Uri>[];
  http.Response json(Object body) =>
      http.Response.bytes(utf8.encode(jsonEncode(body)), 200, headers: {'content-type': 'application/json'});
  Map<String, Object?> list(List<Object?> items) => {
        'items': items,
        'meta': {'page': 1, 'page_size': 100, 'total_items': items.length, 'total_pages': items.isEmpty ? 0 : 1},
      };
  final client = MockClient((r) async {
    requests.add(r.url);
    return switch (r.url.path.replaceFirst('/v1', '')) {
      '/auth/refresh' => json({'access_token': 'a', 'refresh_token': 'r2', 'expires_in': 900}),
      '/vehicles' => json(list([
          {
            'id': 7,
            'vin': 'LLXL7000000190001',
            'mileage': 1000,
            'is_active': true,
            'vehicle_model_id': 3,
            'vehicle_model': {'brand': 'Li Auto', 'model': 'L7', 'trim': null},
            'current_firmware_version': null,
            'created_at': '2026-09-01T10:00:00Z',
          },
        ])),
      '/notifications' => json(list([])),
      '/vehicles/7/aggregate-statuses' => statuses(),
      _ => http.Response('{}', 404),
    };
  });
  final api = ApiClient(baseUrl: Uri.parse('http://api.test'), tokens: MemoryTokenStore('r1'), httpClient: client);
  await tester.pumpWidget(EvServiceDeskApp(repository: HttpClientRepository(api)));
  await tester.pumpAndSettle();
  return requests;
}

void main() {
  group('доступность схемы', () {
    for (final brightness in Brightness.values) {
      testWidgets('экран «Авто» по правилам Flutter: тап-зоны, подписи, контраст ($brightness)', (tester) async {
        tester.platformDispatcher.platformBrightnessTestValue = brightness;
        addTearDown(tester.platformDispatcher.clearPlatformBrightnessTestValue);
        final semantics = tester.ensureSemantics();
        await _pumpPrototype(tester);
        await expectLater(tester, meetsGuideline(androidTapTargetGuideline));
        await expectLater(tester, meetsGuideline(iOSTapTargetGuideline));
        await expectLater(tester, meetsGuideline(labeledTapTargetGuideline));
        await expectLater(tester, meetsGuideline(textContrastGuideline));
        semantics.dispose();
      });
    }

    testWidgets('скринридер читает «агрегат: статус словом» у каждой зоны, сверху вниз', (tester) async {
      final semantics = tester.ensureSemantics();
      await _pumpPrototype(tester);
      final labels = <String, String>{};
      for (final code in _codes) {
        final node = tester.getSemantics(find.byKey(Key('zone-$code')));
        expect(node.flagsCollection.isButton, isTrue, reason: code);
        labels[code] = node.label;
        final name = node.label.split(': ').first;
        final status = AggregateStatus.values.where((s) => node.label == '$name: ${s.label}');
        expect(status, hasLength(1), reason: '$code: «${node.label}» — статус словом');
      }

      // Порядок чтения — по месту на схеме (сверху вниз, в ряду слева направо), а не по порядку ответа API.
      final scheme = tester.getSemantics(find.bySemanticsLabel('Схема автомобиля'));
      final order = <String>[];
      void walk(SemanticsNode node) {
        if (labels.containsValue(node.label)) order.add(node.label);
        for (final child in node.debugListChildrenInOrder(DebugSemanticsDumpOrder.traversalOrder)) {
          walk(child);
        }
      }

      walk(scheme);
      final byPosition = [...aggregateSchemePositions.entries]..sort((a, b) {
          final dy = a.value.dy.compareTo(b.value.dy);
          return dy != 0 ? dy : a.value.dx.compareTo(b.value.dx);
        });
      expect(order, [for (final e in byPosition) labels[e.key]]);
      semantics.dispose();
    });

    test('у каждого статуса своя форма иконки и своё слово — не только цвет', () {
      expect(AggregateStatus.values.map((s) => s.icon).toSet(), hasLength(AggregateStatus.values.length));
      expect(AggregateStatus.values.map((s) => s.label).toSet(), hasLength(AggregateStatus.values.length));
    });
  });

  group('карточка агрегата', () {
    testWidgets('история агрегата: замены и работы по нему с меткой, без записей других агрегатов', (tester) async {
      await _pumpPrototype(tester);
      await tester.tap(find.byKey(const Key('zone-engine_oil')));
      await tester.pumpAndSettle();
      expect(find.text('История агрегата'), findsOneWidget);
      final sheet = find.byType(DraggableScrollableSheet);
      await tester.drag(sheet, const Offset(0, -400));
      await tester.pumpAndSettle();
      expect(find.text('Работа · ${formatKm(34100)} · Долив масла'), findsOneWidget);
      expect(find.text('Замена · ${formatKm(30800)} · Плановое ТО-2'), findsOneWidget);
      expect(find.text('Замена · ${formatKm(15900)}'), findsOneWidget);
      expect(find.byKey(const Key('record-1')), findsNothing, reason: 'масло редуктора — другой агрегат');
    });
  });

  testWidgets('шторка «Мои автомобили» с 6 авто на iPhone SE — без переполнения, последнее выбирается', (tester) async {
    tester.view.physicalSize = const Size(375, 667);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.reset);
    final repo = PrototypeRepository(latency: Duration.zero);
    for (final tail in ['000001', '000002', '000003', '000004']) {
      await tester.runAsync(() => repo.addVehicle('L6TZZZ1Z2RA$tail')); // таймер прототипа — вне подменного времени
    }
    await tester.pumpWidget(EvServiceDeskApp(repository: repo, signedIn: true));
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const Key('vehicle-switcher')));
    await tester.pumpAndSettle();
    expect(tester.takeException(), isNull);
    final last = find.textContaining('•••• 0004');
    await tester.scrollUntilVisible(last, 100,
        scrollable: find.descendant(of: find.byType(BottomSheet), matching: find.byType(Scrollable)));
    await tester.tap(last);
    await tester.pumpAndSettle();
    expect(find.descendant(of: find.byKey(const Key('vehicle-switcher')), matching: find.textContaining('•••• 0004')),
        findsOneWidget);
  });

  group('данные схемы', () {
    testWidgets('статусы читаются одной страницей максимального размера', (tester) async {
      final requests = await _pumpHttp(tester, () => http.Response('{"items": []}', 200));
      final statuses = requests.where((u) => u.path.endsWith('/aggregate-statuses'));
      expect(statuses.map((u) => u.queryParameters['page_size']), everyElement('100'));
    });

    testWidgets('сбой загрузки статусов — ошибка с «Повторить», а не серые зоны «Нет данных»', (tester) async {
      await _pumpHttp(
          tester,
          () => http.Response.bytes(
              utf8.encode(jsonEncode({
                'error': {'code': 'INTERNAL_ERROR', 'message': 'boom'},
              })),
              500,
              headers: {'content-type': 'application/json'}));
      expect(find.text('Не удалось загрузить данные'), findsOneWidget);
      expect(find.text('Повторить'), findsOneWidget);
      expect(find.byType(AggregateScheme), findsNothing);
      expect(find.text('Нет данных'), findsNothing);
    });

    testWidgets('у модели нет регламента ТО — контур и пояснение, не ошибка и не «в норме»', (tester) async {
      await _pumpHttp(
          tester,
          () => http.Response.bytes(utf8.encode(jsonEncode({'items': []})), 200,
              headers: {'content-type': 'application/json'}));
      expect(find.text('Регламент ТО для модели ещё не задан'), findsOneWidget);
      expect(find.byType(AggregateScheme), findsOneWidget);
      expect(find.text('Агрегаты'), findsNothing);
      expect(find.text('Все агрегаты в норме'), findsNothing);
      expect(find.text('Не удалось загрузить данные'), findsNothing);
    });
  });

  test('5 тестовых авто: ожидаемый статус каждого агрегата — по порогам главы 5 (70/100)', () {
    final table = jsonDecode(File('../docs/specs/scheme_test_vehicles.json').readAsStringSync()) as Map;
    final yellowFrom = table['thresholds']['yellow_from_percent'] as num;
    final redAbove = table['thresholds']['red_above_percent'] as num;
    final statuses = <String>{};
    for (final car in (table['vehicles'] as List).cast<Map>()) {
      for (final MapEntry(key: code, value: agg as Map) in (car['aggregates'] as Map).entries) {
        statuses.add(agg['status'] as String);
        final where = '${car['title']}: $code';
        if (!agg.containsKey('replaced_mileage')) {
          expect(agg['status'], 'unknown', reason: '$where — без замены статус не рассчитать');
          continue;
        }
        final p = agg['percentage'] as num?;
        if (p == null) continue; // интервал по времени — процент зависит от даты прогона
        final expected = p > redAbove ? 'red' : (p >= yellowFrom ? 'yellow' : 'green');
        expect(agg['status'], expected, reason: '$where: $p %');
      }
    }
    expect(statuses, {'green', 'yellow', 'red', 'unknown'}, reason: 'все статусы светофора');
  });
}
