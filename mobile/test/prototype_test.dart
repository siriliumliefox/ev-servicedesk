// Кликабельный прототип клиента (Глава 7, Issue #37, ADR 0011): ключевые экраны, правило 3-х кликов
// (ТЗ раздел 6), несколько авто, пустые состояния и «нет сети», ширина 360 px, тап-зоны ≥ 44.
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:ev_servicedesk/data/prototype_repository.dart';
import 'package:ev_servicedesk/main.dart';
import 'package:ev_servicedesk/theme/app_theme.dart';

/// iPhone 15 (393×852) и минимальная ширина из ТЗ (360).
const _phone = Size(393, 852);
const _narrow = Size(360, 740);

Future<PrototypeRepository> _pump(
  WidgetTester tester, {
  bool signedIn = true,
  AccountScenario account = AccountScenario.multiple,
  bool offline = false,
  Size size = _phone,
}) async {
  tester.view.physicalSize = size;
  tester.view.devicePixelRatio = 1;
  addTearDown(tester.view.reset);
  final repo = PrototypeRepository(latency: Duration.zero, account: account)..offline = offline;
  await tester.pumpWidget(EvServiceDeskApp(repository: repo, signedIn: signedIn));
  await tester.pumpAndSettle();
  return repo;
}

/// Счётчик тапов от главного экрана — для правила 3-х кликов.
class _Taps {
  _Taps(this.tester);

  final WidgetTester tester;
  int count = 0;

  Future<void> tap(Finder finder) async {
    await tester.ensureVisible(finder);
    await tester.pumpAndSettle();
    await tester.tap(finder);
    await tester.pumpAndSettle();
    count++;
  }
}

Finder _nav(String label) => find.descendant(of: find.byType(NavigationBar), matching: find.text(label));

void main() {
  group('онбординг: телефон → SMS-код → авто по VIN', () {
    testWidgets('новый клиент проходит все шаги и видит своё авто', (tester) async {
      await _pump(tester, signedIn: false, account: AccountScenario.empty);

      await tester.enterText(find.byKey(const Key('phone')), '291234567');
      await tester.tap(find.text('Получить код'));
      await tester.pumpAndSettle();
      expect(find.text('Отправили на +375 29 123-45-67'), findsOneWidget);

      await tester.enterText(find.byKey(const Key('code')), PrototypeRepository.demoCode);
      await tester.tap(find.byKey(const Key('consent')));
      await tester.tap(find.text('Войти'));
      await tester.pumpAndSettle();
      expect(find.text('Добавьте автомобиль'), findsOneWidget);

      await tester.enterText(find.byKey(const Key('vin')), 'llxab3cf7sa000001');
      await tester.tap(find.text('Добавить'));
      await tester.pumpAndSettle();

      // Главный экран: модель определена по VIN, истории ТО нет — явный статус «Нет данных».
      expect(find.byType(NavigationBar), findsOneWidget);
      expect(find.text('Li Auto L7'), findsOneWidget);
      expect(find.text('Нет данных'), findsWidgets);
    });

    testWidgets('неполный телефон, неверный код и отсутствие согласия ПД — понятные ошибки', (tester) async {
      await _pump(tester, signedIn: false);

      await tester.enterText(find.byKey(const Key('phone')), '2912');
      await tester.tap(find.text('Получить код'));
      await tester.pumpAndSettle();
      expect(find.textContaining('Введите 9 цифр'), findsOneWidget);

      await tester.enterText(find.byKey(const Key('phone')), '291234567');
      await tester.tap(find.text('Получить код'));
      await tester.pumpAndSettle();

      await tester.enterText(find.byKey(const Key('code')), '1234');
      await tester.tap(find.text('Войти'));
      await tester.pumpAndSettle();
      expect(find.textContaining('согласие на обработку персональных данных'), findsOneWidget);

      await tester.tap(find.byKey(const Key('consent')));
      await tester.enterText(find.byKey(const Key('code')), '0000');
      await tester.tap(find.text('Войти'));
      await tester.pumpAndSettle();
      expect(find.text('Неверный код. Осталось попыток: 4'), findsOneWidget);
    });

    testWidgets('VIN не распознан — выбор модели; VIN чужого аккаунта — 409', (tester) async {
      await _pump(tester, account: AccountScenario.empty);
      await tester.tap(find.text('Добавить авто'));
      await tester.pumpAndSettle();

      await tester.enterText(find.byKey(const Key('vin')), 'ABC');
      await tester.tap(find.text('Добавить'));
      await tester.pumpAndSettle();
      expect(find.textContaining('17 символов: латинские'), findsOneWidget);

      await tester.enterText(find.byKey(const Key('vin')), PrototypeRepository.takenVin);
      await tester.tap(find.text('Добавить'));
      await tester.pumpAndSettle();
      expect(find.text('Этот VIN уже привязан к другому аккаунту'), findsOneWidget);

      await tester.enterText(find.byKey(const Key('vin')), 'WVWZZZ1KZ8W000001');
      await tester.tap(find.text('Добавить'));
      await tester.pumpAndSettle();
      expect(find.byKey(const Key('model')), findsOneWidget);

      await tester.tap(find.byKey(const Key('model')));
      await tester.pumpAndSettle();
      await tester.tap(find.text('Voyah Free · EVR').last);
      await tester.pumpAndSettle();
      await tester.tap(find.text('Добавить'));
      await tester.pumpAndSettle();
      expect(find.text('Voyah Free'), findsOneWidget);
    });
  });

  group('правило 3-х кликов от главного экрана (ТЗ раздел 6)', () {
    testWidgets('статус агрегата — 1 тап', (tester) async {
      await _pump(tester);
      final taps = _Taps(tester);
      await taps.tap(find.byKey(const Key('zone-engine_oil')));
      expect(find.text('Масло двигателя'), findsWidgets);
      expect(find.text('Требуется замена'), findsWidgets);
      expect(find.textContaining('перепробег'), findsOneWidget);
      expect(taps.count, lessThanOrEqualTo(3));
    });

    testWidgets('обучающий материал — 2 тапа', (tester) async {
      await _pump(tester);
      final taps = _Taps(tester);
      await taps.tap(_nav('Обучение'));
      await taps.tap(find.byKey(const Key('article-2')));
      expect(find.text('Li Auto L7: как узнать версию прошивки'), findsOneWidget);
      expect(taps.count, lessThanOrEqualTo(3));
    });

    testWidgets('форма тикета — 2 тапа из «Поддержки»', (tester) async {
      await _pump(tester);
      final taps = _Taps(tester);
      await taps.tap(_nav('Поддержка'));
      await taps.tap(find.byKey(const Key('new-ticket')));
      expect(find.text('Новое обращение'), findsOneWidget);
      expect(taps.count, lessThanOrEqualTo(3));
    });

    testWidgets('создание тикета на замену агрегата целиком — 3 тапа', (tester) async {
      await _pump(tester);
      final taps = _Taps(tester);
      await taps.tap(find.byKey(const Key('zone-engine_oil')));
      await taps.tap(find.byKey(const Key('book-service')));
      await taps.tap(find.byKey(const Key('submit-ticket')));
      expect(find.textContaining('Обращение №'), findsWidgets);
      expect(find.text('Запись на замену: Масло двигателя'), findsOneWidget);
      expect(taps.count, lessThanOrEqualTo(3));
    });
  });

  testWidgets('дерево решений: «завис экран» → перезагрузки → тикет с категорией и ходом диагностики', (tester) async {
    await _pump(tester);
    await tester.tap(_nav('Поддержка'));
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const Key('article-10')));
    await tester.pumpAndSettle();
    await tester.tap(find.text('Нет, завис полностью'));
    await tester.pumpAndSettle();
    expect(find.textContaining('Мягкая перезагрузка'), findsOneWidget);
    await tester.tap(find.text('Нет'));
    await tester.pumpAndSettle();
    expect(find.textContaining('Жёсткая перезагрузка'), findsOneWidget);
    await tester.tap(find.text('Нет'));
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const Key('escalate')));
    await tester.pumpAndSettle();

    expect(find.text('Новое обращение'), findsOneWidget);
    final chip = tester.widget<ChoiceChip>(find.byKey(const Key('category-appCrash')));
    expect(chip.selected, isTrue);
    expect(find.textContaining('Мягкая перезагрузка'), findsOneWidget); // ход диагностики в описании
    expect(find.textContaining('Прикрепим автоматически: Li Auto L7, прошивка RU 2.4.1'), findsOneWidget);
  });

  testWidgets('чат по обращению: история и отправка сообщения', (tester) async {
    await _pump(tester);
    await tester.tap(_nav('Поддержка'));
    await tester.pumpAndSettle();
    await tester.tap(find.text('Обращения'));
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const Key('ticket-1042')));
    await tester.pumpAndSettle();
    expect(find.text('Инженер Алексей'), findsOneWidget);

    await tester.enterText(find.byKey(const Key('message')), 'Версия 21.3, скриншот прикрепил');
    await tester.tap(find.byKey(const Key('send')));
    await tester.pumpAndSettle();
    expect(find.text('Версия 21.3, скриншот прикрепил'), findsOneWidget);
  });

  testWidgets('несколько авто: переключатель меняет схему', (tester) async {
    await _pump(tester);
    expect(find.textContaining('авто: 2'), findsOneWidget);
    expect(find.byKey(const Key('zone-engine_oil')), findsOneWidget);

    await tester.tap(find.byKey(const Key('vehicle-switcher')));
    await tester.pumpAndSettle();
    expect(find.text('Мои автомобили'), findsOneWidget);
    await tester.tap(find.text('Zeekr 001 · You'));
    await tester.pumpAndSettle();

    // Zeekr 001 — электромобиль: агрегатов ДВС нет на схеме.
    expect(find.text('Zeekr 001'), findsOneWidget);
    expect(find.byKey(const Key('zone-engine_oil')), findsNothing);
    expect(find.byKey(const Key('zone-cabin_filter')), findsOneWidget);
  });

  testWidgets('новости: счётчик непрочитанных, прочтение уменьшает его', (tester) async {
    await _pump(tester);
    expect(find.descendant(of: find.byType(Badge), matching: find.text('2')), findsOneWidget);
    await tester.tap(_nav('Новости'));
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const Key('notification-1')));
    await tester.pumpAndSettle();
    expect(find.textContaining('Исправлена работа голосового помощника'), findsOneWidget);
    expect(find.descendant(of: find.byType(Badge), matching: find.text('1')), findsOneWidget);
  });

  group('пустые состояния и ошибки', () {
    testWidgets('аккаунт без авто — пустые состояния во всех разделах', (tester) async {
      await _pump(tester, account: AccountScenario.empty);
      expect(find.text('Добавьте автомобиль'), findsOneWidget);

      await tester.tap(_nav('Обучение'));
      await tester.pumpAndSettle();
      expect(find.text('Инструкции появятся после добавления авто'), findsOneWidget);

      await tester.tap(_nav('Поддержка'));
      await tester.pumpAndSettle();
      expect(find.byKey(const Key('new-ticket')), findsNothing);
      await tester.tap(find.text('Обращения'));
      await tester.pumpAndSettle();
      expect(find.text('Обращений пока нет'), findsOneWidget);

      await tester.tap(_nav('Новости'));
      await tester.pumpAndSettle();
      await tester.tap(find.text('Прошивка'));
      await tester.pumpAndSettle();
      expect(find.text('В разделе «Прошивка» пока пусто'), findsOneWidget);
    });

    testWidgets('нет сети — ошибка с «Повторить», после восстановления данные загружаются', (tester) async {
      final repo = await _pump(tester, offline: true);
      expect(find.text('Нет подключения к интернету'), findsOneWidget);
      expect(find.text('Повторить'), findsOneWidget);

      repo.offline = false;
      await tester.tap(find.text('Повторить'));
      await tester.pumpAndSettle();
      expect(find.byKey(const Key('zone-engine_oil')), findsOneWidget);
    });

    testWidgets('нет сети при отправке — сообщение, форма не теряется', (tester) async {
      final repo = await _pump(tester);
      await tester.tap(_nav('Поддержка'));
      await tester.pumpAndSettle();
      await tester.tap(find.byKey(const Key('new-ticket')));
      await tester.pumpAndSettle();
      await tester.tap(find.byKey(const Key('category-audio')));
      await tester.enterText(find.byKey(const Key('description')), 'Нет звука');
      repo.offline = true;
      await tester.tap(find.byKey(const Key('submit-ticket')));
      await tester.pumpAndSettle();
      expect(find.text('Нет подключения к интернету. Попробуйте позже'), findsOneWidget);
      expect(find.text('Нет звука'), findsOneWidget);
    });
  });

  group('ширина 360 px и тап-зоны', () {
    for (final brightness in Brightness.values) {
      testWidgets('все разделы без переполнения ($brightness)', (tester) async {
        tester.platformDispatcher.platformBrightnessTestValue = brightness;
        addTearDown(tester.platformDispatcher.clearPlatformBrightnessTestValue);
        await _pump(tester, size: _narrow);
        for (final section in ['Обучение', 'Поддержка', 'Новости', 'Авто']) {
          await tester.tap(_nav(section));
          await tester.pumpAndSettle();
          expect(tester.takeException(), isNull, reason: section);
        }
        await tester.tap(find.byKey(const Key('zone-cabin_filter')));
        await tester.pumpAndSettle();
        expect(tester.takeException(), isNull);
      });
    }

    testWidgets('зоны схемы ≥ 44×44 и не перекрываются', (tester) async {
      await _pump(tester, size: _narrow);
      final rects = <Rect>[];
      for (final code in ['ac_refrigerant', 'engine_oil', 'oil_filter', 'air_filter', 'cabin_filter', 'gearbox_oil']) {
        final zone = find.byKey(Key('zone-$code'));
        final size = tester.getSize(zone);
        expect(size.width, greaterThanOrEqualTo(EvSize.tapTargetMin), reason: code);
        expect(size.height, greaterThanOrEqualTo(EvSize.tapTargetMin), reason: code);
        rects.add(tester.getRect(zone));
      }
      for (var i = 0; i < rects.length; i++) {
        for (var j = i + 1; j < rects.length; j++) {
          expect(rects[i].overlaps(rects[j]), isFalse, reason: 'зоны $i и $j');
        }
      }
    });
  });
}
