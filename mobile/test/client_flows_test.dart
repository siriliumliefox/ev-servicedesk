// Глава 20 (ADR 0024): вложения в форме и чате, чат в реальном времени, push в приложении, центр уведомлений,
// текст статьи в Markdown. Экраны — на фикстурах прототипа; сервер подменён (сокет, push-канал, выбор файла).
import 'dart:async';
import 'dart:math' as math;

import 'package:flutter/foundation.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:ev_servicedesk/app/push_service.dart';
import 'package:ev_servicedesk/data/attachments.dart';
import 'package:ev_servicedesk/data/models.dart';
import 'package:ev_servicedesk/data/prototype_repository.dart';
import 'package:ev_servicedesk/data/repository.dart';
import 'package:ev_servicedesk/data/ticket_live.dart';
import 'package:ev_servicedesk/main.dart';
import 'package:ev_servicedesk/push/push_channel.dart';
import 'package:ev_servicedesk/screens/learning/learning_screen.dart';
import 'package:ev_servicedesk/theme/app_theme.dart';

/// Сервер прототипа с управляемыми сокетом, загрузками и журналом push-токенов.
class _Repo extends PrototypeRepository {
  _Repo() : super(latency: Duration.zero);

  final live = _ControlledLive();
  final pushTokens = <String>[];
  final unregistered = <String>[];
  final opened = <int>[];
  var failUploads = 0;

  @override
  TicketLive watchTicket(int ticketId, {required int afterId}) => live;

  @override
  Future<UploadedAttachment> uploadAttachment(LocalAttachment file, {void Function(double progress)? onProgress}) {
    if (failUploads > 0) {
      failUploads--;
      return Future.error(const OfflineException());
    }
    return super.uploadAttachment(file, onProgress: onProgress);
  }

  @override
  Future<void> registerPushToken(String token) async => pushTokens.add(token);

  @override
  Future<void> unregisterPushToken(String token) async => unregistered.add(token);

  @override
  Future<void> markNotificationOpened(int notificationId, String pushToken) {
    opened.add(notificationId);
    return super.markNotificationOpened(notificationId, pushToken);
  }
}

class _ControlledLive implements TicketLive {
  final _events = StreamController<TicketLiveEvent>.broadcast();
  final _state = ValueNotifier(LiveState.live);

  void emit(TicketLiveEvent e) => _events.add(e);
  void setState(LiveState s) => _state.value = s;

  @override
  Stream<TicketLiveEvent> get events => _events.stream;
  @override
  ValueListenable<LiveState> get state => _state;
  @override
  void pause() {}
  @override
  void resume() {}
  @override
  Future<void> close() async {}
}

class _Source implements AttachmentSource {
  LocalAttachment? next;

  @override
  Future<LocalAttachment?> pick(AttachmentType type, {required bool camera}) async => next;
}

class _Channel implements PushChannel {
  final received$ = StreamController<PushEvent>.broadcast();
  final opened$ = StreamController<PushEvent>.broadcast();
  final refresh$ = StreamController<String>.broadcast();
  PushEvent? initial;

  @override
  Future<String> permission() async => 'authorized';
  /// iOS без APNs: FCM-токен получить нельзя.
  bool noToken = false;

  @override
  Future<String?> token() async => noToken ? throw Exception('APNS token has not been set') : 'fcm-token';
  @override
  Stream<String> get tokenRefresh => refresh$.stream;
  @override
  Stream<PushEvent> get received => received$.stream;
  @override
  Stream<PushEvent> get opened => opened$.stream;
  @override
  Future<PushEvent?> initialOpened() async => initial;
}

/// Контраст WCAG двух цветов.
double _contrast(Color a, Color b) {
  final la = a.computeLuminance(), lb = b.computeLuminance();
  return (math.max(la, lb) + 0.05) / (math.min(la, lb) + 0.05);
}

PushEvent _push(Map<String, String> data, {String title = '', String body = ''}) =>
    PushEvent(title: title, body: body, data: data, receivedAt: DateTime(2026, 10, 13));

Future<void> _pump(WidgetTester tester, _Repo repo, {_Source? source, _Channel? channel, bool signedIn = true}) async {
  tester.view.physicalSize = const Size(393, 852);
  tester.view.devicePixelRatio = 1;
  addTearDown(tester.view.reset);
  await tester.pumpWidget(EvServiceDeskApp(
    repository: repo,
    signedIn: signedIn,
    attachmentSource: source,
    push: channel == null ? null : PushService(channel, repo),
  ));
  await tester.pumpAndSettle();
}

Finder _nav(String label) => find.descendant(of: find.byType(NavigationBar), matching: find.text(label));

Future<void> _openChat(WidgetTester tester, int ticketId) async {
  await tester.tap(_nav('Поддержка'));
  await tester.pumpAndSettle();
  await tester.tap(find.text('Обращения'));
  await tester.pumpAndSettle();
  await tester.tap(find.byKey(Key('ticket-$ticketId')));
  await tester.pumpAndSettle();
}

Future<void> _attach(WidgetTester tester, String option) async {
  await tester.tap(find.byKey(const Key('attach')));
  await tester.pumpAndSettle();
  await tester.tap(find.byKey(Key(option)));
  await tester.pumpAndSettle();
}

const _photo = LocalAttachment(path: '/tmp/IMG_0001.jpg', fileType: AttachmentType.photo, sizeBytes: 2 * 1024 * 1024);

void main() {
  group('вложения (ADR 0024 п. 9)', () {
    test('проверка до загрузки: формат, 20 МБ фото, 200 МБ видео, не больше 10', () {
      expect(attachmentProblem(_photo, alreadyAttached: 0), isNull);
      expect(
        attachmentProblem(
            const LocalAttachment(path: 'a.mov', fileType: AttachmentType.video, sizeBytes: 199 * 1024 * 1024),
            alreadyAttached: 0),
        isNull,
      );
      expect(
        attachmentProblem(
            const LocalAttachment(path: 'a.mov', fileType: AttachmentType.video, sizeBytes: 201 * 1024 * 1024),
            alreadyAttached: 0),
        contains('200 МБ'),
      );
      expect(
        attachmentProblem(
            const LocalAttachment(path: 'a.jpg', fileType: AttachmentType.photo, sizeBytes: maxPhotoBytes + 1),
            alreadyAttached: 0),
        contains('20 МБ'),
      );
      expect(
        attachmentProblem(const LocalAttachment(path: 'a.gif', fileType: AttachmentType.photo, sizeBytes: 10),
            alreadyAttached: 0),
        contains('формат'),
      );
      expect(
        attachmentProblem(const LocalAttachment(path: 'a.jpg', fileType: AttachmentType.video, sizeBytes: 10),
            alreadyAttached: 0),
        contains('формат'),
        reason: 'фото, выбранное как видео',
      );
      expect(attachmentProblem(_photo, alreadyAttached: 10), contains('не больше 10'));
      expect(mimeType(const LocalAttachment(path: 'IMG.MOV', fileType: AttachmentType.video, sizeBytes: 1)),
          'video/quicktime');
    });

    testWidgets('обращение с фото: загрузка сразу после выбора, фото уходит с тикетом и видно в чате', (tester) async {
      final repo = _Repo();
      final source = _Source()..next = _photo;
      await _pump(tester, repo, source: source);
      await tester.tap(_nav('Поддержка'));
      await tester.pumpAndSettle();
      await tester.tap(find.byKey(const Key('new-ticket')));
      await tester.pumpAndSettle();
      await tester.tap(find.byKey(const Key('vehicle-101')));
      await tester.tap(find.byKey(const Key('category-navigation')));
      await tester.enterText(find.byKey(const Key('description')), 'Не строит маршрут');
      await tester.pumpAndSettle();
      await _attach(tester, 'attach-photo-gallery');
      expect(find.textContaining('Фото 1 · 2,0 МБ'), findsOneWidget);
      await tester.scrollUntilVisible(find.byKey(const Key('submit-ticket')), 200,
          scrollable: find.byType(Scrollable).last);
      await tester.tap(find.byKey(const Key('submit-ticket')));
      await tester.pumpAndSettle();
      expect(find.textContaining('Обращение №'), findsWidgets);
      expect(find.text('Фото'), findsOneWidget, reason: 'вложение в первом сообщении');
    });

    testWidgets('большое видео не прикрепляется — понятная причина', (tester) async {
      final repo = _Repo();
      final source = _Source()
        ..next = const LocalAttachment(path: '/tmp/long.mov', fileType: AttachmentType.video, sizeBytes: 300 << 20);
      await _pump(tester, repo, source: source);
      await _openChat(tester, 1042);
      await _attach(tester, 'attach-video-camera');
      expect(find.text('Видео больше 200 МБ — снимите покороче'), findsOneWidget);
      expect(find.byKey(const Key('attachment-0')), findsNothing);
    });

    testWidgets('загрузка не удалась — отправка ждёт, «повторить» догружает', (tester) async {
      final repo = _Repo()..failUploads = 1;
      final source = _Source()..next = _photo;
      await _pump(tester, repo, source: source);
      await _openChat(tester, 1042);
      await _attach(tester, 'attach-photo-camera');
      expect(find.text('Не загрузилось — повторить'), findsOneWidget);

      await tester.tap(find.byKey(const Key('send')));
      await tester.pumpAndSettle();
      expect(find.text('Повторите загрузку или уберите файл'), findsOneWidget);

      await tester.tap(find.text('Не загрузилось — повторить'));
      await tester.pump(const Duration(seconds: 5)); // сообщение об ошибке закрывает кнопку отправки
      await tester.pumpAndSettle();
      expect(find.textContaining('Фото 1'), findsOneWidget);
      await tester.tap(find.byKey(const Key('send')));
      await tester.pumpAndSettle();
      expect(find.byKey(const Key('attachment-0')), findsNothing, reason: 'отправлено — лоток пуст');
      expect(find.text('Вложение'), findsOneWidget, reason: 'сообщение без текста — подпись «Вложение»');
    });
  });

  group('чат в реальном времени (ADR 0024 п. 8)', () {
    testWidgets('ответ инженера приходит без обновления; повтор по id отбрасывается; «решено» закрывает ввод',
        (tester) async {
      final repo = _Repo();
      await _pump(tester, repo);
      await _openChat(tester, 1042);
      final reply = TicketMessage(
        id: 9001,
        fromClient: false,
        authorName: 'Инженер поддержки',
        body: 'Обновите карты и перезагрузите систему',
        createdAt: DateTime(2026, 10, 13, 10),
      );
      repo.live.emit(LiveMessage(reply));
      await tester.pumpAndSettle();
      repo.live.emit(LiveMessage(reply));
      await tester.pumpAndSettle();
      expect(find.text('Обновите карты и перезагрузите систему'), findsOneWidget);

      repo.live.emit(LiveTicket(Ticket(
        id: 1042,
        vehicleId: 101,
        category: TicketCategory.navigation,
        status: TicketStatus.resolved,
        summary: 'Яндекс Навигатор не показывает пробки',
        createdAt: DateTime(2026, 10, 8, 18, 40),
      )));
      await tester.pumpAndSettle();
      expect(find.descendant(of: find.byKey(const Key('chat-status')), matching: find.text('Решено')), findsOneWidget);
      expect(find.byKey(const Key('message')), findsNothing);
    });

    testWidgets('нет связи дольше мгновения — «переподключаемся», после восстановления надпись уходит', (tester) async {
      final repo = _Repo();
      await _pump(tester, repo);
      await _openChat(tester, 1042);
      repo.live.setState(LiveState.connecting);
      await tester.pump(const Duration(milliseconds: 500));
      expect(find.byKey(const Key('chat-reconnecting')), findsNothing, reason: 'короткий обрыв не мигает');
      await tester.pump(const Duration(seconds: 2));
      expect(find.textContaining('переподключаемся'), findsOneWidget);
      repo.live.setState(LiveState.live);
      await tester.pump();
      expect(find.byKey(const Key('chat-reconnecting')), findsNothing);
    });
  });

  group('push в приложении (ADR 0024 п. 4)', () {
    testWidgets('после входа токен регистрируется, при выходе удаляется до выхода', (tester) async {
      final repo = _Repo();
      await _pump(tester, repo, channel: _Channel());
      expect(repo.pushTokens, ['fcm-token']);
      await tester.tap(find.byKey(const Key('open-profile')));
      await tester.pumpAndSettle();
      await tester.tap(find.byKey(const Key('sign-out')));
      await tester.pumpAndSettle();
      expect(find.byKey(const Key('phone')), findsOneWidget, reason: 'вышли — экран входа');
      expect(repo.unregistered, ['fcm-token']);
    });

    testWidgets(
        'push новости на открытом приложении — баннер; «Открыть» — центр с этим уведомлением, открытие отмечено',
        (tester) async {
      final repo = _Repo();
      final channel = _Channel();
      await _pump(tester, repo, channel: channel);
      channel.received$
          .add(_push({'notification_id': '1', 'type': 'firmware'}, title: 'Новая прошивка', body: 'RU 2.5.0'));
      await tester.pumpAndSettle();
      expect(find.byKey(const Key('push-banner')), findsOneWidget);
      // «Открыть» читается на подложке баннера (на симуляторе было тёмное на тёмном).
      final action = tester.widget<Text>(find.descendant(of: find.byType(SnackBarAction), matching: find.byType(Text)));
      final banner = tester.widget<Material>(
          find.descendant(of: find.byKey(const Key('push-banner')), matching: find.byType(Material)).first);
      final actionColor = DefaultTextStyle.of(tester.element(find.text('Открыть'))).style.color ?? action.style?.color;
      expect(actionColor, isNotNull);
      expect(_contrast(actionColor!, banner.color!), greaterThanOrEqualTo(4.5));
      await tester.tap(find.text('Открыть'));
      await tester.pumpAndSettle();
      expect(find.text('Уведомления'), findsOneWidget);
      expect(find.byKey(const Key('notification-title')), findsOneWidget, reason: 'уведомление открыто сразу');
      expect(repo.opened, [1]);
    });

    testWidgets('без FCM-токена (iOS без APNs) нажатие на push всё равно открывает уведомление', (tester) async {
      final repo = _Repo();
      final channel = _Channel()..noToken = true;
      await _pump(tester, repo, channel: channel);
      expect(repo.pushTokens, isEmpty);
      channel.opened$.add(_push({'notification_id': '2', 'type': 'maintenance'}));
      await tester.pumpAndSettle();
      expect(find.text('Уведомления'), findsOneWidget);
      expect(find.byKey(const Key('notification-title')), findsOneWidget);
      expect(repo.opened, isEmpty, reason: 'отметить открытие без токена нельзя');
    });

    testWidgets('нажатие на push по тикету открывает чат; по открытому чату баннера нет', (tester) async {
      final repo = _Repo();
      final channel = _Channel();
      await _pump(tester, repo, channel: channel);
      channel.opened$.add(_push({'type': 'ticket', 'ticket_id': '1042'}));
      await tester.pumpAndSettle();
      expect(find.text('Обращение №1042'), findsOneWidget);

      channel.received$.add(_push({'type': 'ticket', 'ticket_id': '1042'}, title: 'Поддержка'));
      await tester.pumpAndSettle();
      expect(find.byKey(const Key('push-banner')), findsNothing, reason: 'сообщение покажет сокет');
    });

    testWidgets('push запустил закрытое приложение до входа — откроется после входа', (tester) async {
      final repo = _Repo();
      final channel = _Channel()..initial = _push({'type': 'ticket', 'ticket_id': '1042'});
      await _pump(tester, repo, channel: channel, signedIn: false);
      expect(find.text('Обращение №1042'), findsNothing);
      await tester.enterText(find.byKey(const Key('phone')), '291234567');
      await tester.tap(find.text('Получить код'));
      await tester.pumpAndSettle();
      await tester.enterText(find.byKey(const Key('code')), PrototypeRepository.demoCode);
      await tester.tap(find.byKey(const Key('consent')));
      await tester.tap(find.text('Войти'));
      await tester.pumpAndSettle();
      expect(find.text('Обращение №1042'), findsOneWidget);
    });
  });

  group('текст статьи (ADR 0024 п. 7)', () {
    test('превью в списке — без разметки Markdown', () {
      expect(markdownPreview('# Как обновить карты\n\nТекст'), 'Как обновить карты');
      expect(markdownPreview('\n- **Шаг 1:** откройте [меню](https://x.by)'), 'Шаг 1: откройте меню');
      expect(markdownPreview('---\n\n> Важно'), 'Важно');
    });

    testWidgets('Markdown — заголовки и списки без символов разметки', (tester) async {
      await tester.pumpWidget(MaterialApp(
        theme: evTheme(Brightness.light),
        home: const ArticleScreen(
          article: KnowledgeArticle(
            id: 1,
            vehicleModelId: null,
            articleType: ArticleType.guide,
            title: 'Карты',
            content: '## Обновление\n\n1. Откройте **Настройки**\n2. Нажмите [Обновить](https://example.by)\n\n'
                '![схема](https://example.by/a.png)',
          ),
        ),
      ));
      await tester.pumpAndSettle();
      expect(find.text('Обновление'), findsOneWidget);
      expect(find.textContaining('## '), findsNothing);
      expect(find.textContaining('**'), findsNothing);
      expect(find.byType(Image), findsNothing, reason: 'картинки в v1 не показываются');
    });
  });
}
