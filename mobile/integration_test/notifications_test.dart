// UI E2E главы 23 (ADR 0027 п. 15: E2E-11, E2E-12): центр уведомлений клиента против стека backend. До теста
// backend/scripts/e2e_support.py notify заводит клиента E2E_NOTIFY_PHONE с Zeekr 001, у которого подходит замена
// масла редуктора, запускает worker напоминаний и публикует прошивку RU 3.0.0 для модели (docs/specs/support_flow.json,
// раздел notifications). Клиент входит по SMS-коду и видит в центре уведомлений прошивку и напоминание о ТО;
// напоминание ведёт к записи на ТО по этому авто.
// Запуск: mobile/scripts/e2e_ui.sh (iOS Simulator), в CI — Android-эмулятор (mobile-ui-e2e.yml).
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:integration_test/integration_test.dart';

import 'package:ev_servicedesk/data/api/token_store.dart';
import 'package:ev_servicedesk/main.dart';
import 'package:ev_servicedesk/screens/support/ticket_create_screen.dart';

import 'support.dart';

const _phone = String.fromEnvironment('E2E_NOTIFY_PHONE');
const _code = String.fromEnvironment('E2E_CODE');

// docs/specs/support_flow.json → notifications: версия прошивки и агрегат напоминания.
const _firmware = 'прошивка RU 3.0.0';
const _reminderAggregate = 'Масло редуктора';

void main() {
  IntegrationTestWidgetsFlutterBinding.ensureInitialized();
  WidgetController.hitTestWarningShouldBeFatal = true;

  testWidgets('центр уведомлений: прошивка и напоминание о ТО → запись на ТО', (tester) async {
    expect(apiBaseUrl, isNotEmpty, reason: 'нужен --dart-define=API_BASE_URL');
    expect(_phone, startsWith('+375'), reason: 'нужен --dart-define=E2E_NOTIFY_PHONE');
    await (await SecureTokenStore.open()).clear();
    await tester.pumpWidget(EvServiceDeskApp(repository: await createRepository()));

    // Вход клиентом, которого завёл e2e_support.py notify: авто уже есть — сразу главный экран.
    await requestCode(tester, _phone); // seed только что запрашивал код этого номера
    await tester.enterText(find.byKey(const Key('code')), _code);
    await tapLikeUser(tester, find.descendant(of: find.byKey(const Key('consent')), matching: find.byType(Checkbox)));
    await tapLikeUser(tester, find.text('Войти'));
    await waitFor(tester, find.byKey(const Key('open-vehicle-card')));

    // Центр уведомлений: прошивка для модели авто (C-10) и напоминание о ТО (C-11).
    await tapLikeUser(tester, find.byKey(const Key('notification-bell')).first);
    await waitForAny(tester, [find.textContaining(_firmware)]);
    expect(find.textContaining(_reminderAggregate), findsWidgets);

    // Фильтр «Регламент ТО» оставляет только напоминания.
    await tapLikeUser(tester, find.byKey(const Key('filter-maintenance')));
    await tester.pump(const Duration(milliseconds: 500));
    expect(find.textContaining(_firmware), findsNothing);
    await waitFor(tester, find.textContaining(_reminderAggregate));

    // Напоминание → «Записаться на ТО» → форма записи по этому авто.
    await tapLikeUser(tester, find.textContaining(_reminderAggregate).first);
    await waitFor(tester, find.byKey(const Key('book-maintenance')));
    await tapLikeUser(tester, find.byKey(const Key('book-maintenance')));
    await waitFor(tester, find.byType(TicketCreateScreen));
  });
}
