// E2E клиента на уровне API (глава 18, ADR 0022 п. 2): настоящий HttpClientRepository против стека backend из
// образа-кандидата. Сценарий чек-листа «регистрация → добавление авто → просмотр карточки» плюс сессия:
// восстановление по refresh-токену, выход, отзыв согласия.
// Запуск: scripts/integration_stack.sh backend:smoke -- bash -c 'cd mobile && flutter test test_api_e2e'
// (окружение API_BASE_URL, E2E_PHONE, E2E_CODE задаёт стек; без него тест пропускается).
import 'dart:io';
import 'dart:math';

import 'package:flutter_test/flutter_test.dart';

import 'package:ev_servicedesk/data/api/api_client.dart';
import 'package:ev_servicedesk/data/api/token_store.dart';
import 'package:ev_servicedesk/data/http_repository.dart';
import 'package:ev_servicedesk/data/models.dart';
import 'package:ev_servicedesk/data/repository.dart';

final _env = Platform.environment;
final _baseUrl = _env['API_BASE_URL'] ?? '';
final _phone = _env['E2E_PHONE'] ?? '';
final _code = _env['E2E_CODE'] ?? '';

/// VIN, который мок-декодер распознаёт как Zeekr 001 (ADR 0014); хвост случайный — стек может быть не пустым.
String _zeekrVin() {
  final random = Random();
  return 'L6TZ001${List.generate(10, (_) => random.nextInt(10)).join()}';
}

HttpClientRepository _repository(TokenStore tokens) =>
    HttpClientRepository(ApiClient(baseUrl: Uri.parse(_baseUrl), tokens: tokens));

void main() {
  final skip = _baseUrl.isEmpty || _phone.isEmpty || _code.isEmpty
      ? 'нет API_BASE_URL/E2E_PHONE/E2E_CODE — запускается из scripts/integration_stack.sh'
      : null;

  test('регистрация → авто → карточка → сессия', skip: skip, timeout: const Timeout(Duration(minutes: 3)), () async {
    final tokens = MemoryTokenStore();
    final repo = _repository(tokens);
    var sessionEnded = 0;
    repo.onSessionEnded = () => sessionEnded++;

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
    expect(await repo.maintenanceRecords(vehicle.id), isEmpty);

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
    stale.onSessionEnded = () => staleEnded++;
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
}
