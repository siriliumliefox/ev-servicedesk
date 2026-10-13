// UI E2E главы 20 (ADR 0024 п. 1): клиентский сценарий в симуляторе против стека backend — «Обучение» (Markdown),
// дерево решений → эскалация → тикет с фото (presign → MinIO стека) → ответ инженера приходит в чат по WebSocket →
// новость в центре уведомлений. Инженер — backend/scripts/e2e_support.py answer на Mac (запускает e2e_ui.sh):
// ждёт тикет из дерева, отвечает и публикует новость. Тексты — docs/specs/support_flow.json.
// Запуск: mobile/scripts/e2e_ui.sh.
import 'dart:convert';
import 'dart:io';
import 'dart:math';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:integration_test/integration_test.dart';

import 'package:ev_servicedesk/data/api/token_store.dart';
import 'package:ev_servicedesk/data/attachments.dart';
import 'package:ev_servicedesk/data/models.dart';
import 'package:ev_servicedesk/main.dart';

import 'support.dart';

const _phone = String.fromEnvironment('E2E_SUPPORT_PHONE');
const _code = String.fromEnvironment('E2E_CODE');

/// Системный выбор фото автотест нажать не может (ADR 0024 п. 9): «галерея» отдаёт настоящий JPEG.
class _JpegSource implements AttachmentSource {
  @override
  Future<LocalAttachment?> pick(AttachmentType type, {required bool camera}) async {
    final bytes = base64Decode(
      '/9j/4AAQSkZJRgABAQEASABIAAD/2wBDAP//////////////////////////////////////////////////////////////////////////////'
      '////////wgALCAABAAEBAREA/8QAFBABAAAAAAAAAAAAAAAAAAAAAP/aAAgBAQABPxA=',
    );
    final file = File('${Directory.systemTemp.path}/e2e-${DateTime.now().microsecondsSinceEpoch}.jpg')
      ..writeAsBytesSync(bytes);
    return LocalAttachment(path: file.path, fileType: AttachmentType.photo, sizeBytes: bytes.length);
  }
}

void main() {
  IntegrationTestWidgetsFlutterBinding.ensureInitialized();
  WidgetController.hitTestWarningShouldBeFatal = true;

  testWidgets('обучение → дерево решений → тикет с фото → ответ инженера в чате → новость', (tester) async {
    expect(apiBaseUrl, isNotEmpty, reason: 'нужен --dart-define=API_BASE_URL');
    expect(_phone, startsWith('+375'), reason: 'нужен --dart-define=E2E_SUPPORT_PHONE');
    await (await SecureTokenStore.open()).clear();
    await tester.pumpWidget(EvServiceDeskApp(repository: await createRepository(), attachmentSource: _JpegSource()));

    // Вход новым клиентом и авто по VIN.
    await waitFor(tester, find.text('Получить код'));
    await tester.enterText(find.byKey(const Key('phone')), _phone.substring(4));
    await tapLikeUser(tester, find.text('Получить код'));
    await waitFor(tester, find.byKey(const Key('code')));
    await tester.enterText(find.byKey(const Key('code')), _code);
    await tapLikeUser(tester, find.descendant(of: find.byKey(const Key('consent')), matching: find.byType(Checkbox)));
    await tapLikeUser(tester, find.text('Войти'));
    await waitFor(tester, find.byKey(const Key('vin')));
    final random = Random();
    await tester.enterText(
        find.byKey(const Key('vin')), 'L6TZ001${List.generate(10, (_) => random.nextInt(10)).join()}');
    await tapLikeUser(tester, find.text('Добавить'));
    await waitFor(tester, find.byKey(const Key('open-vehicle-card')));

    // «Обучение»: статья в Markdown — заголовки без символов разметки.
    await tapLikeUser(tester, find.descendant(of: find.byType(NavigationBar), matching: find.text('Обучение')));
    await waitFor(tester, find.text('Как обновить карты навигации'));
    await tapLikeUser(tester, find.text('Как обновить карты навигации'));
    await waitFor(tester, find.byKey(const Key('article-content')));
    expect(find.text('Как обновить'), findsOneWidget);
    expect(find.textContaining('## '), findsNothing);
    await tester.pageBack();
    await tester.pump(const Duration(milliseconds: 500));

    // «Поддержка» → дерево решений → эскалация.
    await tapLikeUser(tester, find.descendant(of: find.byType(NavigationBar), matching: find.text('Поддержка')));
    await waitFor(tester, find.text('Навигация не строит маршрут'));
    await tapLikeUser(tester, find.text('Навигация не строит маршрут'));
    await waitFor(tester, find.text('Нет'));
    await tapLikeUser(tester, find.text('Нет'));
    await waitFor(tester, find.text('Нет, не строится'));
    await tapLikeUser(tester, find.text('Нет, не строится'));
    await waitFor(tester, find.byKey(const Key('escalate')));
    await tapLikeUser(tester, find.byKey(const Key('escalate')));

    // Форма: категория и ход диагностики подставлены; фото загружается сразу после выбора.
    await waitFor(tester, find.byKey(const Key('submit-ticket')));
    expect(tester.widget<ChoiceChip>(find.byKey(const Key('category-navigation'))).selected, isTrue);
    await tapLikeUser(tester, find.byKey(const Key('attach')));
    await waitFor(tester, find.byKey(const Key('attach-photo-gallery')));
    await tester.tap(find.byKey(const Key('attach-photo-gallery')));
    await waitFor(tester, find.bySemanticsLabel(RegExp('Фото 1.*загружено')));
    await tapLikeUser(tester, find.byKey(const Key('submit-ticket')));

    // Чат: своё сообщение с фото, затем ответ инженера — без обновления экрана (WebSocket).
    await waitFor(tester, find.byKey(const Key('chat-messages')));
    expect(find.textContaining('Навигация не строит маршрут'), findsWidgets);
    await waitForAny(tester, [find.textContaining('Обновите карты по инструкции')],
        timeout: const Duration(seconds: 90));
    await waitFor(tester, find.descendant(of: find.byKey(const Key('chat-status')), matching: find.text('В работе')));
    expect(find.byKey(const Key('chat-reconnecting')), findsNothing);

    // Центр уведомлений: новость, опубликованная после регистрации клиента.
    await tester.pageBack();
    await tester.pump(const Duration(milliseconds: 500));
    await tapLikeUser(tester, find.byKey(const Key('notification-bell')).first);
    await waitForAny(tester, [find.text('Новый сервисный центр в Гомеле')], timeout: const Duration(seconds: 30));
    await tapLikeUser(tester, find.text('Новый сервисный центр в Гомеле'));
    await waitFor(tester, find.byKey(const Key('notification-title')));
  });
}
