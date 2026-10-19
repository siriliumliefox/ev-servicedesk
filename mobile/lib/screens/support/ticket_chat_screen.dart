// Чат по обращению (ADR 0024 п. 8): первым сообщением — само обращение (описание и вложения из карточки тикета:
// в переписку они не входят), дальше переписка по REST, новые сообщения и смена статуса — по WebSocket (TicketLive);
// повторы отбрасываются по id. Свёрнутое приложение закрывает сокет, возврат — переподключение и догрузка.
// Вложения — фото и видео (ADR 0024 п. 9).
import 'dart:async';

import 'package:flutter/material.dart';
import 'package:url_launcher/url_launcher.dart';

import '../../app/app_state.dart';
import '../../data/models.dart';
import '../../data/retry_key.dart';
import '../../data/ticket_live.dart';
import '../../theme/app_theme.dart';
import '../../ui/format.dart';
import '../../ui/info_note.dart';
import '../../ui/states.dart';
import 'attachment_tray.dart';
import 'support_screen.dart';

class TicketChatScreen extends StatefulWidget {
  const TicketChatScreen({super.key, required this.ticket, this.notice});

  /// Тикет из списка или из push: шапка видна, пока грузится карточка.
  final Ticket ticket;

  /// Пояснение над перепиской сразу после отправки: что будет дальше (заявка на запись — глава 9).
  final String? notice;

  @override
  State<TicketChatScreen> createState() => _TicketChatScreenState();
}

/// Один владелец всего чата: тикет (шапка и поле ввода следуют за его статусом), обращение, переписка, сокет,
/// вложения.
class _TicketChatScreenState extends State<TicketChatScreen> {
  late final AppState _app = AppScope.read(context);
  late Ticket _ticket = widget.ticket;

  /// Обращение — первым сообщением клиента (в прототипе у старых обращений описания нет).
  TicketMessage? _opening;

  /// Сообщения по id: кадр сокета и догрузка могут прийти дважды.
  final Map<int, TicketMessage> _messages = {};
  bool _loaded = false;
  Object? _loadError;

  TicketLive? _live;
  StreamSubscription<TicketLiveEvent>? _events;
  late final AppLifecycleListener _lifecycle;

  final _controller = TextEditingController();
  // Повтор неудачной отправки того же черновика — с тем же ключом: сервер не создаст дубль (#111).
  final _retryKey = RetryKey();
  final _scroll = ScrollController();
  late final AttachmentUploads _uploads = AttachmentUploads(_app.repository)..addListener(_changed);
  bool _sending = false;
  // Ошибка отправки — над полем ввода, а не всплывающим сообщением: оно на 4 с закрывало поле и кнопку
  // «Отправить», повторить отправку было нельзя (#105).
  String? _sendError;

  /// «Переподключаемся…» — только если связи нет дольше мгновения: короткое подключение при открытии не мигает.
  bool _showReconnecting = false;
  Timer? _reconnectingTimer;

  @override
  void initState() {
    super.initState();
    _app.chatOpened(widget.ticket.id);
    _lifecycle = AppLifecycleListener(onPause: () => _live?.pause(), onResume: () => _live?.resume());
    _load();
  }

  @override
  void dispose() {
    _app.chatClosed(widget.ticket.id);
    _lifecycle.dispose();
    _reconnectingTimer?.cancel();
    _live?.state.removeListener(_onLiveState);
    unawaited(_events?.cancel());
    unawaited(_live?.close());
    _uploads.dispose();
    _controller.dispose();
    _scroll.dispose();
    super.dispose();
  }

  /// Карточка тикета (описание, вложения, свежий статус) и переписка; затем — сокет с догрузкой после них.
  Future<void> _load() async {
    final repository = _app.repository;
    try {
      final detail = await repository.ticket(widget.ticket.id);
      final messages = await repository.messages(widget.ticket.id);
      if (!mounted) return;
      setState(() {
        _ticket = detail;
        _opening = _openingOf(detail);
        _messages.addEntries(messages.map((m) => MapEntry(m.id, m)));
        _loaded = true;
      });
      _watch(afterId: messages.fold(0, (id, m) => m.id > id ? m.id : id));
    } on Exception catch (e) {
      if (mounted) setState(() => _loadError = e);
    }
  }

  void _retry() {
    setState(() => _loadError = null);
    _load();
  }

  static TicketMessage? _openingOf(Ticket detail) {
    final description = detail.description;
    if (description == null) return null;
    return TicketMessage(
      id: 0,
      fromClient: true,
      authorName: 'Вы',
      body: description,
      createdAt: detail.createdAt,
      attachments: detail.attachments,
    );
  }

  void _watch({required int afterId}) {
    final live = _live = _app.repository.watchTicket(widget.ticket.id, afterId: afterId);
    _events = live.events.listen(_onEvent);
    live.state.addListener(_onLiveState);
    _onLiveState();
  }

  void _changed() => setState(() {});

  void _onEvent(TicketLiveEvent e) {
    if (!mounted) return;
    switch (e) {
      case LiveMessage(:final message):
        final isNew = !_messages.containsKey(message.id);
        setState(() => _messages[message.id] = message);
        if (isNew) _scrollToEnd();
      case LiveTicket(:final ticket):
        setState(() => _ticket = ticket);
    }
  }

  void _onLiveState() {
    final live = _live?.state.value == LiveState.live;
    _reconnectingTimer?.cancel();
    if (live) {
      if (_showReconnecting) setState(() => _showReconnecting = false);
    } else {
      _reconnectingTimer = Timer(const Duration(milliseconds: 1500), () {
        if (mounted) setState(() => _showReconnecting = true);
      });
    }
  }

  void _scrollToEnd() => WidgetsBinding.instance.addPostFrameCallback((_) {
        if (_scroll.hasClients) {
          _scroll.animateTo(_scroll.position.maxScrollExtent, duration: EvDuration.normal, curve: Curves.easeOut);
        }
      });

  Future<void> _send() async {
    final body = _controller.text.trim();
    if (body.isEmpty && _uploads.isEmpty) return;
    final blocker = _uploads.blocker;
    if (blocker != null) {
      showErrorSnack(context, blocker);
      return;
    }
    setState(() {
      _sending = true;
      _sendError = null;
    });
    final text = body.isEmpty ? 'Вложение' : body;
    final attachments = _uploads.uploaded;
    final key = _retryKey.forDraft([text, for (final a in attachments) a.key].join('\n'));
    try {
      final m = await _app.repository.sendMessage(
        widget.ticket.id,
        text,
        attachments: attachments,
        clientRequestId: key,
      );
      _retryKey.reset();
      setState(() {
        _messages[m.id] = m;
        _controller.clear();
        _uploads.clear();
      });
      _scrollToEnd();
    } on Exception catch (e) {
      if (mounted) setState(() => _sendError = 'Не отправлено. ${actionErrorText(e)}');
    } finally {
      if (mounted) setState(() => _sending = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        // Статус — под номером, а не в действиях справа: номер обращения виден целиком на узком экране;
        // если не помещается и так — ужимается, а не обрезается многоточием (глава 9).
        title: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          mainAxisSize: MainAxisSize.min,
          children: [
            FittedBox(
              fit: BoxFit.scaleDown,
              alignment: Alignment.centerLeft,
              child: Text('Обращение №${_ticket.id}'),
            ),
            Row(
              children: [
                Flexible(child: Text(_ticket.category.label, style: Theme.of(context).textTheme.bodySmall)),
                const SizedBox(width: EvSpace.s2),
                TicketStatusChip(key: const Key('chat-status'), status: _ticket.status),
              ],
            ),
          ],
        ),
      ),
      body: switch ((_loadError, _loaded)) {
        (final Object error, _) => ErrorState(error: error, onRetry: _retry),
        (_, false) => const Center(child: CircularProgressIndicator()),
        _ => _chat(context),
      },
    );
  }

  Widget _chat(BuildContext context) {
    final c = context.evColors;
    final resolved = _ticket.status == TicketStatus.resolved;
    final messages = [
      if (_opening case final opening?) opening,
      ...(_messages.values.toList()..sort((a, b) => a.id.compareTo(b.id))),
    ];
    return Column(
      children: [
        if (_showReconnecting && _live?.state.value != LiveState.live)
          Container(
            key: const Key('chat-reconnecting'),
            width: double.infinity,
            color: c.surfaceSubtle,
            padding: const EdgeInsets.symmetric(horizontal: EvSpace.s4, vertical: EvSpace.s2),
            child: Semantics(
              liveRegion: true,
              child: Text(
                _live?.state.value == LiveState.stopped
                    ? 'Новые сообщения не обновляются — откройте чат заново'
                    : 'Нет связи с сервером — переподключаемся…',
                style: Theme.of(context).textTheme.bodySmall?.copyWith(color: c.fgMuted),
              ),
            ),
          ),
        if (widget.notice != null)
          Padding(
            padding: const EdgeInsets.fromLTRB(EvSpace.s4, EvSpace.s4, EvSpace.s4, 0),
            child: InfoNote(key: const Key('chat-notice'), text: widget.notice!),
          ),
        Expanded(
          child: ListView.builder(
            key: const Key('chat-messages'),
            controller: _scroll,
            padding: const EdgeInsets.all(EvSpace.s4),
            itemCount: messages.length,
            itemBuilder: (context, i) => _Bubble(key: Key('message-${messages[i].id}'), message: messages[i]),
          ),
        ),
        if (resolved)
          Container(
            width: double.infinity,
            color: c.surfaceSubtle,
            padding: const EdgeInsets.all(EvSpace.s4),
            child: SafeArea(
              top: false,
              child: Text(
                'Обращение решено. Если проблема вернулась — создайте новое.',
                style: TextStyle(color: c.fgMuted),
              ),
            ),
          )
        else
          Material(
            color: c.surface,
            child: SafeArea(
              top: false,
              child: Padding(
                padding: const EdgeInsets.all(EvSpace.s2),
                child: Column(
                  mainAxisSize: MainAxisSize.min,
                  children: [
                    if (_sendError != null)
                      Padding(
                        padding: const EdgeInsets.fromLTRB(EvSpace.s2, 0, EvSpace.s2, EvSpace.s2),
                        child: Align(
                          alignment: Alignment.centerLeft,
                          child: Text(
                            _sendError!,
                            key: const Key('send-error'),
                            style: TextStyle(color: c.dangerText),
                          ),
                        ),
                      ),
                    if (!_uploads.isEmpty)
                      Padding(
                        padding: const EdgeInsets.only(bottom: EvSpace.s2),
                        child: Align(alignment: Alignment.centerLeft, child: AttachmentTray(uploads: _uploads)),
                      ),
                    Row(
                      children: [
                        AttachButton(uploads: _uploads, compact: true),
                        Expanded(
                          child: TextField(
                            key: const Key('message'),
                            controller: _controller,
                            minLines: 1,
                            maxLines: 4,
                            textCapitalization: TextCapitalization.sentences,
                            decoration: const InputDecoration(hintText: 'Сообщение'),
                          ),
                        ),
                        IconButton(
                          key: const Key('send'),
                          tooltip: 'Отправить',
                          icon: _sending ? const ButtonProgress() : const Icon(Icons.send),
                          onPressed: _sending ? null : _send,
                        ),
                      ],
                    ),
                  ],
                ),
              ),
            ),
          ),
      ],
    );
  }
}

class _Bubble extends StatelessWidget {
  const _Bubble({super.key, required this.message});

  final TicketMessage message;

  @override
  Widget build(BuildContext context) {
    final c = context.evColors;
    final text = Theme.of(context).textTheme;
    final mine = message.fromClient;
    final muted = mine ? c.onPrimary : c.fgMuted;
    return Align(
      alignment: mine ? Alignment.centerRight : Alignment.centerLeft,
      child: ConstrainedBox(
        constraints: BoxConstraints(maxWidth: MediaQuery.sizeOf(context).width * 0.8),
        child: Container(
          margin: const EdgeInsets.only(bottom: EvSpace.s3),
          padding: const EdgeInsets.all(EvSpace.s3),
          decoration: BoxDecoration(
            color: mine ? c.primary : c.surface,
            border: mine ? null : Border.all(color: c.border),
            borderRadius: const BorderRadius.all(Radius.circular(EvRadius.lg)),
          ),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              if (!mine) Text(message.authorName, style: text.labelSmall?.copyWith(color: c.primaryText)),
              Text(message.body, style: text.bodyLarge?.copyWith(color: mine ? c.onPrimary : c.fg)),
              for (final a in message.attachments)
                Padding(
                  padding: const EdgeInsets.only(top: EvSpace.s2),
                  child: _AttachmentView(attachment: a, color: muted),
                ),
              const SizedBox(height: EvSpace.s1),
              Text(formatDateTime(message.createdAt), style: text.bodySmall?.copyWith(color: muted)),
            ],
          ),
        ),
      ),
    );
  }
}

/// Фото — миниатюра (нажатие — на весь экран), видео — открывается в системном плеере. Ссылка действует
/// 15 минут: устаревшая обновится, когда переписка перечитается (возврат в приложение, повторное открытие).
class _AttachmentView extends StatelessWidget {
  const _AttachmentView({required this.attachment, required this.color});

  final TicketAttachment attachment;
  final Color color;

  @override
  Widget build(BuildContext context) {
    final url = attachment.url;
    final photo = attachment.fileType == AttachmentType.photo;
    final label = Row(
      mainAxisSize: MainAxisSize.min,
      children: [
        Icon(photo ? Icons.image_outlined : Icons.play_circle_outline, size: EvSize.iconMd, color: color),
        const SizedBox(width: EvSpace.s1),
        Flexible(
          child: Text(photo ? 'Фото' : 'Видео', style: Theme.of(context).textTheme.bodySmall?.copyWith(color: color)),
        ),
      ],
    );
    if (url == null) return label; // прототип: файла нет
    if (!photo) {
      return InkWell(
        onTap: () => launchUrl(Uri.parse(url), mode: LaunchMode.externalApplication),
        child: Semantics(button: true, label: 'Открыть видео', child: label),
      );
    }
    return Semantics(
      button: true,
      label: 'Открыть фото',
      child: GestureDetector(
        onTap: () => Navigator.of(context).push(MaterialPageRoute<void>(builder: (_) => _PhotoScreen(url: url))),
        child: ClipRRect(
          borderRadius: const BorderRadius.all(Radius.circular(EvRadius.md)),
          child: Image.network(
            url,
            height: 160,
            fit: BoxFit.cover,
            errorBuilder: (_, __, ___) => label,
            loadingBuilder: (_, child, progress) => progress == null
                ? child
                : const SizedBox(height: 160, width: 120, child: Center(child: CircularProgressIndicator())),
          ),
        ),
      ),
    );
  }
}

class _PhotoScreen extends StatelessWidget {
  const _PhotoScreen({required this.url});

  final String url;

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: Colors.black,
      appBar: AppBar(backgroundColor: Colors.black, foregroundColor: Colors.white),
      body: InteractiveViewer(child: Center(child: Image.network(url))),
    );
  }
}
