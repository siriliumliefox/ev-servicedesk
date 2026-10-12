// UI E2E схемы агрегатов (глава 19, ADR 0023 п. 7): 5 тестовых авто (backend/scripts/seed_scheme_vehicles.py) на
// симуляторе против стека backend. У каждого авто метка каждой зоны и строка списка совпадают со статусом из API,
// зона нажимается и открывает карточку агрегата с тем же статусом. Таблицу против API сверяет seed и test_api_e2e.
// Запуск: mobile/scripts/e2e_ui.sh [симулятор] — seed + --dart-define API_BASE_URL, E2E_SCHEME_PHONE, E2E_CODE.
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:integration_test/integration_test.dart';

import 'package:ev_servicedesk/data/api/token_store.dart';
import 'package:ev_servicedesk/main.dart';
import 'package:ev_servicedesk/screens/car/aggregate_scheme.dart';
import 'package:ev_servicedesk/ui/status_badge.dart';

const _phone = String.fromEnvironment('E2E_SCHEME_PHONE');
const _code = String.fromEnvironment('E2E_CODE');

/// Ждать, пока появится хотя бы один из виджетов: запросы идут к настоящему серверу, pumpAndSettle сеть не ждёт.
Future<Finder> _waitForAny(WidgetTester tester, List<Finder> finders,
    {Duration timeout = const Duration(seconds: 30)}) async {
  final end = DateTime.now().add(timeout);
  while (DateTime.now().isBefore(end)) {
    await tester.pump(const Duration(milliseconds: 200));
    for (final f in finders) {
      if (f.evaluate().isNotEmpty) return f;
    }
  }
  throw TestFailure('Не дождались: $finders');
}

Future<void> _waitFor(WidgetTester tester, Finder finder) => _waitForAny(tester, [finder]);

Future<void> _tap(WidgetTester tester, Finder finder) async {
  FocusManager.instance.primaryFocus?.unfocus();
  await tester.pump(const Duration(milliseconds: 500));
  await tester.ensureVisible(finder);
  await tester.pump(const Duration(milliseconds: 300));
  await tester.tap(finder);
}

/// Вход тестовым номером; seed только что запрашивал код этого номера — при паузе между запросами (429) ждём.
Future<void> _signIn(WidgetTester tester) async {
  await _waitFor(tester, find.text('Получить код'));
  await tester.enterText(find.byKey(const Key('phone')), _phone.substring(4));
  final codeField = find.byKey(const Key('code'));
  for (var attempt = 0;; attempt++) {
    await _tap(tester, find.text('Получить код'));
    final shown = await _waitForAny(tester, [codeField, find.textContaining('Слишком много попыток')]);
    if (shown == codeField) break;
    expect(attempt, 0, reason: 'пауза между запросами кода — один раз');
    await Future<void>.delayed(const Duration(seconds: 61));
  }
  await tester.enterText(find.byKey(const Key('code')), _code);
  await _tap(tester, find.descendant(of: find.byKey(const Key('consent')), matching: find.byType(Checkbox)));
  await _tap(tester, find.text('Войти'));
}

void main() {
  IntegrationTestWidgetsFlutterBinding.ensureInitialized();
  WidgetController.hitTestWarningShouldBeFatal = true;

  testWidgets('5 тестовых авто: зоны и список схемы совпадают со статусами backend', (tester) async {
    expect(apiBaseUrl, isNotEmpty, reason: 'нужен --dart-define=API_BASE_URL');
    expect(_phone, startsWith('+375'), reason: 'нужен --dart-define=E2E_SCHEME_PHONE');
    final semantics = tester.ensureSemantics();
    await (await SecureTokenStore.open()).clear();
    final repo = await createRepository();
    await tester.pumpWidget(EvServiceDeskApp(repository: repo));
    await _signIn(tester);
    await _waitFor(tester, find.byKey(const Key('open-vehicle-card')));

    final vehicles = await repo.vehicles();
    expect(vehicles, hasLength(5));
    var compared = 0;
    for (final (i, vehicle) in vehicles.indexed) {
      if (i > 0) {
        await _tap(tester, find.byKey(const Key('vehicle-switcher')));
        await _waitFor(tester, find.textContaining(vehicle.vinMasked));
        await _tap(tester, find.textContaining(vehicle.vinMasked).last);
      }
      final statuses = await repo.aggregateStatuses(vehicle.id);
      await _waitFor(tester, find.byKey(Key('row-${statuses.first.aggregateTypeCode}')));
      for (final s in statuses) {
        final expected = '${s.aggregateTypeName}: ${s.status.label}';
        final row = find.byKey(Key('row-${s.aggregateTypeCode}'));
        await tester.ensureVisible(row);
        await tester.pumpAndSettle();
        expect(find.descendant(of: row, matching: find.text(s.status.label)), findsOneWidget, reason: expected);
        if (!aggregateSchemePositions.containsKey(s.aggregateTypeCode)) continue;
        final zone = find.byKey(Key('zone-${s.aggregateTypeCode}'));
        await tester.ensureVisible(zone);
        await tester.pumpAndSettle();
        expect(tester.getSemantics(zone).label, expected, reason: vehicle.vinMasked);
        expect(zone.hitTestable(), findsOneWidget, reason: expected);
        await tester.tap(zone);
        await _waitFor(tester, find.byType(BottomSheet));
        await tester.pumpAndSettle();
        expect(
          find.descendant(of: find.byType(BottomSheet), matching: find.byType(StatusBadge)),
          findsOneWidget,
        );
        expect(find.descendant(of: find.byType(BottomSheet), matching: find.text(s.status.label)), findsWidgets,
            reason: '$expected — в карточке агрегата');
        await tester.tapAt(const Offset(10, 60));
        await tester.pumpAndSettle();
        compared++;
      }
      debugPrint('PASS  ${vehicle.vehicleModel.title} ${vehicle.vinMasked}: '
          '${statuses.map((s) => '${s.aggregateTypeCode} ${s.status.name}').join(', ')}');
    }
    debugPrint('Схема совпала с backend: $compared зон из $compared');
    expect(compared, 24, reason: 'все зоны 5 авто: 6 + 6 + 6 + 3 + 3');
    semantics.dispose();
  });
}
