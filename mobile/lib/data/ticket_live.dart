// Чат по тикету в реальном времени (ADR 0024 п. 8; docs/asyncapi.yaml 1.1.1, ADR 0017 п. 9):
// WebSocket /v1/tickets/{id}/ws — первый кадр auth, после каждого ready догрузка по REST (after_id), затем
// message.created / ticket.updated. Доставка по сокету — не более одного раза: пропуски закрывает догрузка,
// повторы экран отбрасывает по id. Переподключение с паузой; 4401 — новый access-токен, 4403 — стоп,
// 4429 — пауза 60 с. Отдельного опроса нет.
import 'dart:async';
import 'dart:convert';
import 'dart:math';

import 'package:flutter/foundation.dart';
import 'package:web_socket_channel/web_socket_channel.dart';

import 'api/contract_json.dart';
import 'models.dart';
import 'repository.dart';

enum LiveState {
  /// Подключение или переподключение — на экране «Переподключаемся…».
  connecting,

  /// Сокет авторизован, пропущенное догружено.
  live,

  /// Доступа нет (4403) или сессия завершена — переподключения не будет.
  stopped,
}

sealed class TicketLiveEvent {
  const TicketLiveEvent();
}

/// Новое сообщение (кадр message.created или догрузка после ready).
class LiveMessage extends TicketLiveEvent {
  const LiveMessage(this.message);

  final TicketMessage message;
}

/// Тикет изменился (статус, исполнитель): кадр ticket.updated или GET /tickets/{id} после ready.
class LiveTicket extends TicketLiveEvent {
  const LiveTicket(this.ticket);

  final Ticket ticket;
}

abstract class TicketLive {
  Stream<TicketLiveEvent> get events;
  ValueListenable<LiveState> get state;

  /// Приложение свёрнуто — сокет закрывается (iOS всё равно оборвёт его в фоне).
  void pause();

  /// Приложение снова на экране — подключиться сразу, без паузы.
  void resume();

  Future<void> close();
}

/// Сокет, отделённый от web_socket_channel — для тестов с фейком.
abstract class LiveSocket {
  Stream<Object?> get frames;
  void send(String data);

  /// Код закрытия после завершения frames (WebSocket close code).
  int? get closeCode;
  Future<void> close();
}

typedef LiveConnector = Future<LiveSocket> Function(Uri url);

Future<LiveSocket> connectWebSocket(Uri url) async {
  final channel = WebSocketChannel.connect(url);
  await channel.ready;
  return _ChannelSocket(channel);
}

class _ChannelSocket implements LiveSocket {
  _ChannelSocket(this._channel);

  final WebSocketChannel _channel;

  @override
  Stream<Object?> get frames => _channel.stream;

  @override
  void send(String data) => _channel.sink.add(data);

  @override
  int? get closeCode => _channel.closeCode;

  @override
  Future<void> close() async => _channel.sink.close();
}

/// Пауза перед n-й попыткой переподключения подряд: 1, 2, 4 … 30 с.
Duration reconnectDelay(int attempt) => Duration(seconds: min(30, 1 << min(attempt, 5)));

class WsTicketLive implements TicketLive {
  WsTicketLive({
    required this.url,
    required this.connect,
    required this.accessToken,
    required this.messagesAfter,
    required this.ticket,
    required int afterId,
    this.delay = reconnectDelay,
    this.connectTimeout = const Duration(seconds: 20),
  }) : _afterId = afterId {
    unawaited(_run());
  }

  final Uri url;
  final LiveConnector connect;

  /// Access-токен; stale — токен, отклонённый сервером (4401): нужен новый.
  final Future<String> Function({String? stale}) accessToken;

  /// GET /tickets/{id}/messages?after_id= — все страницы.
  final Future<List<TicketMessage>> Function(int afterId) messagesAfter;

  /// GET /tickets/{id}.
  final Future<Ticket> Function() ticket;
  final Duration Function(int attempt) delay;
  final Duration connectTimeout;

  /// Курсор догрузки — максимальный id сообщения из REST, не из кадров сокета (AsyncAPI).
  int _afterId;

  final _events = StreamController<TicketLiveEvent>.broadcast();
  final _state = ValueNotifier(LiveState.connecting);
  LiveSocket? _socket;
  bool _closed = false;
  bool _paused = false;
  Completer<void>? _wake;

  @override
  Stream<TicketLiveEvent> get events => _events.stream;

  @override
  ValueListenable<LiveState> get state => _state;

  @override
  void pause() {
    if (_closed || _paused) return;
    _paused = true;
    unawaited(_socket?.close());
  }

  @override
  void resume() {
    if (_closed || !_paused) return;
    _paused = false;
    _wakeUp();
  }

  @override
  Future<void> close() async {
    if (_closed) return;
    _closed = true;
    _wakeUp();
    await _socket?.close();
    _state.value = LiveState.stopped;
    await _events.close();
  }

  void _wakeUp() {
    final wake = _wake;
    _wake = null;
    if (wake != null && !wake.isCompleted) wake.complete();
  }

  /// Пауза, которую прерывают resume() и close().
  Future<void> _sleep(Duration d) {
    final wake = _wake = Completer<void>();
    final timer = Timer(d, _wakeUp);
    return wake.future.whenComplete(timer.cancel);
  }

  Future<void> _run() async {
    var attempt = 0;
    String? stale;
    // 4401 после свежего токена — сразу заново один раз; повтор подряд (до ready) — уже с паузой.
    var authRetried = false;
    while (!_closed) {
      if (_paused) {
        await _sleep(const Duration(days: 1));
        attempt = 0;
        continue;
      }
      _setState(LiveState.connecting);
      String? token;
      int? code;
      try {
        token = await accessToken(stale: stale);
        stale = null;
        final socket = await connect(url).timeout(connectTimeout);
        _socket = socket;
        if (_closed || _paused) {
          await socket.close();
          continue;
        }
        socket.send(jsonEncode({'type': 'auth', 'access_token': token}));
        await for (final raw in socket.frames) {
          if (_closed) break;
          if (await _onFrame(raw)) {
            attempt = 0;
            authRetried = false;
          }
        }
        code = socket.closeCode;
      } on ApiException catch (e) {
        // Refresh отклонён — сессия завершена, приложение вернулось ко входу.
        if (e.code == 'UNAUTHORIZED') break;
      } on Object {
        // Нет сети, тайм-аут, сбой сервера — переподключение.
      }
      _socket = null;
      if (_closed || _paused) continue;
      if (code == 4403) break;
      if (code == 4401 && token != null) {
        stale = token; // следующая попытка — с новым токеном
        if (!authRetried) {
          authRetried = true;
          continue;
        }
      }
      _setState(LiveState.connecting);
      await _sleep(code == 4429 ? const Duration(seconds: 60) : delay(attempt++));
    }
    if (!_closed) _setState(LiveState.stopped);
  }

  /// true — сокет авторизован (ready): серия неудач прервана.
  Future<bool> _onFrame(Object? raw) async {
    final Map<String, Object?> frame;
    try {
      frame = jsonDecode(raw! as String) as Map<String, Object?>;
    } on Object {
      return false; // кадр не по контракту — пропускаем
    }
    switch (frame['type']) {
      case 'ready':
        await _sync();
        return true;
      case 'message.created':
        _emit(LiveMessage(parseTicketMessage(frame['data']! as Map<String, Object?>)));
      case 'ticket.updated':
        _emit(LiveTicket(parseTicket(frame['data']! as Map<String, Object?>)));
    }
    return false;
  }

  /// После ready — всё, что пришло, пока сокета не было. Не удалось — переподключение и повтор догрузки.
  Future<void> _sync() async {
    try {
      final missed = await messagesAfter(_afterId);
      for (final m in missed) {
        _afterId = max(_afterId, m.id);
        _emit(LiveMessage(m));
      }
      _emit(LiveTicket(await ticket()));
      _setState(LiveState.live);
    } on Object {
      await _socket?.close();
    }
  }

  void _emit(TicketLiveEvent e) {
    if (!_events.isClosed) _events.add(e);
  }

  void _setState(LiveState s) {
    if (!_closed) _state.value = s;
  }
}

/// Без сервера (прототип, тесты экранов): всегда «на связи», событий нет.
class OfflineTicketLive implements TicketLive {
  final _events = StreamController<TicketLiveEvent>.broadcast();
  final _state = ValueNotifier(LiveState.live);

  @override
  Stream<TicketLiveEvent> get events => _events.stream;

  @override
  ValueListenable<LiveState> get state => _state;

  /// Событие «с сервера» — для демонстрации и тестов.
  void add(TicketLiveEvent e) => _events.add(e);

  @override
  void pause() {}

  @override
  void resume() {}

  @override
  Future<void> close() => _events.close();
}
