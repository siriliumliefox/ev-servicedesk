// Чат в реальном времени (ADR 0024 п. 8, docs/asyncapi.yaml 1.1.1): первый кадр auth, догрузка после ready,
// кадры message.created / ticket.updated, переподключение, 4401 — новый токен, 4403 — стоп, пауза в фоне.
import 'dart:async';
import 'dart:convert';

import 'package:flutter_test/flutter_test.dart';

import 'package:ev_servicedesk/data/models.dart';
import 'package:ev_servicedesk/data/repository.dart';
import 'package:ev_servicedesk/data/ticket_live.dart';

class _FakeSocket implements LiveSocket {
  final sent = <Map<String, Object?>>[];
  final _frames = StreamController<Object?>();

  @override
  int? closeCode;

  @override
  Stream<Object?> get frames => _frames.stream;

  @override
  void send(String data) => sent.add(jsonDecode(data) as Map<String, Object?>);

  void frame(Map<String, Object?> f) => _frames.add(jsonEncode(f));

  /// Сервер закрыл соединение с кодом.
  Future<void> serverClose(int code) async {
    closeCode = code;
    await _frames.close();
  }

  @override
  Future<void> close() async {
    if (!_frames.isClosed) await _frames.close();
  }
}

Map<String, Object?> _messageJson(int id, {String role = 'engineer'}) => {
      'id': id,
      'ticket_id': 7,
      'author': {'id': 2, 'role': role},
      'body': 'Сообщение $id',
      'attachments': <Object?>[],
      'created_at': '2026-10-13T10:00:00Z',
    };

Map<String, Object?> _ticketJson(String status) => {
      'id': 7,
      'vehicle_id': 1,
      'category': 'navigation',
      'status': status,
      'summary': 'Навигация',
      'created_at': '2026-10-13T09:00:00Z',
      'sla_due_at': '2026-10-13T17:00:00Z',
      'is_overdue': false,
      'vehicle_model': {'brand': 'Zeekr', 'model': '001'},
    };

TicketMessage _message(int id) => TicketMessage(
      id: id,
      fromClient: false,
      authorName: 'Инженер поддержки',
      body: 'Сообщение $id',
      createdAt: DateTime(2026, 10, 13),
    );

Ticket _ticket(TicketStatus status) => Ticket(
      id: 7,
      vehicleId: 1,
      category: TicketCategory.navigation,
      status: status,
      summary: 'Навигация',
      createdAt: DateTime(2026, 10, 13),
    );

class _Harness {
  final sockets = <_FakeSocket>[];
  final afterIds = <int>[];
  final tokenCalls = <String?>[];
  var token = 'access-1';
  var missed = <TicketMessage>[];
  var status = TicketStatus.inProgress;
  Object? connectError;
  final delays = <int>[];

  WsTicketLive start({int afterId = 10}) => WsTicketLive(
        url: Uri.parse('ws://api.test/v1/tickets/7/ws'),
        connect: (_) async {
          final error = connectError;
          if (error != null) {
            connectError = null;
            throw error;
          }
          final s = _FakeSocket();
          sockets.add(s);
          return s;
        },
        accessToken: ({String? stale}) async {
          tokenCalls.add(stale);
          if (stale != null) token = 'access-${tokenCalls.length}';
          return token;
        },
        messagesAfter: (after) async {
          afterIds.add(after);
          final result = missed;
          missed = [];
          return result;
        },
        ticket: () async => _ticket(status),
        afterId: afterId,
        delay: (attempt) {
          delays.add(attempt);
          return Duration.zero;
        },
      );
}

Future<void> _settle() => Future<void>.delayed(const Duration(milliseconds: 10));

void main() {
  test('auth первым кадром → ready → догрузка после курсора REST → live; кадры сообщений и статуса', () async {
    final h = _Harness()..missed = [_message(11), _message(12)];
    final live = h.start();
    final events = <TicketLiveEvent>[];
    live.events.listen(events.add);
    await _settle();

    expect(h.sockets, hasLength(1));
    expect(h.sockets.single.sent.single, {'type': 'auth', 'access_token': 'access-1'});
    expect(live.state.value, LiveState.connecting);

    h.sockets.single.frame({'type': 'ready'});
    await _settle();
    expect(h.afterIds, [10], reason: 'курсор — последнее сообщение, загруженное экраном');
    expect(live.state.value, LiveState.live);
    expect([for (final e in events.whereType<LiveMessage>()) e.message.id], [11, 12]);
    expect(events.whereType<LiveTicket>().single.ticket.status, TicketStatus.inProgress);

    h.sockets.single.frame({'type': 'message.created', 'data': _messageJson(13)});
    h.sockets.single.frame({'type': 'ticket.updated', 'data': _ticketJson('resolved')});
    await _settle();
    expect(events.whereType<LiveMessage>().last.message.id, 13);
    expect(events.whereType<LiveTicket>().last.ticket.status, TicketStatus.resolved);
    await live.close();
  });

  test('обрыв — переподключение; курсор догрузки — из REST, не из кадров сокета', () async {
    final h = _Harness()..missed = [_message(11)];
    final live = h.start();
    await _settle();
    h.sockets.single.frame({'type': 'ready'});
    await _settle();
    h.sockets.single.frame({'type': 'message.created', 'data': _messageJson(20)});
    await _settle();

    await h.sockets.single.serverClose(1011);
    await _settle();
    expect(h.sockets, hasLength(2));
    expect(live.state.value, LiveState.connecting);
    h.sockets.last.frame({'type': 'ready'});
    await _settle();
    expect(h.afterIds, [10, 11], reason: 'id 20 пришёл кадром — повторно его отбросит экран');
    expect(live.state.value, LiveState.live);
    await live.close();
  });

  test('4401 — новый access-токен и сразу заново; второй 4401 подряд — уже с паузой', () async {
    final h = _Harness();
    final live = h.start();
    await _settle();
    await h.sockets.single.serverClose(4401);
    await _settle();
    expect(h.tokenCalls, [null, 'access-1'], reason: 'отклонённый токен передан для обновления');
    expect(h.sockets, hasLength(2));
    expect(h.sockets.last.sent.single['access_token'], isNot('access-1'));
    expect(h.delays, isEmpty, reason: 'без паузы');

    await h.sockets.last.serverClose(4401);
    await _settle();
    expect(h.delays, isNotEmpty);
    await live.close();
  });

  test('4403 — доступа нет: стоп без переподключения', () async {
    final h = _Harness();
    final live = h.start();
    await _settle();
    await h.sockets.single.serverClose(4403);
    await _settle();
    expect(live.state.value, LiveState.stopped);
    expect(h.sockets, hasLength(1));
    await live.close();
  });

  test('сессия завершена (refresh отклонён) — стоп', () async {
    final h = _Harness();
    final live = WsTicketLive(
      url: Uri.parse('ws://api.test/v1/tickets/7/ws'),
      connect: (_) async => _FakeSocket(),
      accessToken: ({String? stale}) async => throw const ApiException('UNAUTHORIZED', 'Сессия завершена'),
      messagesAfter: (_) async => [],
      ticket: () async => _ticket(TicketStatus.newTicket),
      afterId: 0,
      delay: (a) {
        h.delays.add(a);
        return Duration.zero;
      },
    );
    await _settle();
    expect(live.state.value, LiveState.stopped);
    expect(h.delays, isEmpty);
    await live.close();
  });

  test('нет сети при подключении — пауза и повтор; серия неудач сбрасывается после ready', () async {
    final h = _Harness()..connectError = const OfflineException();
    final live = h.start();
    await _settle();
    expect(h.delays, [0]);
    expect(h.sockets, hasLength(1));
    h.sockets.single.frame({'type': 'ready'});
    await _settle();
    await h.sockets.single.serverClose(1013);
    await _settle();
    expect(h.delays, [0, 0], reason: 'после ready — снова первая (короткая) пауза');
    await live.close();
  });

  test('пауза 1, 2, 4 … 30 с', () {
    expect([for (var i = 0; i < 7; i++) reconnectDelay(i).inSeconds], [1, 2, 4, 8, 16, 30, 30]);
  });

  test('приложение свёрнуто — сокет закрыт; на экране — переподключение и догрузка', () async {
    final h = _Harness();
    final live = h.start();
    await _settle();
    h.sockets.single.frame({'type': 'ready'});
    await _settle();

    live.pause();
    await _settle();
    expect(h.sockets, hasLength(1));
    h.missed = [_message(11)];
    final events = <TicketLiveEvent>[];
    live.events.listen(events.add);
    live.resume();
    await _settle();
    expect(h.sockets, hasLength(2));
    h.sockets.last.frame({'type': 'ready'});
    await _settle();
    expect(events.whereType<LiveMessage>().single.message.id, 11);
    await live.close();
  });
}
