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
/// настоящая и закрывает кнопки внизу экрана).
Future<void> tapLikeUser(WidgetTester tester, Finder finder) async {
  FocusManager.instance.primaryFocus?.unfocus();
  await tester.pump(const Duration(milliseconds: 500));
  await tester.ensureVisible(finder);
  await tester.pump(const Duration(milliseconds: 300));
  await tester.tap(finder);
}
