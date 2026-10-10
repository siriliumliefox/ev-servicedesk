// Глава 9 (Issue #43): вёрстка на реальных метриках шрифта — подписи схемы (M6), номер в шапке чата и подсказка
// у телефона (M7), ошибка выбора авто в форме обращения на маленьком экране и с клавиатурой (M5).
// Тестовый шрифт flutter_test рисует каждый глиф квадратом 1em и не показывает переносы и обрезку,
// как на устройстве. Здесь в семейство EvTypeMobile.fontFamily загружается Roboto из Flutter SDK —
// пропорциональный шрифт с кириллицей, есть и в CI. Системный шрифт iOS/macOS (SF) шире Roboto ≈ на 7 % —
// у подписей схемы проверяется запас 10 %. Шрифт регистрируется на весь файл, поэтому тесты — отдельным файлом.
import 'dart:io';

import 'package:flutter/material.dart';
import 'package:flutter/rendering.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:ev_servicedesk/data/prototype_repository.dart';
import 'package:ev_servicedesk/main.dart';
import 'package:ev_servicedesk/theme/app_theme.dart';

/// Минимальная ширина из ТЗ и iPhone 12–15 (390 pt). Подсказка у телефона обрезалась в раунде 1 на 390 pt
/// с системным шрифтом SF; Roboto уже SF ≈ на 7 %, поэтому с ним обрезка воспроизводится только на 360.
const _widths = [Size(360, 740), Size(390, 844)];

Future<void> _loadFont() async {
  final root = Platform.environment['FLUTTER_ROOT'];
  final file = File('$root/bin/cache/artifacts/material_fonts/Roboto-Medium.ttf');
  expect(file.existsSync(), isTrue, reason: 'нет ${file.path} (FLUTTER_ROOT=$root)');
  await (FontLoader(EvTypeMobile.fontFamily)..addFont(file.readAsBytes().then(ByteData.sublistView))).load();
}

Future<void> _pump(WidgetTester tester, Size size, {bool signedIn = true}) async {
  tester.view.physicalSize = size;
  tester.view.devicePixelRatio = 1;
  addTearDown(tester.view.reset);
  await tester.pumpWidget(
    EvServiceDeskApp(repository: PrototypeRepository(latency: Duration.zero), signedIn: signedIn),
  );
  await tester.pumpAndSettle();
}

/// Абзац виджета Text (его RichText).
RenderParagraph _paragraph(WidgetTester tester, Finder text) =>
    tester.renderObject<RenderParagraph>(find.descendant(of: text, matching: find.byType(RichText)));

double _width(String text, TextStyle? style) =>
    (TextPainter(text: TextSpan(text: text, style: style), textDirection: TextDirection.ltr)..layout()).width;

Future<void> _tap(WidgetTester tester, Finder finder) async {
  await tester.ensureVisible(finder);
  await tester.pumpAndSettle();
  await tester.tap(finder);
  await tester.pumpAndSettle();
}

/// iPhone SE (375×667) — самый короткий экран; клавиатура SE с панелью подсказок — ≈ 260 pt.
const _small = Size(375, 667);
const _keyboard = 260.0;

void main() {
  setUpAll(_loadFont);

  for (final size in _widths) {
    final w = size.width.toInt();

    testWidgets('M6: подписи схемы — до 2 строк, слова не разрываются, зоны не перекрываются ($w px)', (tester) async {
      await _pump(tester, size);
      final zones = <Rect>[];
      for (final code in ['ac_refrigerant', 'engine_oil', 'oil_filter', 'air_filter', 'cabin_filter', 'gearbox_oil']) {
        final zone = find.byKey(Key('zone-$code'));
        // Подпись — Text зоны (иконка статуса тоже рисуется через RichText).
        final label = _paragraph(tester, find.descendant(of: zone, matching: find.byType(Text)));
        expect(label.didExceedMaxLines, isFalse, reason: code);
        // Каждое слово целиком в строке (с запасом на более широкий SF) — без переноса посреди слова.
        final text = label.text.toPlainText();
        for (final word in text.split(' ')) {
          expect(_width(word, label.text.style) * 1.1, lessThanOrEqualTo(label.constraints.maxWidth),
              reason: '$code: «$word»');
        }
        final rect = tester.getRect(zone);
        expect(rect.left, greaterThanOrEqualTo(0), reason: code);
        expect(rect.right, lessThanOrEqualTo(size.width), reason: code);
        zones.add(rect);
      }
      for (var i = 0; i < zones.length; i++) {
        for (var j = i + 1; j < zones.length; j++) {
          expect(zones[i].overlaps(zones[j]), isFalse, reason: 'зоны $i и $j');
        }
      }
      expect(tester.takeException(), isNull);
    });

    testWidgets('M7а: номер обращения в шапке чата виден целиком, статус — под ним ($w px)', (tester) async {
      await _pump(tester, size);
      await tester.tap(find.descendant(of: find.byType(NavigationBar), matching: find.text('Поддержка')));
      await tester.pumpAndSettle();
      await tester.tap(find.text('Обращения'));
      await tester.pumpAndSettle();
      await tester.tap(find.byKey(const Key('ticket-1042')));
      await tester.pumpAndSettle();

      final title = find.text('Обращение №1042');
      final appBar = tester.getRect(find.byType(AppBar));
      expect(_paragraph(tester, title).didExceedMaxLines, isFalse);
      final rect = tester.getRect(title);
      expect(rect.right, lessThanOrEqualTo(appBar.right));
      // Помещается без ужатия (FittedBox — страховка для длинных номеров).
      expect(rect.width, moreOrLessEquals(tester.getSize(title).width));

      final status = find.descendant(of: find.byType(AppBar), matching: find.text('В работе'));
      expect(tester.getRect(status).top, greaterThanOrEqualTo(rect.bottom));
      expect(tester.getRect(status).bottom, lessThanOrEqualTo(appBar.bottom));
      expect(tester.takeException(), isNull);
    });

    testWidgets('M7б: подсказка у поля телефона переносится, а не обрезается ($w px)', (tester) async {
      await _pump(tester, size, signedIn: false);
      final helper = find.text('Пришлём SMS с кодом для входа или регистрации');
      expect(_paragraph(tester, helper).didExceedMaxLines, isFalse);
      expect(tester.getRect(helper).right, lessThanOrEqualTo(size.width));
      expect(tester.takeException(), isNull);
    });
  }

  for (final (size, keyboard) in [(_small, 0.0), (_small, _keyboard), (_widths.first, 0.0)]) {
    final label = '${size.width.toInt()}×${size.height.toInt()}${keyboard > 0 ? ', клавиатура' : ''}';

    testWidgets('M5: «Отправить» внизу формы без авто — вопрос, варианты и ошибка на экране ($label)', (tester) async {
      await _pump(tester, size);
      // C5: дерево неполадок → «Создать обращение»; описание из дерева многострочное — форма длиннее экрана.
      await _tap(tester, find.descendant(of: find.byType(NavigationBar), matching: find.text('Поддержка')));
      await _tap(tester, find.byKey(const Key('article-10')));
      await _tap(tester, find.text('Нет, завис полностью'));
      await _tap(tester, find.text('Нет'));
      await _tap(tester, find.text('Нет'));
      await _tap(tester, find.byKey(const Key('escalate')));
      expect(find.text('Новое обращение'), findsOneWidget);
      tester.view.viewInsets = FakeViewPadding(bottom: keyboard);
      await tester.pumpAndSettle();

      // К кнопке — позицией, а не жестом: в центре экрана может оказаться многострочное поле со своей прокруткой.
      final form = find.descendant(of: find.byType(ListView).last, matching: find.byType(Scrollable)).first;
      final position = tester.state<ScrollableState>(form).position;
      while (position.pixels < position.maxScrollExtent) {
        position.jumpTo(position.maxScrollExtent);
        await tester.pumpAndSettle();
      }
      final visible = tester.getRect(form);
      expect(visible.bottom, lessThanOrEqualTo(size.height - keyboard));
      final question = find.text('По какому автомобилю?');
      // Сценарий воспроизведён: вопрос над видимой областью (или ListView его уже не держит).
      expect(question.evaluate().isEmpty || tester.getRect(question).top < visible.top, isTrue);

      await tester.tap(find.byKey(const Key('submit-ticket')));
      await tester.pumpAndSettle();
      for (final finder in [
        question,
        find.byKey(const Key('vehicle-101')),
        find.byKey(const Key('vehicle-102')),
        find.text('Выберите автомобиль'),
      ]) {
        final rect = tester.getRect(finder);
        expect(rect.top, greaterThanOrEqualTo(visible.top), reason: '$finder');
        expect(rect.bottom, lessThanOrEqualTo(visible.bottom), reason: '$finder');
      }
      expect(find.text('Новое обращение'), findsOneWidget); // форма не отправлена
      expect(tester.takeException(), isNull);
    });
  }
}
