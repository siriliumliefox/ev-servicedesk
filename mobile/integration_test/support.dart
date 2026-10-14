// Общие шаги UI E2E (главы 18–19): приложение на симуляторе ходит в настоящий стек backend.
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

/// Ждать, пока появится хотя бы один из виджетов: запросы идут к настоящему серверу, pumpAndSettle сеть не ждёт.
Future<Finder> waitForAny(WidgetTester tester, List<Finder> finders,
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

Future<void> waitFor(WidgetTester tester, Finder finder) => waitForAny(tester, [finder]);

/// Тап как у пользователя: клавиатура скрыта, элемент прокручен в видимую область (на симуляторе клавиатура
/// настоящая и закрывает кнопки внизу экрана). Элемент должен быть построен — в длинном списке сначала `revealIn`.
Future<void> tapLikeUser(WidgetTester tester, Finder finder) async {
  FocusManager.instance.primaryFocus?.unfocus();
  await tester.pump(const Duration(milliseconds: 500));
  await tester.ensureVisible(finder);
  await tester.pump(const Duration(milliseconds: 300));
  await tester.tap(finder);
}

/// Запросить SMS-код номером, которому seed только что запрашивал код: сервер отклоняет повтор раньше 60 с (429,
/// «Слишком много попыток») — один раз подождать и повторить. Ждём ответ сервера, а не таймаут: на медленном
/// эмуляторе запрос идёт дольше, и кнопка в это время показывает индикатор вместо текста.
Future<void> requestCode(WidgetTester tester, String phone) async {
  await waitFor(tester, find.text('Получить код'));
  await tester.enterText(find.byKey(const Key('phone')), phone.substring(4));
  final codeField = find.byKey(const Key('code'));
  for (var attempt = 0;; attempt++) {
    await tapLikeUser(tester, find.text('Получить код'));
    final shown = await waitForAny(tester, [codeField, find.textContaining('Слишком много попыток')]);
    if (shown == codeField) return;
    expect(attempt, 0, reason: 'пауза между запросами кода — один раз');
    await Future<void>.delayed(const Duration(seconds: 61));
  }
}

/// Прокрутить список экрана `screen`, пока не построится `finder`: элемент ленивого ListView за его кэшем ещё не
/// создан (форма длиннее экрана — низкий экран Android-эмулятора, глава 23).
Future<void> revealIn(WidgetTester tester, Finder screen, Finder finder) async {
  if (finder.evaluate().isNotEmpty) return;
  final list = find.descendant(of: screen, matching: find.byType(Scrollable)).first;
  await tester.scrollUntilVisible(finder, 200, scrollable: list);
}
