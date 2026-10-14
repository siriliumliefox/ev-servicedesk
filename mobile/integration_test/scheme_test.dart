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

import 'support.dart';

const _phone = String.fromEnvironment('E2E_SCHEME_PHONE');
const _code = String.fromEnvironment('E2E_CODE');

/// Вход тестовым номером; seed только что запрашивал код этого номера — при паузе между запросами (429) ждём.
Future<void> _signIn(WidgetTester tester) async {
  await waitFor(tester, find.text('Получить код'));
  await tester.enterText(find.byKey(const Key('phone')), _phone.substring(4));
  final codeField = find.byKey(const Key('code'));
  for (var attempt = 0;; attempt++) {
    await tapLikeUser(tester, find.text('Получить код'));
    final shown = await waitForAny(tester, [codeField, find.textContaining('Слишком много попыток')]);
    if (shown == codeField) break;
    expect(attempt, 0, reason: 'пауза между запросами кода — один раз');
    await Future<void>.delayed(const Duration(seconds: 61));
  }
  await tester.enterText(find.byKey(const Key('code')), _code);
  await tapLikeUser(tester, find.descendant(of: find.byKey(const Key('consent')), matching: find.byType(Checkbox)));
  await tapLikeUser(tester, find.text('Войти'));
}

/// Схема нового авто: на медленном Android-эмуляторе статусы грузятся дольше, а экран после переключения может
/// остаться прокрученным вниз (схема вверху не построена) — ждём до 60 с, возвращая экран к началу.
Future<void> _waitForScheme(WidgetTester tester, Finder screen, Finder zone) async {
  final end = DateTime.now().add(const Duration(seconds: 60));
  while (zone.evaluate().isEmpty) {
    if (DateTime.now().isAfter(end)) throw TestFailure('Не дождались схемы: $zone');
    if (screen.evaluate().isNotEmpty) await tester.fling(screen, const Offset(0, 600), 2000);
    await tester.pump(const Duration(seconds: 1));
  }
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
    await waitFor(tester, find.byKey(const Key('open-vehicle-card')));

    final vehicles = await repo.vehicles();
    expect(vehicles, hasLength(5));
    var compared = 0;
    for (final (i, vehicle) in vehicles.indexed) {
      if (i > 0) {
        await tapLikeUser(tester, find.byKey(const Key('vehicle-switcher')));
        await waitFor(tester, find.textContaining(vehicle.vinMasked));
        await tapLikeUser(tester, find.textContaining(vehicle.vinMasked).last);
      }
      final statuses = await repo.aggregateStatuses(vehicle.id);
      final onScheme = [
        for (final s in statuses)
          if (aggregateSchemePositions.containsKey(s.aggregateTypeCode)) s
      ];
      // Экран «Авто» — ленивый ListView: схема вверху, строки списка строятся при прокрутке к ним.
      final screen = find.descendant(of: find.byType(RefreshIndicator), matching: find.byType(Scrollable)).first;
      await _waitForScheme(tester, screen, find.byKey(Key('zone-${onScheme.first.aggregateTypeCode}')));

      for (final s in onScheme) {
        final expected = '${s.aggregateTypeName}: ${s.status.label}';
        final zone = find.byKey(Key('zone-${s.aggregateTypeCode}'));
        await tester.scrollUntilVisible(zone, -150, scrollable: screen);
        await tester.pumpAndSettle();
        expect(tester.getSemantics(zone).label, expected, reason: vehicle.vinMasked);
        expect(zone.hitTestable(), findsOneWidget, reason: expected);
        await tester.tap(zone);
        await waitFor(tester, find.byType(BottomSheet));
        await tester.pumpAndSettle();
        final sheet = find.byType(BottomSheet);
        expect(find.descendant(of: sheet, matching: find.text(s.aggregateTypeName)), findsWidgets, reason: expected);
        expect(find.descendant(of: sheet, matching: find.text(s.status.label)), findsOneWidget,
            reason: '$expected — в карточке агрегата');
        await tester.tapAt(const Offset(10, 60)); // затемнение над шитом
        await tester.pumpAndSettle();
        compared++;
      }

      for (final s in statuses) {
        final row = find.byKey(Key('row-${s.aggregateTypeCode}'));
        await tester.scrollUntilVisible(row, 150, scrollable: screen);
        await tester.pumpAndSettle();
        expect(find.descendant(of: row, matching: find.text(s.status.label)), findsOneWidget,
            reason: '${s.aggregateTypeName}: ${s.status.label} — в списке');
      }
      await tester.scrollUntilVisible(find.byKey(const Key('open-vehicle-card')), -300, scrollable: screen);
      await tester.pumpAndSettle();
      debugPrint('PASS  ${vehicle.vehicleModel.title} ${vehicle.vinMasked}: '
          '${statuses.map((s) => '${s.aggregateTypeCode} ${s.status.name}').join(', ')}');
    }
    debugPrint('Схема совпала с backend: $compared зон из $compared');
    expect(compared, 24, reason: 'все зоны 5 авто: 6 + 6 + 6 + 3 + 3');
    semantics.dispose();
  });
}
