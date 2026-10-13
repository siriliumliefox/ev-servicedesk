// HttpClientRepository, глава 20 (ADR 0024): вложения presign → PUT в S3 (Content-Type — для HEAD на сервере),
// привязка к тикету и сообщению, переписка постранично с after_id, push-токены и отметка открытия.
import 'dart:convert';
import 'dart:io';

import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';

import 'package:ev_servicedesk/data/api/api_client.dart';
import 'package:ev_servicedesk/data/api/token_store.dart';
import 'package:ev_servicedesk/data/http_repository.dart';
import 'package:ev_servicedesk/data/models.dart';
import 'package:ev_servicedesk/data/repository.dart';

http.Response _json(int status, Object body) =>
    http.Response.bytes(utf8.encode(jsonEncode(body)), status, headers: {'content-type': 'application/json'});

Map<String, Object?> _message(int id) => {
      'id': id,
      'ticket_id': 7,
      'author': {'id': 2, 'role': 'engineer'},
      'body': 'Ответ $id',
      'attachments': [
        {'file_url': 'http://s3.test/b/tickets/7/a.jpg?X-Amz-Signature=1', 'file_type': 'photo'},
      ],
      'created_at': '2026-10-13T10:00:00Z',
    };

void main() {
  late List<http.Request> requests;
  late Map<String, http.Response Function(http.Request)> routes;
  late HttpClientRepository repo;

  setUp(() async {
    requests = [];
    routes = {};
    final api = ApiClient(
      baseUrl: Uri.parse('http://api.test:8000'),
      tokens: MemoryTokenStore('refresh'),
      httpClient: MockClient((r) async {
        requests.add(r);
        if (r.url.path == '/v1/auth/refresh') {
          return _json(200, {'access_token': 'a', 'refresh_token': 'r', 'expires_in': 900});
        }
        final key = '${r.method} ${r.url.host == 's3.test' ? 's3' : r.url.path}';
        final route = routes[key];
        return route == null ? http.Response('', 204) : route(r);
      }),
    );
    repo = HttpClientRepository(api);
  });

  test('вложение: presign с именем и типом → PUT файла с Content-Type → ключ для привязки', () async {
    final dir = await Directory.systemTemp.createTemp('ev-upload');
    addTearDown(() => dir.delete(recursive: true));
    final file = File('${dir.path}/IMG_0001.mov')..writeAsBytesSync(List.filled(1000, 7));
    routes['POST /v1/uploads/presign'] = (_) => _json(201, {
          'upload_url': 'http://s3.test/b/uploads/5/x.mov?X-Amz-Signature=1',
          'file_url': 'uploads/5/x.mov',
          'expires_at': '2026-10-13T10:15:00Z',
        });
    routes['PUT s3'] = (_) => http.Response('', 200);

    final progress = <double>[];
    final attachment = await repo.uploadAttachment(
      LocalAttachment(path: file.path, fileType: AttachmentType.video, sizeBytes: 1000),
      onProgress: progress.add,
    );

    final presign = requests.firstWhere((r) => r.url.path == '/v1/uploads/presign');
    expect(jsonDecode(presign.body), {'file_name': 'IMG_0001.mov', 'file_type': 'video'});
    final put = requests.firstWhere((r) => r.method == 'PUT');
    expect(put.headers['Content-Type'], 'video/quicktime');
    expect(put.headers.containsKey('Authorization'), isFalse, reason: 'токен API в S3 не уходит');
    expect(put.bodyBytes, hasLength(1000));
    expect(progress.last, 1.0);
    expect(attachment.url, 'uploads/5/x.mov');
    expect(attachment.fileType, AttachmentType.video);
  });

  test('S3 отклонил загрузку — понятная ошибка, а не «что-то пошло не так»', () async {
    final dir = await Directory.systemTemp.createTemp('ev-upload');
    addTearDown(() => dir.delete(recursive: true));
    final file = File('${dir.path}/a.jpg')..writeAsBytesSync([1, 2, 3]);
    routes['POST /v1/uploads/presign'] = (_) => _json(201, {
          'upload_url': 'http://s3.test/b/uploads/5/a.jpg',
          'file_url': 'uploads/5/a.jpg',
          'expires_at': '2026-10-13T10:15:00Z',
        });
    routes['PUT s3'] = (_) => http.Response('<Error>SignatureDoesNotMatch</Error>', 403);
    await expectLater(
      repo.uploadAttachment(LocalAttachment(path: file.path, fileType: AttachmentType.photo, sizeBytes: 3)),
      throwsA(isA<ApiException>().having((e) => e.message, 'message', contains('Не удалось загрузить файл'))),
    );
  });

  test('тикет и сообщение уходят с загруженными вложениями (TicketAttachmentInput)', () async {
    routes['POST /v1/tickets'] = (_) => _json(201, {
          'id': 7,
          'vehicle_id': 1,
          'category': 'navigation',
          'status': 'new',
          'summary': 's',
          'created_at': '2026-10-13T10:00:00Z',
        });
    routes['POST /v1/tickets/7/messages'] = (_) => _json(201, _message(30));
    const photo = TicketAttachment(fileName: 'a.jpg', fileType: AttachmentType.photo, url: 'uploads/5/a.jpg');
    await repo.createTicket(const TicketDraft(
      vehicleId: 1,
      category: TicketCategory.navigation,
      description: 'Не строит маршрут',
      sourceArticleId: 3,
      sourceNodeId: 9,
      attachments: [photo],
    ));
    final message = await repo.sendMessage(7, 'Ещё фото', attachments: const [photo]);

    final create = jsonDecode(requests.firstWhere((r) => r.url.path == '/v1/tickets').body) as Map;
    expect(create['attachments'], [
      {'file_url': 'uploads/5/a.jpg', 'file_type': 'photo'},
    ]);
    expect(create['source_article_id'], 3);
    expect(create['source_node_id'], 9);
    final send = jsonDecode(requests.firstWhere((r) => r.url.path == '/v1/tickets/7/messages').body) as Map;
    expect(send['attachments'], hasLength(1));
    expect(message.attachments.single.url, startsWith('http://s3.test/'), reason: 'в ответе — ссылка на скачивание');
    expect(message.attachments.single.fileName, 'a.jpg', reason: 'имя без подписи URL');
  });

  test('переписка — все страницы; догрузка — after_id', () async {
    routes['GET /v1/tickets/7/messages'] = (r) {
      final page = int.parse(r.url.queryParameters['page']!);
      return _json(200, {
        'items': [_message(page * 10)],
        'meta': {'page': page, 'page_size': 100, 'total': 2, 'total_pages': 2},
      });
    };
    final all = await repo.messages(7, afterId: 5);
    expect(all.map((m) => m.id), [10, 20]);
    final gets = requests.where((r) => r.url.path == '/v1/tickets/7/messages').toList();
    expect(gets.map((r) => r.url.queryParameters['after_id']), ['5', '5']);
    expect(gets.map((r) => r.url.queryParameters['page']), ['1', '2']);
  });

  test('push: регистрация, удаление (токен в пути экранирован), отметка открытия с токеном', () async {
    await repo.registerPushToken('tok:en/1');
    await repo.unregisterPushToken('tok:en/1');
    await repo.markNotificationOpened(42, 'tok:en/1');
    final register = requests.firstWhere((r) => r.url.path == '/v1/push-tokens');
    expect(jsonDecode(register.body), {'token': 'tok:en/1'});
    final delete = requests.firstWhere((r) => r.method == 'DELETE');
    expect(delete.url.toString(), endsWith('/v1/push-tokens/tok%3Aen%2F1'));
    final opened = requests.firstWhere((r) => r.url.path == '/v1/notifications/42/opened');
    expect(jsonDecode(opened.body), {'token': 'tok:en/1'});
  });

  test('статьи без авто — только общие (без модели)', () async {
    routes['GET /v1/knowledge-articles'] = (_) => _json(200, {
          'items': [
            {'id': 1, 'vehicle_model_id': null, 'article_type': 'troubleshooting', 'title': 'Общая', 'content': ''},
            {'id': 2, 'vehicle_model_id': 5, 'article_type': 'troubleshooting', 'title': 'Модели', 'content': ''},
          ],
          'meta': {'page': 1, 'page_size': 100, 'total': 2, 'total_pages': 1},
        });
    expect((await repo.articles(null, ArticleType.troubleshooting)).map((a) => a.id), [1]);
    final get = requests.firstWhere((r) => r.url.path == '/v1/knowledge-articles');
    expect(get.url.queryParameters.containsKey('vehicle_model_id'), isFalse);
  });

  test('адрес WebSocket того же backend', () {
    final api = ApiClient(baseUrl: Uri.parse('https://api.example.by'), tokens: MemoryTokenStore());
    expect(api.webSocketUrl('/tickets/7/ws').toString(), 'wss://api.example.by/v1/tickets/7/ws');
  });
}
