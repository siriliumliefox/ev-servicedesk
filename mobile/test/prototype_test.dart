// Кликабельный прототип клиента (Глава 7, Issue #37, ADR 0011): ключевые экраны, правило 3-х кликов
// (ТЗ раздел 6), несколько авто, пустые состояния и «нет сети», ширина 360 px, тап-зоны ≥ 44.
// Глава 9 (Issue #43): правки по итогам юзабилити-теста, раунд 1 — группа в конце файла.
import 'dart:math' as math;

import 'package:flutter/material.dart';
import 'package:flutter/rendering.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:ev_servicedesk/data/models.dart';
import 'package:ev_servicedesk/data/prototype_repository.dart';
import 'package:ev_servicedesk/main.dart';
import 'package:ev_servicedesk/screens/car/car_screen.dart';
import 'package:ev_servicedesk/screens/support/ticket_create_screen.dart';
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
    await _reveal(tester, finder);
    await tester.ensureVisible(finder);
    await tester.pumpAndSettle();
    await tester.tap(finder);
    await tester.pumpAndSettle();
    count++;
  }
}

Finder _nav(String label) => find.descendant(of: find.byType(NavigationBar), matching: find.text(label));

/// Длинный экран (форма с описанием из дерева): ListView строит элементы лениво — прокрутить до ещё не построенного.
/// Прокрутка позицией, а не жестом: в центре экрана может оказаться многострочное поле со своей прокруткой.
Future<void> _reveal(WidgetTester tester, Finder finder) async {
  if (finder.evaluate().isNotEmpty) return;
  final list = find.descendant(of: find.byType(ListView).last, matching: find.byType(Scrollable)).first;
  final position = tester.state<ScrollableState>(list).position;
  while (finder.evaluate().isEmpty && position.pixels < position.maxScrollExtent) {
    position.jumpTo(math.min(position.pixels + 200, position.maxScrollExtent));
    await tester.pumpAndSettle();
  }
}

/// Сменить авто через шторку «Мои автомобили» (переключатель на видимой вкладке).
Future<void> _selectVehicle(WidgetTester tester, String title) async {
  await tester.tap(find.byKey(const Key('vehicle-switcher')));
  await tester.pumpAndSettle();
  await tester.tap(find.text(title));
  await tester.pumpAndSettle();
}

AggregateStatusItem _item(AggregateStatus status) =>
    AggregateStatusItem(aggregateTypeCode: 'x', aggregateTypeName: 'x', status: status);

/// Сводка с обычными пробелами (в интерфейсе счётчики — с неразрывными).
(String, String?) _summary(List<AggregateStatusItem> items) {
  final (headline, hint) = aggregateSummary(items);
  return (headline.replaceAll('\u00A0', ' '), hint);
}

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
    // Глава 9 (M5): на аккаунте два авто — дерево к машине не привязано, авто выбирает клиент.
    await tester.tap(find.byKey(const Key('vehicle-101')));
    await tester.pumpAndSettle();
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
      await tester.tap(find.byKey(const Key('vehicle-101'))); // глава 9 (M5): при двух авто — выбор обязателен
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

  group('глава 9: правки по юзабилити-тесту, раунд 1', () {
    testWidgets('M1 (U-06): на «Обучении» можно сменить авто — статья Li Auto L7 за 4 тапа', (tester) async {
      await _pump(tester);
      await _selectVehicle(tester, 'Zeekr 001 · You'); // исходное состояние C6: выбран Zeekr 001

      final taps = _Taps(tester);
      await taps.tap(_nav('Обучение'));
      expect(find.text('Zeekr 001: голосовой помощник на русском'), findsOneWidget);
      expect(find.text('Li Auto L7: как узнать версию прошивки'), findsNothing);

      await taps.tap(find.byKey(const Key('vehicle-switcher')));
      expect(find.text('Мои автомобили'), findsOneWidget); // та же шторка, что на «Авто»
      await taps.tap(find.text('Li Auto L7 · Max'));
      expect(find.text('Li Auto L7: как узнать версию прошивки'), findsOneWidget);
      await taps.tap(find.byKey(const Key('article-2')));
      expect(find.text('Версия прошивки указана в «Настройки» → «Об автомобиле» → «Версия ПО».'), findsOneWidget);
      // C6: «Обучение» → переключатель → «Li Auto L7 · Max» → статья. Было 4 только с «Авто» (+1 с другой вкладки).
      expect(taps.count, 4);

      // Выбор общий для приложения: на «Авто» тоже Li Auto L7.
      await tester.pageBack();
      await tester.pumpAndSettle();
      await tester.tap(_nav('Авто'));
      await tester.pumpAndSettle();
      expect(find.text('Li Auto L7'), findsOneWidget);
      expect(find.byKey(const Key('zone-engine_oil')), findsOneWidget);
    });

    testWidgets('M1: одно авто — модель в заголовке «Обучения», без переключателя', (tester) async {
      await _pump(tester, account: AccountScenario.single);
      await tester.tap(_nav('Обучение'));
      await tester.pumpAndSettle();
      expect(find.text('Обучение · Li Auto L7'), findsOneWidget);
      expect(find.byKey(const Key('vehicle-switcher')), findsNothing);
    });

    testWidgets('M2 (C3): «Записаться на замену» — форма записи, время → описание, понятное подтверждение',
        (tester) async {
      await _pump(tester);
      final taps = _Taps(tester);
      await taps.tap(find.byKey(const Key('zone-engine_oil')));
      await taps.tap(find.byKey(const Key('book-service')));

      expect(find.text('Запись на замену'), findsOneWidget);
      expect(find.text('Что случилось?'), findsNothing);
      expect(find.text('Когда удобно приехать'), findsOneWidget);
      for (final option in visitTimeOptions) {
        expect(find.text(option), findsOneWidget);
      }
      // Авто известно из карточки агрегата — выбрано.
      expect(tester.widget<ChoiceChip>(find.byKey(const Key('vehicle-101'))).selected, isTrue);
      expect(find.text('Отправить заявку'), findsOneWidget);

      await taps.tap(find.text('Будни, вечер')); // необязательный выбор
      await taps.tap(find.byKey(const Key('submit-ticket')));
      expect(taps.count, 4); // без выбора времени — 3 (тест правила 3-х кликов выше)

      expect(find.text('Обращение №1100'), findsOneWidget);
      expect(find.text('Запись на замену: Масло двигателя\nКогда удобно приехать: Будни, вечер'), findsOneWidget);
      expect(find.text(bookingSentNotice), findsOneWidget);
      expect(find.text('Новое'), findsOneWidget); // статус в шапке чата — в роде «обращения»
      expect(find.textContaining('создано. Инженер ответит в чате'), findsNothing);
    });

    testWidgets('M2: «Записаться на ТО» у агрегата в норме — форма «Запись на ТО»', (tester) async {
      await _pump(tester);
      await tester.tap(find.byKey(const Key('zone-air_filter')));
      await tester.pumpAndSettle();
      await tester.tap(find.byKey(const Key('book-service')));
      await tester.pumpAndSettle();
      expect(find.text('Запись на ТО'), findsOneWidget);
      expect(find.text('Запись на ТО: Воздушный фильтр'), findsOneWidget);
    });

    test('M3 (U-01): сводка учитывает «Нет данных»; «в норме» — только если все «Заменено»', () {
      expect(_summary([_item(AggregateStatus.green), _item(AggregateStatus.green)]), ('Все агрегаты в норме', null));
      expect(_summary(List.filled(6, _item(AggregateStatus.unknown))),
          ('Нет данных о замене: 6', 'Статусы появятся после ТО в сервисе'));
      expect(_summary([_item(AggregateStatus.green), _item(AggregateStatus.unknown)]), ('Нет данных: 1', null));
      // У модели нет агрегатов в регламенте — не «в норме».
      expect(_summary([]), ('Нет данных о замене', 'Статусы появятся после ТО в сервисе'));
      expect(aggregateSummary([_item(AggregateStatus.yellow)]).$1, 'Скоро\u00A0менять:\u00A01');
      expect(
          _summary([
            _item(AggregateStatus.red),
            _item(AggregateStatus.yellow),
            _item(AggregateStatus.unknown),
            _item(AggregateStatus.green),
          ]),
          ('Требуется замена: 1 · Скоро менять: 1 · Нет данных: 1', null));
    });

    testWidgets('M3: новое авто без истории ТО — «Нет данных о замене», а не «в норме»', (tester) async {
      await _pump(tester, account: AccountScenario.empty);
      await tester.tap(find.text('Добавить авто'));
      await tester.pumpAndSettle();
      await tester.enterText(find.byKey(const Key('vin')), 'LLXAB3CF7SA000001');
      await tester.tap(find.text('Добавить'));
      await tester.pumpAndSettle();
      expect(find.text('Нет данных о замене: 6'), findsOneWidget);
      expect(find.text('Статусы появятся после ТО в сервисе'), findsOneWidget);
      expect(find.text('Все агрегаты в норме'), findsNothing);
    });

    testWidgets('M3: часть агрегатов без данных — счётчик рядом с остальными', (tester) async {
      await _pump(tester);
      expect(tester.widget<Text>(find.byKey(const Key('summary'))).data!.replaceAll('\u00A0', ' '),
          'Требуется замена: 1 · Скоро менять: 2 · Нет данных: 1');
    });

    testWidgets('M4: без согласия ПД — ошибка у галочки, поле кода не красное', (tester) async {
      final semantics = tester.ensureSemantics();
      await _pump(tester, signedIn: false);
      await tester.enterText(find.byKey(const Key('phone')), '291234567');
      await tester.tap(find.text('Получить код'));
      await tester.pumpAndSettle();
      await tester.enterText(find.byKey(const Key('code')), PrototypeRepository.demoCode);
      await tester.tap(find.text('Войти'));
      await tester.pumpAndSettle();

      final error = find.byKey(const Key('consent-error'));
      expect(find.descendant(of: error, matching: find.textContaining('примите согласие')), findsOneWidget);
      expect(
          tester.getTopLeft(error).dy, greaterThanOrEqualTo(tester.getBottomLeft(find.byKey(const Key('consent'))).dy));
      // Что получит VoiceOver (iOS/macOS): ошибка — живая область (зачитывается при появлении),
      // и она же — подсказка галочки (зачитывается, когда фокус на галочке).
      const message = 'Чтобы продолжить, примите согласие на обработку персональных данных';
      expect(tester.getSemantics(error), isSemantics(label: message, isLiveRegion: true));
      expect(
        tester.getSemantics(find.byKey(const Key('consent'))),
        isSemantics(hint: message, hasCheckedState: true, isChecked: false),
      );
      expect(tester.widget<CheckboxListTile>(find.byKey(const Key('consent'))).isError, isTrue);
      expect(tester.widget<TextField>(find.byKey(const Key('code'))).decoration?.errorText, isNull);

      await tester.tap(find.byKey(const Key('consent')));
      await tester.pumpAndSettle();
      expect(error, findsNothing);
      expect(tester.getSemantics(find.byKey(const Key('consent'))), isSemantics(hint: '', isChecked: true));
      semantics.dispose();
    });

    testWidgets('M5: из дерева неполадок при двух авто — авто не подставлено, выбор обязателен; C5 — 8 тапов',
        (tester) async {
      final repo = await _pump(tester);
      await _selectVehicle(tester, 'Zeekr 001 · You'); // исходное состояние C5: на «Авто» выбран Zeekr 001

      final taps = _Taps(tester);
      await taps.tap(_nav('Поддержка'));
      await taps.tap(find.byKey(const Key('article-10')));
      await taps.tap(find.text('Нет, завис полностью'));
      await taps.tap(find.text('Нет'));
      await taps.tap(find.text('Нет'));
      await taps.tap(find.byKey(const Key('escalate')));

      expect(find.text('По какому автомобилю?'), findsOneWidget);
      expect(tester.widget<ChoiceChip>(find.byKey(const Key('vehicle-101'))).selected, isFalse);
      expect(tester.widget<ChoiceChip>(find.byKey(const Key('vehicle-102'))).selected, isFalse);

      await _reveal(tester, find.byKey(const Key('submit-ticket')));
      await tester.tap(find.byKey(const Key('submit-ticket')));
      await tester.pumpAndSettle();
      expect(find.text('Выберите автомобиль'), findsOneWidget);
      expect(find.text('Новое обращение'), findsOneWidget); // форма не отправлена

      await taps.tap(find.byKey(const Key('vehicle-101')));
      expect(find.text('Выберите автомобиль'), findsNothing);
      expect(find.textContaining('Прикрепим автоматически: Li Auto L7'), findsOneWidget);
      await taps.tap(find.byKey(const Key('submit-ticket')));
      expect(find.text('Обращение №1100'), findsOneWidget);
      // C5: «Поддержка» → статья → 3 ответа → «Создать обращение» → авто → «Отправить». Было 7, стало 8.
      expect(taps.count, 8);

      final tickets = await tester.runAsync(repo.tickets);
      expect(tickets!.firstWhere((t) => t.id == 1100).vehicleId, 101);
    });

    testWidgets('M5: «Поддержка» → «Новое обращение» при двух авто — выбор обязателен', (tester) async {
      await _pump(tester);
      await tester.tap(_nav('Поддержка'));
      await tester.pumpAndSettle();
      await tester.tap(find.byKey(const Key('new-ticket')));
      await tester.pumpAndSettle();
      await tester.tap(find.byKey(const Key('category-audio')));
      await tester.enterText(find.byKey(const Key('description')), 'Нет звука');
      await tester.tap(find.byKey(const Key('submit-ticket')));
      await tester.pumpAndSettle();
      expect(find.text('Выберите автомобиль'), findsOneWidget);
      expect(find.text('Новое обращение'), findsOneWidget);
    });

    testWidgets('M5: одно авто — подставлено, выбор не спрашивается', (tester) async {
      await _pump(tester, account: AccountScenario.single);
      await tester.tap(_nav('Поддержка'));
      await tester.pumpAndSettle();
      await tester.tap(find.byKey(const Key('new-ticket')));
      await tester.pumpAndSettle();
      expect(find.text('По какому автомобилю?'), findsNothing);
      expect(find.textContaining('Прикрепим автоматически: Li Auto L7'), findsOneWidget);
      await tester.tap(find.byKey(const Key('category-audio')));
      await tester.enterText(find.byKey(const Key('description')), 'Нет звука');
      await tester.tap(find.byKey(const Key('submit-ticket')));
      await tester.pumpAndSettle();
      expect(find.text('Обращение №1100'), findsOneWidget);
    });

    testWidgets('M6: подписи на схеме — названия агрегатов, как в списке и карточке', (tester) async {
      await _pump(tester, size: _narrow);
      const names = {
        'ac_refrigerant': 'Фреон кондиционера',
        'engine_oil': 'Масло двигателя',
        'oil_filter': 'Масляный фильтр',
        'air_filter': 'Воздушный фильтр',
        'cabin_filter': 'Салонный фильтр',
        'gearbox_oil': 'Масло редуктора',
      };
      for (final MapEntry(key: code, value: name) in names.entries) {
        final label = tester.widget<Text>(
          find.descendant(of: find.byKey(Key('zone-$code')), matching: find.byType(Text)),
        );
        expect(label.data, name, reason: code);
        expect(label.maxLines, 2, reason: code);
      }
      for (final short in ['Масло ДВС', 'Масл. фильтр', 'Возд. фильтр', 'Салон. фильтр', 'Редуктор']) {
        expect(find.text(short), findsNothing, reason: short);
      }
      // Те же названия — в списке под схемой.
      await _reveal(tester, find.byKey(const Key('row-gearbox_oil')));
      for (final MapEntry(key: code, value: name) in names.entries) {
        expect(find.descendant(of: find.byKey(Key('row-$code')), matching: find.text(name)), findsOneWidget);
      }
    });

    testWidgets('M7в: у обращения из дерева неполадок (длинное описание) видна дата', (tester) async {
      await _pump(tester, size: _narrow);
      await tester.tap(_nav('Поддержка'));
      await tester.pumpAndSettle();
      await tester.tap(find.byKey(const Key('article-10')));
      await tester.pumpAndSettle();
      await tester.tap(find.text('Нет, завис полностью'));
      await tester.pumpAndSettle();
      await tester.tap(find.text('Нет'));
      await tester.pumpAndSettle();
      await tester.tap(find.text('Нет'));
      await tester.pumpAndSettle();
      await tester.tap(find.byKey(const Key('escalate')));
      await tester.pumpAndSettle();
      await tester.tap(find.byKey(const Key('vehicle-101')));
      await _reveal(tester, find.byKey(const Key('submit-ticket')));
      await tester.tap(find.byKey(const Key('submit-ticket')));
      await tester.pumpAndSettle();
      await tester.pageBack();
      await tester.pumpAndSettle();
      await tester.tap(find.text('Обращения'));
      await tester.pumpAndSettle();

      final tile = find.byKey(const Key('ticket-1100'));
      final date = find.byKey(const Key('ticket-1100-date'));
      expect(find.descendant(of: tile, matching: date), findsOneWidget);
      expect(tester.widget<Text>(date).data, '10 окт., 12:00');
      expect(tester.renderObject<RenderParagraph>(date).didExceedMaxLines, isFalse);
      expect(tester.getRect(tile).contains(tester.getRect(date).bottomRight - const Offset(1, 1)), isTrue);
      final description = tester.widget<Text>(
        find.descendant(of: tile, matching: find.textContaining('Что уже пробовал(а)')),
      );
      expect(description.maxLines, 2);
      expect(description.overflow, TextOverflow.ellipsis);
      expect(tester.takeException(), isNull);
    });
  });
}
