// #111 (ADR 0031): повтор отправки после обрыва связи не создаёт дубль. Сервер записал обращение или
// сообщение, а ответ до клиента не дошёл («Нет подключения к интернету», текст остаётся в поле); повтор
// того же черновика уходит с тем же ключом client_request_id, и сервер отвечает уже записанным.
import 'dart:math';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:ev_servicedesk/data/models.dart';
import 'package:ev_servicedesk/data/prototype_repository.dart';
import 'package:ev_servicedesk/data/repository.dart';
import 'package:ev_servicedesk/data/retry_key.dart';
import 'package:ev_servicedesk/main.dart';

final _uuidV4 = RegExp(r'^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$');

/// Сервер прототипа, который теряет ответ на следующую отправку: запись сделана, клиенту — обрыв связи.
class _LossyRepo extends PrototypeRepository {
  _LossyRepo() : super(latency: Duration.zero);

  bool loseNextResponse = false;
  final keys = <String?>[];

  Future<T> _maybeLose<T>(T result) async {
    if (!loseNextResponse) return result;
    loseNextResponse = false;
    throw const OfflineException();
  }

  @override
  Future<Ticket> createTicket(TicketDraft draft) async {
    keys.add(draft.clientRequestId);
    return _maybeLose(await super.createTicket(draft));
  }

  @override
  Future<TicketMessage> sendMessage(int ticketId, String body,
      {List<UploadedAttachment> attachments = const [], String? clientRequestId}) async {
    keys.add(clientRequestId);
    return _maybeLose(
        await super.sendMessage(ticketId, body, attachments: attachments, clientRequestId: clientRequestId));
  }
}

Future<_LossyRepo> _pump(WidgetTester tester) async {
  tester.view.physicalSize = const Size(393, 852);
  tester.view.devicePixelRatio = 1;
  addTearDown(tester.view.reset);
  final repo = _LossyRepo();
  await tester.pumpWidget(EvServiceDeskApp(repository: repo, signedIn: true));
  await tester.pumpAndSettle();
  await tester.tap(find.descendant(of: find.byType(NavigationBar), matching: find.text('Поддержка')));
  await tester.pumpAndSettle();
  return repo;
}

Future<void> _tap(WidgetTester tester, Finder finder) async {
  await tester.ensureVisible(finder);
  await tester.pumpAndSettle();
  await tester.tap(finder);
  await tester.pumpAndSettle();
}

/// Сообщение об ошибке закрывает поле ввода снизу — повтор после того, как оно скрылось.
Future<void> _waitSnackGone(WidgetTester tester) async {
  await tester.pump(const Duration(seconds: 10));
  await tester.pumpAndSettle();
  expect(find.byType(SnackBar), findsNothing);
}

void main() {
  group('RetryKey', () {
    test('тот же черновик — тот же ключ; другой черновик или после отправки — новый', () {
      final retry = RetryKey(random: Random(1));
      final first = retry.forDraft('Нет звука');
      expect(first, matches(_uuidV4));
      expect(retry.forDraft('Нет звука'), first);
      final edited = retry.forDraft('Нет звука в колонках');
      expect(edited, isNot(first));
      retry.reset();
      expect(retry.forDraft('Нет звука в колонках'), isNot(edited));
    });

    test('UUID версии 4 из криптостойкого генератора', () {
      final ids = {for (var i = 0; i < 100; i++) newRequestId()};
      expect(ids, hasLength(100));
      expect(ids, everyElement(matches(_uuidV4)));
    });
  });

  testWidgets('чат: ответ потерян — повтор с тем же ключом, сообщение одно', (tester) async {
    final repo = await _pump(tester);
    await _tap(tester, find.text('Обращения'));
    await _tap(tester, find.byKey(const Key('ticket-1042')));
    const text = 'Перезагрузил, не помогло';
    await tester.enterText(find.byKey(const Key('message')), text);
    repo.loseNextResponse = true;
    await _tap(tester, find.byKey(const Key('send')));
    // Ошибка — над полем ввода (#105): всплывающее сообщение закрывало «Отправить», повторить было нельзя.
    expect(find.byType(SnackBar), findsNothing);
    expect(find.text('Не отправлено. Нет подключения к интернету. Попробуйте позже'), findsOneWidget);
    expect(find.text(text), findsOneWidget, reason: 'текст остался в поле');

    await _tap(tester, find.byKey(const Key('send')));
    expect(repo.keys, hasLength(2));
    expect(repo.keys.first, matches(_uuidV4));
    expect(repo.keys.last, repo.keys.first);
    expect(find.text(text), findsOneWidget, reason: 'в переписке, поле очищено');
    expect(find.byKey(const Key('send-error')), findsNothing, reason: 'ошибка снята после отправки');

    // Переписка с «сервера» — сообщение записано один раз.
    await _tap(tester, find.byType(BackButton));
    await _tap(tester, find.byKey(const Key('ticket-1042')));
    expect(find.text(text), findsOneWidget);

    // Следующее сообщение — новый черновик и новый ключ, даже с тем же текстом.
    await tester.enterText(find.byKey(const Key('message')), text);
    await _tap(tester, find.byKey(const Key('send')));
    expect(repo.keys.last, isNot(repo.keys.first));
    expect(find.text(text), findsNWidgets(2));
  });

  testWidgets('новое обращение: ответ потерян — повтор с тем же ключом, обращение одно', (tester) async {
    final repo = await _pump(tester);
    await _tap(tester, find.byKey(const Key('new-ticket')));
    await _tap(tester, find.byKey(const Key('vehicle-101')));
    await _tap(tester, find.byKey(const Key('category-audio')));
    await tester.enterText(find.byKey(const Key('description')), 'Нет звука');
    repo.loseNextResponse = true;
    await _tap(tester, find.byKey(const Key('submit-ticket')));
    expect(find.text('Нет подключения к интернету. Попробуйте позже'), findsOneWidget);
    await _waitSnackGone(tester);

    await _tap(tester, find.byKey(const Key('submit-ticket')));
    expect(repo.keys, hasLength(2));
    expect(repo.keys.last, repo.keys.first);
    expect(find.text('Обращение №1100 создано. Инженер ответит в чате'), findsOneWidget);

    await _tap(tester, find.byType(BackButton));
    await _tap(tester, find.text('Обращения'));
    expect(find.text('Нет звука'), findsOneWidget, reason: 'на «сервере» одно обращение');
  });
}
