// Глава 9 (Issue #43): вёрстка на реальных метриках шрифта — подписи схемы (M6), номер в шапке чата и подсказка
// у телефона (M7), ошибка выбора авто в форме обращения на маленьком экране и с клавиатурой (M5).
// Тестовый шрифт flutter_test рисует каждый глиф квадратом 1em и не показывает переносы и обрезку,
// как на устройстве. Здесь в семейство EvTypeMobile.fontFamily загружаются начертания Inter из assets/fonts —
// тот же шрифт, что в приложении (глава 18, ADR 0022 п. 9). У подписей схемы — запас 10 % на увеличенный
// системный размер текста. Шрифт регистрируется на весь файл, поэтому тесты — отдельным файлом.
// Глава 19 (ADR 0023 п. 6): подписи и зоны схемы (M6) — на ширинах 360–430 px при масштабе текста 1.0 и 1.1 (предел
// подписей схемы), группа в конце файла.
import 'dart:io';

import 'package:flutter/material.dart';
import 'package:flutter/rendering.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:ev_servicedesk/data/prototype_repository.dart';
import 'package:ev_servicedesk/main.dart';
import 'package:ev_servicedesk/screens/car/aggregate_scheme.dart';
import 'package:ev_servicedesk/theme/app_theme.dart';

/// Минимальная ширина из ТЗ и iPhone 12–15 (390 pt). Подсказка у телефона обрезалась в раунде 1 на 390 pt
/// с системным шрифтом SF (до подключения Inter).
const _widths = [Size(360, 740), Size(390, 844)];

Future<void> _loadFont() async {
  final loader = FontLoader(EvTypeMobile.fontFamily);
  for (final weight in ['Regular', 'Medium', 'SemiBold', 'Bold']) {
    final file = File('assets/fonts/inter/Inter-$weight.ttf');
    expect(file.existsSync(), isTrue, reason: 'нет ${file.path}');
    loader.addFont(file.readAsBytes().then(ByteData.sublistView));
  }
  await loader.load();
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

  group('глава 19: схема на ширинах 360–430 px и с крупным шрифтом', () {
    // Минимум ТЗ, iPhone SE, iPhone 12–15, iPhone 11/XR, iPhone 15 Pro Max/Plus.
    const sizes = [Size(360, 740), Size(375, 667), Size(390, 844), Size(414, 896), Size(430, 932)];
    const codes = ['engine_oil', 'oil_filter', 'air_filter', 'ac_refrigerant', 'cabin_filter', 'gearbox_oil'];
    for (final size in sizes) {
      for (final scale in [1.0, AggregateScheme.maxLabelTextScale]) {
        testWidgets('${size.width.toInt()} px, текст ×$scale: каждая зона нажимается, ≥ 44×44, без наложений',
            (tester) async {
          tester.platformDispatcher.textScaleFactorTestValue = scale;
          addTearDown(tester.platformDispatcher.clearTextScaleFactorTestValue);
          await _pump(tester, size);
          final rects = <String, Rect>{};
          for (final code in codes) {
            final zone = find.byKey(Key('zone-$code'));
            await tester.ensureVisible(zone);
            await tester.pumpAndSettle();
            final rect = tester.getRect(zone);
            expect(rect.width, greaterThanOrEqualTo(EvSize.tapTargetMin), reason: code);
            expect(rect.height, greaterThanOrEqualTo(EvSize.tapTargetMin), reason: code);
            expect(rect.left, greaterThanOrEqualTo(0), reason: code);
            expect(rect.right, lessThanOrEqualTo(size.width), reason: code);
            final label = _paragraph(tester, find.descendant(of: zone, matching: find.byType(Text)));
            expect(label.didExceedMaxLines, isFalse, reason: '$code: подпись целиком');
            // M6 (глава 9): каждое слово целиком в строке — без переноса посреди слова. При обычном размере текста —
            // с запасом 10 % на увеличенный системный размер, при увеличенном — с его масштабом.
            final margin = scale == 1.0 ? 1.1 : 1.0;
            for (final word in label.text.toPlainText().split(' ')) {
              final width = label.textScaler.scale(_width(word, label.text.style));
              expect(width * margin, lessThanOrEqualTo(label.constraints.maxWidth), reason: '$code: «$word»');
            }
            // Центр зоны не перекрыт ничем (подписью соседа, контуром) — тап попадает в неё.
            expect(zone.hitTestable(), findsOneWidget, reason: code);
            await tester.tap(zone);
            await tester.pumpAndSettle();
            final name = (tester.widget<Text>(find.descendant(of: zone, matching: find.byType(Text)))).data!;
            expect(find.descendant(of: find.byType(BottomSheet), matching: find.text(name)), findsOneWidget,
                reason: '$code: открылась карточка агрегата');
            await tester.tapAt(const Offset(10, 10)); // закрыть шит тапом по затемнению
            await tester.pumpAndSettle();
            // Положение на экране зависит от прокрутки — рамка запоминается в координатах схемы.
            rects[code] = rect.shift(-tester.getTopLeft(find.byType(AggregateScheme)));
          }
          final list = rects.entries.toList();
          for (var i = 0; i < list.length; i++) {
            for (var j = i + 1; j < list.length; j++) {
              expect(list[i].value.overlaps(list[j].value), isFalse, reason: '${list[i].key} и ${list[j].key}');
            }
          }
          expect(tester.takeException(), isNull);
        });
      }
    }
  });
}
