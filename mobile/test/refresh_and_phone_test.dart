// Замечания прогона главы 22 к мобильному клиенту: M1 — номер с кодом страны в поле с префиксом «+375»,
// M2 — «потянуть для обновления» на пустых экранах, M3 — лента уведомлений перечитывается, когда снова видна.
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:ev_servicedesk/data/models.dart';
import 'package:ev_servicedesk/data/prototype_repository.dart';
import 'package:ev_servicedesk/main.dart';
import 'package:ev_servicedesk/ui/format.dart';

/// Сервер прототипа, у которого статьи и лента меняются «на сервере» во время теста.
class _Repo extends PrototypeRepository {
  _Repo() : super(latency: Duration.zero);

  final articlesByType = <ArticleType, List<KnowledgeArticle>>{};
  List<NotificationItem>? feed;
  String? requestedPhone;

  @override
  Future<int> requestCode(String phone) {
    requestedPhone = phone;
    return super.requestCode(phone);
  }

  @override
  Future<List<KnowledgeArticle>> articles(int? vehicleModelId, ArticleType type) =>
      articlesByType.containsKey(type) ? Future.value([...articlesByType[type]!]) : super.articles(vehicleModelId, type);

  @override
  Future<List<NotificationItem>> notifications() => feed == null ? super.notifications() : Future.value([...feed!]);
}

Future<void> _pump(WidgetTester tester, _Repo repo, {bool signedIn = true}) async {
  tester.view.physicalSize = const Size(393, 852);
  tester.view.devicePixelRatio = 1;
  addTearDown(tester.view.reset);
  await tester.pumpWidget(EvServiceDeskApp(repository: repo, signedIn: signedIn));
  await tester.pumpAndSettle();
}

Finder _nav(String label) => find.descendant(of: find.byType(NavigationBar), matching: find.text(label));

Future<void> _pull(WidgetTester tester, Finder from) async {
  await tester.fling(from, const Offset(0, 400), 1000);
  await tester.pumpAndSettle();
}

KnowledgeArticle _article(int id, ArticleType type, String title) =>
    KnowledgeArticle(id: id, vehicleModelId: null, articleType: type, title: title, content: 'Текст статьи');

NotificationItem _news(int id, String title) =>
    NotificationItem(id: id, type: NotificationType.news, message: title, createdAt: DateTime(2026, 10, id));

void main() {
  group('M1: номер телефона с кодом страны', () {
    test('9 цифр абонента из любого вида записи', () {
      expect(belarusSubscriberDigits('+375 29 000-90-06'), '290009006');
      expect(belarusSubscriberDigits('375290009006'), '290009006');
      expect(belarusSubscriberDigits('80290009006'), '290009006');
      expect(belarusSubscriberDigits('8 (029) 000-90-06'), '290009006');
      expect(belarusSubscriberDigits('29 000-90-06'), '290009006');
      expect(belarusSubscriberDigits('375'), '375', reason: 'номер ещё набирается — код не отрезается раньше времени');
    });

    for (final input in ['+375 29 000-90-06', '375290009006', '80290009006']) {
      testWidgets('«$input» — код уходит на +375290009006, а не на чужой номер', (tester) async {
        final repo = _Repo();
        await _pump(tester, repo, signedIn: false);
        await tester.enterText(find.byKey(const Key('phone')), input);
        await tester.pump();
        expect(tester.widget<TextField>(find.byKey(const Key('phone'))).controller!.text, '290009006');
        await tester.tap(find.text('Получить код'));
        await tester.pumpAndSettle();
        expect(repo.requestedPhone, '+375290009006');
      });
    }

    testWidgets('номер с кодом, набранный не до конца, не отправляется', (tester) async {
      final repo = _Repo();
      await _pump(tester, repo, signedIn: false);
      await tester.enterText(find.byKey(const Key('phone')), '375290009');
      await tester.tap(find.text('Получить код'));
      await tester.pumpAndSettle();
      expect(repo.requestedPhone, isNull);
      expect(find.textContaining('Введите 9 цифр'), findsOneWidget);
    });
  });

  group('M2: «потянуть для обновления» на пустом экране', () {
    testWidgets('«Обучение»: новая инструкция видна после жеста, без возврата из фона', (tester) async {
      final repo = _Repo()..articlesByType[ArticleType.guide] = [];
      await _pump(tester, repo);
      await tester.tap(_nav('Обучение'));
      await tester.pumpAndSettle();
      expect(find.text('Инструкций для этой модели пока нет'), findsOneWidget);

      repo.articlesByType[ArticleType.guide] = [_article(901, ArticleType.guide, 'Зарядка от сети 220 В')];
      await _pull(tester, find.text('Инструкций для этой модели пока нет'));
      expect(find.text('Зарядка от сети 220 В'), findsOneWidget);
    });

    testWidgets('«Поддержка → Неполадки»', (tester) async {
      final repo = _Repo()..articlesByType[ArticleType.troubleshooting] = [];
      await _pump(tester, repo);
      await tester.tap(_nav('Поддержка'));
      await tester.pumpAndSettle();
      expect(find.text('Инструкций по неполадкам пока нет'), findsOneWidget);

      repo.articlesByType[ArticleType.troubleshooting] = [
        _article(902, ArticleType.troubleshooting, 'Не заряжается'),
      ];
      await _pull(tester, find.text('Инструкций по неполадкам пока нет'));
      expect(find.text('Не заряжается'), findsOneWidget);
    });

    testWidgets('центр уведомлений и «Новости»', (tester) async {
      final repo = _Repo()..feed = [];
      await _pump(tester, repo);
      await tester.tap(_nav('Новости'));
      await tester.pumpAndSettle();
      expect(find.text('Пока нет новостей'), findsOneWidget);

      repo.feed = [_news(1, 'Открыт новый сервисный центр')];
      await _pull(tester, find.text('Пока нет новостей'));
      expect(find.text('Открыт новый сервисный центр'), findsOneWidget);

      repo.feed = [];
      await tester.tap(find.byKey(const Key('notification-bell')).hitTestable());
      await tester.pumpAndSettle();
      expect(find.text('Уведомлений пока нет'), findsOneWidget);
      repo.feed = [_news(2, 'Акция на шиномонтаж')];
      await _pull(tester, find.text('Уведомлений пока нет'));
      expect(find.text('Акция на шиномонтаж'), findsOneWidget);
    });
  });

  group('M3: лента перечитывается, когда снова видна', () {
    testWidgets('повторно открытый центр уведомлений — новый список без жеста', (tester) async {
      final repo = _Repo()..feed = [_news(1, 'Первая новость')];
      await _pump(tester, repo);
      final bell = find.byKey(const Key('notification-bell')).hitTestable();
      await tester.tap(bell);
      await tester.pumpAndSettle();
      expect(find.text('Первая новость'), findsOneWidget);

      // Поверх центра — другой экран (запись на ТО из уведомления и т.п.); тем временем пришло новое.
      tester.state<NavigatorState>(find.byType(Navigator).first)
          .push(MaterialPageRoute<void>(builder: (_) => const Scaffold(body: Text('Поверх центра'))));
      await tester.pumpAndSettle();
      repo.feed = [_news(2, 'Вторая новость'), ...repo.feed!];
      tester.state<NavigatorState>(find.byType(Navigator).first).pop();
      await tester.pumpAndSettle();
      expect(find.text('Вторая новость'), findsOneWidget);

      // Закрыли и открыли колокольчиком снова.
      await tester.pageBack();
      await tester.pumpAndSettle();
      repo.feed = [_news(3, 'Третья новость'), ...repo.feed!];
      await tester.tap(bell);
      await tester.pumpAndSettle();
      expect(find.text('Третья новость'), findsOneWidget);
    });

    testWidgets('снова выбранная вкладка «Новости» — новый список без жеста', (tester) async {
      final repo = _Repo()..feed = [_news(1, 'Первая новость')];
      await _pump(tester, repo);
      await tester.tap(_nav('Новости'));
      await tester.pumpAndSettle();
      expect(find.text('Первая новость'), findsOneWidget);

      await tester.tap(_nav('Авто'));
      await tester.pumpAndSettle();
      repo.feed = [_news(2, 'Вторая новость'), ...repo.feed!];
      await tester.tap(_nav('Новости'));
      await tester.pumpAndSettle();
      expect(find.text('Вторая новость'), findsOneWidget);
    });
  });
}
