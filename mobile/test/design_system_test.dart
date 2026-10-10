// Дизайн-система в Flutter (Глава 6, Issue #34): тап-зоны ≥ 44×44, статусы «не только цветом»,
// тема на токенах. Контраст и сетка проверяются по design/tokens.json — npm run test:tokens.
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:ev_servicedesk/theme/app_theme.dart';
import 'package:ev_servicedesk/ui/bottom_nav.dart';
import 'package:ev_servicedesk/ui/status_badge.dart';

Widget _host(Widget child, {Brightness brightness = Brightness.light}) => MaterialApp(
      theme: evTheme(brightness),
      home: Scaffold(body: Center(child: child)),
    );

void expectTapTarget(WidgetTester tester, Finder finder) {
  final size = tester.getSize(finder);
  expect(size.width, greaterThanOrEqualTo(EvSize.tapTargetMin), reason: 'ширина $size');
  expect(size.height, greaterThanOrEqualTo(EvSize.tapTargetMin), reason: 'высота $size');
}

void main() {
  test('минимальная тап-зона из токенов ≥ 44', () {
    expect(EvSize.tapTargetMin, greaterThanOrEqualTo(44));
  });

  for (final brightness in Brightness.values) {
    test('тема $brightness содержит EvColors из токенов', () {
      final theme = evTheme(brightness);
      final colors = theme.extension<EvColors>()!;
      expect(colors, brightness == Brightness.dark ? evColorsDark : evColorsLight);
      expect(theme.colorScheme.primary, colors.primary);
      expect(theme.scaffoldBackgroundColor, colors.canvas);
    });
  }

  testWidgets('кнопки: высота control-mobile, тап-зона ≥ 44×44', (tester) async {
    await tester.pumpWidget(_host(Column(mainAxisSize: MainAxisSize.min, children: [
      FilledButton(onPressed: () {}, child: const Text('OK')),
      OutlinedButton(onPressed: () {}, child: const Text('Да')),
      TextButton(onPressed: () {}, child: const Text('Ок')),
      IconButton(onPressed: () {}, icon: const Icon(Icons.close)),
    ])));
    for (final type in [FilledButton, OutlinedButton, TextButton, IconButton]) {
      expectTapTarget(tester, find.byType(type));
    }
    expect(tester.getSize(find.byType(FilledButton)).height, EvSize.controlMobile);
  });

  testWidgets('нижняя навигация: высота bottom-nav, каждый пункт ≥ 44×44', (tester) async {
    await tester.pumpWidget(MaterialApp(
      theme: evTheme(Brightness.light),
      home: Scaffold(bottomNavigationBar: EvBottomNav(current: EvSection.car, onSelected: (_) {})),
    ));
    expect(tester.getSize(find.byType(NavigationBar)).height, EvSize.bottomNav);
    for (final s in EvSection.values) {
      expect(find.text(s.label), findsOneWidget);
      expectTapTarget(tester, find.widgetWithText(NavigationDestination, s.label));
    }
  });

  testWidgets('нижняя навигация переключает раздел', (tester) async {
    EvSection? selected;
    await tester.pumpWidget(MaterialApp(
      theme: evTheme(Brightness.light),
      home: Scaffold(bottomNavigationBar: EvBottomNav(current: EvSection.car, onSelected: (s) => selected = s)),
    ));
    await tester.tap(find.text('Поддержка'));
    expect(selected, EvSection.support);
  });

  for (final brightness in Brightness.values) {
    testWidgets('бейдж статуса ($brightness): подпись + своя иконка + цвета токенов', (tester) async {
      await tester.pumpWidget(_host(
        Column(mainAxisSize: MainAxisSize.min, children: [
          for (final s in AggregateStatus.values) StatusBadge(status: s),
        ]),
        brightness: brightness,
      ));
      final colors = brightness == Brightness.dark ? evColorsDark : evColorsLight;
      for (final s in AggregateStatus.values) {
        expect(find.text(s.label), findsOneWidget);
        final icon = tester.widget<Icon>(find.byIcon(s.icon));
        expect(icon.color, s.colors(colors).$2);
      }
      // Формы иконок различны — статус не передаётся одним цветом.
      expect(AggregateStatus.values.map((s) => s.icon).toSet(), hasLength(AggregateStatus.values.length));
    });
  }

  test('подписи статусов совпадают с глоссарием и вебом', () {
    expect(AggregateStatus.values.map((s) => s.label).toList(),
        ['Заменено', 'Скоро менять', 'Требуется замена', 'Нет данных']);
  });

  // Глава 7: вкладки и чипы — только пары токенов с проверенным контрастом (npm run test:tokens):
  // брендовый жёлтый — лишь заливка с on-primary, текст вкладки — fg, подчёркивание — primary-text.
  for (final brightness in Brightness.values) {
    test('вкладки и чипы ($brightness) на парах токенов с контрастом WCAG', () {
      final theme = evTheme(brightness);
      final c = theme.extension<EvColors>()!;
      expect(theme.tabBarTheme.labelColor, c.fg);
      expect(theme.tabBarTheme.unselectedLabelColor, c.fgMuted);
      expect(theme.tabBarTheme.indicatorColor, c.primaryText);
      expect(theme.chipTheme.selectedColor, c.primary);
      expect(theme.chipTheme.secondaryLabelStyle?.color, c.onPrimary);
      expect(theme.chipTheme.checkmarkColor, c.onPrimary);
      expect(theme.chipTheme.labelStyle?.color, c.fg);
    });
  }
}
