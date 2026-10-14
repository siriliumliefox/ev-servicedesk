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
/// настоящая и закрывает кнопки внизу экрана). Элемент длинного списка за кэшем ListView ещё не построен (низкий
/// экран Android-эмулятора, глава 23) — список прокручивается, пока он не появится.
Future<void> tapLikeUser(WidgetTester tester, Finder finder) async {
  FocusManager.instance.primaryFocus?.unfocus();
  await tester.pump(const Duration(milliseconds: 500));
  if (finder.evaluate().isEmpty) {
    final list = find.byWidgetPredicate((w) => w is Scrollable && axisDirectionToAxis(w.axisDirection) == Axis.vertical);
    await tester.scrollUntilVisible(finder, 200, scrollable: list.first);
  }
  await tester.ensureVisible(finder);
  await tester.pump(const Duration(milliseconds: 300));
  await tester.tap(finder);
}

/// Запросить SMS-код. Если номер только что запрашивал код (seed стека), сервер отклоняет повтор раньше 60 с
/// (429) — подождать и повторить, пока не появится поле кода.
Future<void> requestCode(WidgetTester tester, String phone) async {
  await tester.enterText(find.byKey(const Key('phone')), phone.substring(4));
  final end = DateTime.now().add(const Duration(seconds: 100));
  while (true) {
    await tapLikeUser(tester, find.text('Получить код'));
    try {
      await waitForAny(tester, [find.byKey(const Key('code'))], timeout: const Duration(seconds: 10));
      return;
    } on TestFailure {
      if (DateTime.now().isAfter(end)) rethrow;
      await Future<void>.delayed(const Duration(seconds: 15));
    }
  }
}
