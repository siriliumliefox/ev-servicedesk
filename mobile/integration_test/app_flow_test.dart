// UI E2E (глава 18, ADR 0022 п. 2): приложение на симуляторе против локального стека backend.
// Сценарий чек-листа: регистрация → добавление авто → просмотр карточки; затем пробег, перезапуск без SMS и выход.
// Запуск: mobile/scripts/e2e_ui.sh (поднимает стек и передаёт API_BASE_URL, E2E_PHONE, E2E_CODE через --dart-define).
import 'dart:math';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:integration_test/integration_test.dart';

import 'package:ev_servicedesk/data/api/token_store.dart';
import 'package:ev_servicedesk/main.dart';
import 'package:ev_servicedesk/ui/format.dart';

const _phone = String.fromEnvironment('E2E_PHONE');
const _code = String.fromEnvironment('E2E_CODE');

/// Ждать появления виджета: запросы идут к настоящему серверу, pumpAndSettle не ждёт сеть.
Future<void> _waitFor(WidgetTester tester, Finder finder, {Duration timeout = const Duration(seconds: 30)}) async {
  final end = DateTime.now().add(timeout);
  while (DateTime.now().isBefore(end)) {
    await tester.pump(const Duration(milliseconds: 200));
    if (finder.evaluate().isNotEmpty) return;
  }
  throw TestFailure('Не дождались: $finder');
}

/// Тап как у пользователя: клавиатура скрыта, элемент прокручен в видимую область (на симуляторе клавиатура
/// настоящая и закрывает кнопки внизу экрана).
Future<void> _tap(WidgetTester tester, Finder finder) async {
  FocusManager.instance.primaryFocus?.unfocus();
  await tester.pump(const Duration(milliseconds: 500));
  await tester.ensureVisible(finder);
  await tester.pump(const Duration(milliseconds: 300));
  await tester.tap(finder);
}

Future<void> _launch(WidgetTester tester) async {
  await tester.pumpWidget(EvServiceDeskApp(repository: await createRepository()));
}

void main() {
  IntegrationTestWidgetsFlutterBinding.ensureInitialized();
  WidgetController.hitTestWarningShouldBeFatal = true; // промах тапа — ошибка, а не тихое ожидание

  testWidgets('регистрация → авто по VIN → карточка → перезапуск без SMS → выход', (tester) async {
    expect(apiBaseUrl, isNotEmpty, reason: 'нужен --dart-define=API_BASE_URL');
    expect(_phone, startsWith('+375'), reason: 'нужен --dart-define=E2E_PHONE');
    await (await SecureTokenStore.open()).clear(); // сессия прошлого прогона

    // Регистрация по SMS-коду с согласием на обработку ПД.
    await _launch(tester);
    await _waitFor(tester, find.text('Получить код'));
    await tester.enterText(find.byKey(const Key('phone')), _phone.substring(4));
    await _tap(tester, find.text('Получить код'));
    await _waitFor(tester, find.byKey(const Key('code')));
    await tester.enterText(find.byKey(const Key('code')), _code);
    // По галочке, а не по центру строки: там ссылка «Политика обработки ПД».
    await _tap(tester, find.descendant(of: find.byKey(const Key('consent')), matching: find.byType(Checkbox)));
    await _tap(tester, find.text('Войти'));

    // Новый клиент: добавление авто по VIN (мок-декодер распознаёт Zeekr 001).
    await _waitFor(tester, find.byKey(const Key('vin')));
    final random = Random();
    final vin = 'L6TZ001${List.generate(10, (_) => random.nextInt(10)).join()}';
    await tester.enterText(find.byKey(const Key('vin')), vin);
    await _tap(tester, find.text('Добавить'));

    // Главный экран и карточка авто.
    await _waitFor(tester, find.byKey(const Key('open-vehicle-card')));
    expect(find.textContaining('Zeekr 001'), findsWidgets);
    await _tap(tester, find.byKey(const Key('open-vehicle-card')));
    await _waitFor(tester, find.text('Работ пока не было'));
    expect(find.text('•••• ${vin.substring(13)}'), findsWidgets);

    await _tap(tester, find.byKey(const Key('update-mileage')));
    await _waitFor(tester, find.byKey(const Key('mileage-input')));
    await tester.enterText(find.byKey(const Key('mileage-input')), '1500');
    await _tap(tester, find.byKey(const Key('save-mileage')));
    await _waitFor(tester, find.text('Пробег обновлён'));

    // Перезапуск: вход по сохранённой сессии, без SMS-кода.
    await tester.pumpWidget(const SizedBox.shrink());
    await _launch(tester);
    await _waitFor(tester, find.byKey(const Key('open-vehicle-card')));
    expect(find.text('Получить код'), findsNothing);

    // Выход с устройства — экран входа.
    await _tap(tester, find.byKey(const Key('open-profile')));
    await _waitFor(tester, find.text(formatPhone(_phone)));
    await _tap(tester, find.byKey(const Key('sign-out')));
    await _waitFor(tester, find.text('Получить код'));
  });
}
