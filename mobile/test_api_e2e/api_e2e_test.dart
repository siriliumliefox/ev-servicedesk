// E2E клиента на уровне API (глава 18, ADR 0022 п. 2): настоящий HttpClientRepository против стека backend из
// образа-кандидата. Сценарий чек-листа «регистрация → добавление авто → просмотр карточки» плюс сессия:
// восстановление по refresh-токену, выход, отзыв согласия. Схема агрегатов (глава 19, ADR 0023 п. 7): статусы
// 5 тестовых авто в клиенте совпадают с таблицей docs/specs/scheme_test_vehicles.json. Глава 20 (ADR 0024 п. 1):
// «дерево решений → эскалация → тикет с фото → ответ инженера в чате» по WebSocket, новости и акции, push-токен;
// данные — docs/specs/support_flow.json, действия персонала — backend/scripts/e2e_support.py.
// Запуск: scripts/integration_stack.sh backend:smoke -- bash -c \
//   '(cd backend && poetry run python scripts/seed_scheme_vehicles.py &&
//     poetry run python scripts/e2e_support.py seed) && cd mobile && flutter test test_api_e2e'
// (окружение API_BASE_URL, E2E_PHONE, E2E_CODE, E2E_SCHEME_PHONE, E2E_SUPPORT_PHONE, E2E_JOB_RUNNER задаёт стек;
// без него тест пропускается).
import 'dart:convert';
import 'dart:io';
import 'dart:math';

import 'package:flutter_test/flutter_test.dart';

import 'package:ev_servicedesk/data/api/api_client.dart';
import 'package:ev_servicedesk/data/api/token_store.dart';
import 'package:ev_servicedesk/data/http_repository.dart';
import 'package:ev_servicedesk/data/models.dart';
import 'package:ev_servicedesk/data/repository.dart';
import 'package:ev_servicedesk/data/ticket_live.dart';

final _env = Platform.environment;
final _baseUrl = _env['API_BASE_URL'] ?? '';
final _phone = _env['E2E_PHONE'] ?? '';
final _code = _env['E2E_CODE'] ?? '';
final _schemePhone = _env['E2E_SCHEME_PHONE'] ?? '';
final _supportPhone = _env['E2E_SUPPORT_PHONE'] ?? '';

/// Действие персонала на стеке (backend/scripts/e2e_support.py): публикация, ответ инженера.
Future<void> _staff(List<String> args) async {
  final r =
      await Process.run('poetry', ['run', 'python', 'scripts/e2e_support.py', ...args], workingDirectory: '../backend');
  expect(r.exitCode, 0, reason: 'e2e_support.py ${args.join(' ')}\n${r.stdout}${r.stderr}');
}

/// JPEG 1×1 — настоящая картинка: в чате клиента и у инженера она откроется.
final _jpeg = base64Decode(
  '/9j/4AAQSkZJRgABAQEASABIAAD/2wBDAP//////////////////////////////////////////////////////////////////////////////'
  '////////wgALCAABAAEBAREA/8QAFBABAAAAAAAAAAAAAAAAAAAAAP/aAAgBAQABPxA=',
);

/// VIN, который мок-декодер распознаёт как Zeekr 001 (ADR 0014); хвост случайный — стек может быть не пустым.
String _zeekrVin() {
  final random = Random();
  return 'L6TZ001${List.generate(10, (_) => random.nextInt(10)).join()}';
}

HttpClientRepository _repository(TokenStore tokens) =>
    HttpClientRepository(ApiClient(baseUrl: Uri.parse(_baseUrl), tokens: tokens));

/// Запрос кода с паузой между запросами (429 + Retry-After): номер мог только что запрашивать код другой шаг стека.
Future<void> _requestCode(HttpClientRepository repo, String phone) async {
  try {
    await repo.requestCode(phone);
  } on ApiException catch (e) {
    if (e.code != 'RATE_LIMITED') rethrow;
    await Future<void>.delayed(e.retryAfter! + const Duration(seconds: 1));
    await repo.requestCode(phone);
  }
}

void main() {
  final skip = _baseUrl.isEmpty || _phone.isEmpty || _code.isEmpty
      ? 'нет API_BASE_URL/E2E_PHONE/E2E_CODE — запускается из scripts/integration_stack.sh'
      : null;
  final schemeSkip =
      _schemePhone.isEmpty ? 'нет E2E_SCHEME_PHONE — 5 тестовых авто создаёт seed_scheme_vehicles.py' : null;

  test('регистрация → авто → карточка → сессия', skip: skip, timeout: const Timeout(Duration(minutes: 3)), () async {
    final tokens = MemoryTokenStore();
    final repo = _repository(tokens);
    var sessionEnded = 0;
    repo.sessionEnded.listen((_) => sessionEnded++);

    // Регистрация: без согласия ПД — 422 PD_CONSENT_REQUIRED, код не расходуется (контракт).
    expect(await repo.requestCode(_phone), greaterThan(0));
    await expectLater(
      repo.verifyCode(_phone, _code),
      throwsA(isA<ApiException>().having((e) => e.code, 'code', 'PD_CONSENT_REQUIRED')),
    );
    await repo.verifyCode(_phone, _code, pdPolicyVersion: '2026-10');
    expect(await tokens.read(), isNotNull, reason: 'refresh-токен сохранён');
    expect((await repo.me()).phone, _phone);
    expect(await repo.vehicles(), isEmpty);

    // Добавление авто по VIN: модель определил декодер; повтор — 409 VIN_ALREADY_ADDED.
    final vin = _zeekrVin();
    final vehicle = await repo.addVehicle(vin);
    expect(vehicle.vin, vin);
    expect(vehicle.vehicleModel.title, 'Zeekr 001');
    await expectLater(
      repo.addVehicle(vin),
      throwsA(isA<ApiException>().having((e) => e.code, 'code', 'VIN_ALREADY_ADDED')),
    );
    final models = await repo.vehicleModels();
    expect(models.map((m) => m.id), contains(vehicle.vehicleModel.id), reason: 'Vehicle.vehicle_model_id');

    // Главный экран: список авто, статусы агрегатов.
    expect((await repo.vehicles()).map((v) => v.id), [vehicle.id]);
    final statuses = await repo.aggregateStatuses(vehicle.id);
    expect(statuses, isNotEmpty);
    expect(statuses.every((s) => s.status == AggregateStatus.unknown), isTrue, reason: 'замен ещё не было');

    // Карточка: пробег только вверх, история ТО постранично.
    final updated = await repo.updateMileage(vehicle.id, 12000);
    expect(updated.mileage, 12000);
    await expectLater(
      repo.updateMileage(vehicle.id, 11000),
      throwsA(isA<ApiException>().having((e) => e.code, 'code', 'MILEAGE_DECREASE')),
    );
    final history = await repo.maintenanceRecordsPage(vehicle.id);
    expect(history.items, isEmpty);
    expect(history.hasMore, isFalse);
    expect((await repo.maintenanceRecordsPage(vehicle.id, aggregateTypeCode: 'gearbox_oil')).items, isEmpty);

    // Остальные разделы на реальном API (ADR 0022 п. 5): статьи модели, тикеты, уведомления.
    await repo.articles(vehicle.vehicleModel.id, ArticleType.troubleshooting);
    final ticket = await repo.createTicket(TicketDraft(
      vehicleId: vehicle.id,
      category: TicketCategory.navigation,
      description: 'Навигация не строит маршрут после обновления',
    ));
    expect((await repo.tickets()).map((t) => t.id), contains(ticket.id));
    final message = await repo.sendMessage(ticket.id, 'Дополнение: ошибка после перезагрузки');
    expect(message.fromClient, isTrue);
    expect((await repo.messages(ticket.id)).map((m) => m.id), contains(message.id));
    await repo.notifications();

    // Перезапуск приложения: access-токена в памяти нет — вход по сохранённому refresh без SMS.
    final restarted = _repository(tokens);
    expect(await restarted.restoreSession(), isTrue);
    expect((await restarted.vehicles()).map((v) => v.id), [vehicle.id]);

    // Выход с устройства: токен стёрт, старый refresh сервер больше не принимает.
    final staleRefresh = await tokens.read();
    await restarted.signOut();
    expect(await tokens.read(), isNull);
    final stale = _repository(MemoryTokenStore(staleRefresh));
    var staleEnded = 0;
    stale.sessionEnded.listen((_) => staleEnded++);
    await expectLater(
      stale.vehicles(),
      throwsA(isA<ApiException>().having((e) => e.code, 'code', 'UNAUTHORIZED')),
    );
    expect(staleEnded, 1, reason: 'отклонённый refresh завершает сессию');
    expect(sessionEnded, 0);

    // Повторный вход (согласие уже действует): новый код — после паузы между запросами (429 + Retry-After).
    final limited =
        await repo.requestCode(_phone).then<ApiException?>((_) => null, onError: (Object e) => e as ApiException);
    if (limited != null) {
      expect(limited.code, 'RATE_LIMITED');
      expect(limited.message, startsWith('Слишком много попыток. Повторите через'));
      await Future<void>.delayed(limited.retryAfter! + const Duration(seconds: 1));
      await repo.requestCode(_phone);
    }
    await repo.verifyCode(_phone, _code);

    // Отзыв согласия на обработку ПД завершает все сессии пользователя.
    await repo.withdrawPdConsent();
    expect(await tokens.read(), isNull);
  });

  test('схема агрегатов: 5 тестовых авто — статусы клиента совпадают с таблицей',
      skip: skip ?? schemeSkip, timeout: const Timeout(Duration(minutes: 3)), () async {
    final table =
        jsonDecode(File('../docs/specs/scheme_test_vehicles.json').readAsStringSync()) as Map<String, dynamic>;
    final repo = _repository(MemoryTokenStore());
    await _requestCode(repo, _schemePhone);
    await repo.verifyCode(_schemePhone, _code); // согласие ПД дал seed

    final vehicles = {for (final v in await repo.vehicles()) v.vin: v};
    final cars = (table['vehicles'] as List).cast<Map<String, dynamic>>();
    expect(vehicles.keys.toSet(), cars.map((c) => c['vin']).toSet());
    for (final car in cars) {
      final vehicle = vehicles[car['vin']]!;
      expect(vehicle.vehicleModel.title, car['model'], reason: car['title'] as String);
      final expected = (car['aggregates'] as Map).cast<String, Map<String, dynamic>>();
      final actual = {for (final s in await repo.aggregateStatuses(vehicle.id)) s.aggregateTypeCode: s};
      expect(actual.keys.toSet(), expected.keys.toSet(), reason: car['title'] as String);
      for (final MapEntry(key: code, value: want) in expected.entries) {
        final got = actual[code]!;
        final where = '${car['title']}: $code';
        expect(got.status.name, want['status'], reason: where);
        if (want.containsKey('percentage')) expect(got.percentage, want['percentage'], reason: where);
        // История агрегата: у заменённого — запись вида «замена», у нового авто — пусто.
        final history = await repo.maintenanceRecordsPage(vehicle.id, aggregateTypeCode: code);
        expect(history.items.map((r) => r.kind),
            want.containsKey('replaced_mileage') ? [MaintenanceKind.replacement] : isEmpty,
            reason: where);
      }
    }
  });

  test('глава 20: дерево решений → эскалация → тикет с фото → ответ инженера в чате по WebSocket',
      skip: skip ?? (_supportPhone.isEmpty ? 'нет E2E_SUPPORT_PHONE' : null),
      timeout: const Timeout(Duration(minutes: 3)), () async {
    final flow = jsonDecode(File('../docs/specs/support_flow.json').readAsStringSync()) as Map<String, dynamic>;
    final trouble = flow['troubleshooting'] as Map<String, dynamic>;
    final repo = _repository(MemoryTokenStore());
    await _requestCode(repo, _supportPhone);
    await repo.verifyCode(_supportPhone, _code, pdPolicyVersion: '2026-10');
    final vehicle = await repo.addVehicle(_zeekrVin());

    // «Обучение»: общая статья видна авто любой модели, текст — Markdown.
    final guides = await repo.articles(vehicle.vehicleModel.id, ArticleType.guide);
    final guide = guides.firstWhere((a) => a.title == (flow['guide'] as Map)['title']);
    expect(guide.content, contains('## Как обновить'));

    // «Устранение неполадок»: проход по дереву до эскалации — как на экране.
    final articles = await repo.articles(vehicle.vehicleModel.id, ArticleType.troubleshooting);
    final article = articles.firstWhere((a) => a.title == trouble['title']);
    expect(article.category, TicketCategory.navigation);
    final nodes = {for (final n in await repo.decisionTree(article.id)) n.id: n};
    var node = nodes.values.singleWhere((n) => n.isRoot);
    for (final answer in (trouble['path_to_escalation'] as List).cast<String>()) {
      node = nodes[node.options.singleWhere((o) => o.label == answer).nextNodeId]!;
    }
    expect(node.isEscalation, isTrue);

    // Вложение: presign → PUT в MinIO стека → привязка к тикету при создании.
    final dir = await Directory.systemTemp.createTemp('ev-e2e');
    addTearDown(() => dir.delete(recursive: true));
    final photo = File('${dir.path}/screen.jpg')..writeAsBytesSync(_jpeg);
    final progress = <double>[];
    final attachment = await repo.uploadAttachment(
      LocalAttachment(path: photo.path, fileType: AttachmentType.photo, sizeBytes: _jpeg.length),
      onProgress: progress.add,
    );
    expect(progress.last, 1.0);
    final ticket = await repo.createTicket(TicketDraft(
      vehicleId: vehicle.id,
      category: article.category!,
      description: '${article.title}. Что уже пробовал(а): перезагрузка, геолокация',
      sourceArticleId: article.id,
      sourceNodeId: node.id,
      attachments: [attachment],
    ));
    // Описание и фото — в карточке тикета (чат показывает их первым сообщением), переписка начинается пустой.
    final detail = await repo.ticket(ticket.id);
    expect(detail.description, startsWith(article.title));
    expect(detail.attachments.single.fileType, AttachmentType.photo);
    expect(await repo.messages(ticket.id), isEmpty);
    final download = await HttpClient().getUrl(Uri.parse(detail.attachments.single.url!));
    final response = await download.close();
    expect(response.statusCode, 200, reason: 'фото скачивается по ссылке из ответа');
    expect(await response.fold<int>(0, (n, chunk) => n + chunk.length), _jpeg.length);

    // Чат в реальном времени: сокет на связи → инженер отвечает → сообщение приходит без запроса клиента.
    final live = repo.watchTicket(ticket.id, afterId: 0);
    addTearDown(live.close);
    final events = <TicketLiveEvent>[];
    final sub = live.events.listen(events.add);
    addTearDown(sub.cancel);
    Future<void> until(bool Function() ok, String what) async {
      for (var i = 0; i < 150 && !ok(); i++) {
        await Future<void>.delayed(const Duration(milliseconds: 100));
      }
      expect(ok(), isTrue, reason: what);
    }

    await until(() => live.state.value == LiveState.live, 'сокет авторизован (ready)');
    await _staff(['reply', '--ticket', '${ticket.id}']);
    await until(() => events.whereType<LiveMessage>().any((e) => !e.message.fromClient), 'ответ инженера по сокету');
    final reply = events.whereType<LiveMessage>().firstWhere((e) => !e.message.fromClient).message;
    expect(reply.body, flow['engineer_reply']);
    expect(reply.authorName, 'Инженер поддержки', reason: 'контакты сотрудника клиенту не отдаются');
    await until(() => events.whereType<LiveTicket>().any((e) => e.ticket.status == TicketStatus.inProgress),
        'тикет взят в работу — ticket.updated');

    // Ответ клиента с фото — в тот же чат.
    final again = await repo
        .uploadAttachment(LocalAttachment(path: photo.path, fileType: AttachmentType.photo, sizeBytes: _jpeg.length));
    final mine = await repo.sendMessage(ticket.id, 'Обновил карты — не помогло', attachments: [again]);
    expect(mine.attachments, hasLength(1));

    // Инженер решает тикет — статус приходит по сокету.
    await _staff(
        ['reply', '--ticket', '${ticket.id}', '--text', 'Проверили удалённо, всё работает', '--status', 'resolved']);
    await until(() => events.whereType<LiveTicket>().any((e) => e.ticket.status == TicketStatus.resolved),
        'решён — ticket.updated');

    // Догрузка после переподключения не теряет и не дублирует: вся переписка — по порядку id.
    final all = await repo.messages(ticket.id);
    expect(all.map((m) => m.id).toList(), [...all.map((m) => m.id)]..sort());
    expect(all, hasLength(3), reason: 'ответ инженера, ответ клиента, решение');

    // Центр уведомлений: новость и акция для клиента, появившегося до публикации.
    await repo.registerPushToken('e2e-${DateTime.now().microsecondsSinceEpoch}');
    await _staff(['publish']);
    final feed = await repo.notifications();
    expect(
        feed.where((n) => n.type.isNews).map((n) => n.type).toSet(), {NotificationType.news, NotificationType.promo});
    final news = feed.firstWhere((n) => n.type == NotificationType.news);
    await repo.markNotificationRead(news.id);
    expect((await repo.notifications()).firstWhere((n) => n.id == news.id).isRead, isTrue);
  });
}
