// Чат по обращению (ADR 0024 п. 8): переписка по REST, новые сообщения и смена статуса — по WebSocket (TicketLive);
// повторы отбрасываются по id. Свёрнутое приложение закрывает сокет, возврат — переподключение и догрузка.
// Вложения — фото и видео (ADR 0024 п. 9).
import 'dart:async';

import 'package:flutter/material.dart';
import 'package:url_launcher/url_launcher.dart';

import '../../app/app_state.dart';
import '../../data/models.dart';
import '../../data/ticket_live.dart';
import '../../theme/app_theme.dart';
import '../../ui/format.dart';
import '../../ui/info_note.dart';
import '../../ui/states.dart';
import 'attachment_tray.dart';
import 'support_screen.dart';

class TicketChatScreen extends StatefulWidget {
  const TicketChatScreen({super.key, required this.ticket, this.notice});

  final Ticket ticket;

  /// Пояснение над перепиской сразу после отправки: что будет дальше (заявка на запись — глава 9).
  final String? notice;

  @override
  State<TicketChatScreen> createState() => _TicketChatScreenState();
}

class _TicketChatScreenState extends State<TicketChatScreen> {
  /// Статус меняется по ticket.updated — шапка и поле ввода следуют за ним.
  late Ticket _ticket = widget.ticket;
  late final AppState _app = AppScope.read(context);

  @override
  void initState() {
    super.initState();
    _app.openChatTicketId = widget.ticket.id;
  }

  @override
  void dispose() {
    if (_app.openChatTicketId == widget.ticket.id) _app.openChatTicketId = null;
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final app = AppScope.of(context);
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
      body: AsyncView<List<TicketMessage>>(
        reloadKey: app.revision,
        load: () => app.repository.messages(_ticket.id),
        builder: (context, messages, _) => _Chat(
          ticket: _ticket,
          initial: messages,
          notice: widget.notice,
          onTicket: (t) => setState(() => _ticket = t),
        ),
      ),
    );
  }
}

class _Chat extends StatefulWidget {
  const _Chat({required this.ticket, required this.initial, required this.onTicket, this.notice});

  final Ticket ticket;
  final List<TicketMessage> initial;
  final ValueChanged<Ticket> onTicket;
  final String? notice;

  @override
  State<_Chat> createState() => _ChatState();
}

class _ChatState extends State<_Chat> {
  /// Сообщения по id: кадр сокета и догрузка могут прийти дважды.
  late final Map<int, TicketMessage> _messages = {for (final m in widget.initial) m.id: m};
  final _controller = TextEditingController();
  final _scroll = ScrollController();
  late final AttachmentUploads _uploads = AttachmentUploads(AppScope.read(context).repository)..addListener(_changed);
  late final TicketLive _live;
  late final StreamSubscription<TicketLiveEvent> _events;
  late final AppLifecycleListener _lifecycle;
  bool _sending = false;

  /// «Переподключаемся…» — только если связи нет дольше мгновения: короткое подключение при открытии не мигает.
  bool _showReconnecting = false;
  Timer? _reconnectingTimer;

  @override
  void initState() {
    super.initState();
    final lastId = widget.initial.fold(0, (id, m) => m.id > id ? m.id : id);
    _live = AppScope.read(context).repository.watchTicket(widget.ticket.id, afterId: lastId);
    _events = _live.events.listen(_onEvent);
    _live.state.addListener(_onLiveState);
    _onLiveState();
    _lifecycle = AppLifecycleListener(onPause: _live.pause, onResume: _live.resume);
  }

  @override
  void didUpdateWidget(covariant _Chat old) {
    super.didUpdateWidget(old);
    // Перечитанная переписка (возврат в приложение) дополняет то, что пришло по сокету.
    if (old.initial != widget.initial) {
      for (final m in widget.initial) {
        _messages[m.id] = m;
      }
    }
  }

  @override
  void dispose() {
    _lifecycle.dispose();
    _reconnectingTimer?.cancel();
    _live.state.removeListener(_onLiveState);
    unawaited(_events.cancel());
    unawaited(_live.close());
    _uploads.dispose();
    _controller.dispose();
    _scroll.dispose();
    super.dispose();
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
        widget.onTicket(ticket);
    }
  }

  void _onLiveState() {
    final live = _live.state.value == LiveState.live;
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
    final blocker = uploadsBlocker(_uploads);
    if (blocker != null) {
      showErrorSnack(context, blocker);
      return;
    }
    setState(() => _sending = true);
    try {
      final m = await AppScope.read(context).repository.sendMessage(
            widget.ticket.id,
            body.isEmpty ? 'Вложение' : body,
            attachments: _uploads.uploaded,
          );
      setState(() {
        _messages[m.id] = m;
        _controller.clear();
        _uploads.clear();
      });
      _scrollToEnd();
    } on Exception catch (e) {
      if (mounted) showErrorSnack(context, e);
    } finally {
      if (mounted) setState(() => _sending = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final c = context.evColors;
    final resolved = widget.ticket.status == TicketStatus.resolved;
    final messages = _messages.values.toList()..sort((a, b) => a.id.compareTo(b.id));
    return Column(
      children: [
        if (_showReconnecting && _live.state.value != LiveState.live)
          Container(
            key: const Key('chat-reconnecting'),
            width: double.infinity,
            color: c.surfaceSubtle,
            padding: const EdgeInsets.symmetric(horizontal: EvSpace.s4, vertical: EvSpace.s2),
            child: Semantics(
              liveRegion: true,
              child: Text(
                _live.state.value == LiveState.stopped
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
