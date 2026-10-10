// Чат по обращению (GET/POST /tickets/{id}/messages). Real-time (WebSocket) — глава 17.
import 'package:flutter/material.dart';

import '../../app/app_state.dart';
import '../../data/models.dart';
import '../../theme/app_theme.dart';
import '../../ui/format.dart';
import '../../ui/states.dart';
import 'support_screen.dart';

class TicketChatScreen extends StatelessWidget {
  const TicketChatScreen({super.key, required this.ticket});

  final Ticket ticket;

  @override
  Widget build(BuildContext context) {
    final app = AppScope.of(context);
    return Scaffold(
      appBar: AppBar(
        title: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text('Обращение №${ticket.id}'),
            Text(ticket.category.label, style: Theme.of(context).textTheme.bodySmall),
          ],
        ),
        actions: [
          Padding(
            padding: const EdgeInsets.only(right: EvSpace.s4),
            child: Center(child: TicketStatusChip(status: ticket.status)),
          ),
        ],
      ),
      body: AsyncView<List<TicketMessage>>(
        reloadKey: app.revision,
        load: () => app.repository.messages(ticket.id),
        builder: (context, messages, _) => _Chat(ticket: ticket, initial: messages),
      ),
    );
  }
}

class _Chat extends StatefulWidget {
  const _Chat({required this.ticket, required this.initial});

  final Ticket ticket;
  final List<TicketMessage> initial;

  @override
  State<_Chat> createState() => _ChatState();
}

class _ChatState extends State<_Chat> {
  late List<TicketMessage> _messages = widget.initial;
  final _controller = TextEditingController();
  final List<TicketAttachment> _attachments = [];
  bool _sending = false;

  @override
  void didUpdateWidget(covariant _Chat old) {
    super.didUpdateWidget(old);
    if (old.initial != widget.initial) _messages = widget.initial;
  }

  @override
  void dispose() {
    _controller.dispose();
    super.dispose();
  }

  Future<void> _send() async {
    final body = _controller.text.trim();
    if (body.isEmpty && _attachments.isEmpty) return;
    setState(() => _sending = true);
    try {
      final m = await AppScope.read(context).repository.sendMessage(
            widget.ticket.id,
            body.isEmpty ? 'Вложение' : body,
            attachments: List.of(_attachments),
          );
      setState(() {
        _messages = [..._messages, m];
        _controller.clear();
        _attachments.clear();
      });
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
    return Column(
      children: [
        Expanded(
          child: ListView.builder(
            padding: const EdgeInsets.all(EvSpace.s4),
            itemCount: _messages.length,
            itemBuilder: (context, i) => _Bubble(message: _messages[i]),
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
                padding: const EdgeInsets.fromLTRB(EvSpace.s2, EvSpace.s2, EvSpace.s2, EvSpace.s2),
                child: Column(
                  mainAxisSize: MainAxisSize.min,
                  children: [
                    if (_attachments.isNotEmpty)
                      Wrap(
                        spacing: EvSpace.s2,
                        children: [
                          for (final a in _attachments)
                            InputChip(
                              label: Text(a.fileName),
                              onDeleted: () => setState(() => _attachments.remove(a)),
                            ),
                        ],
                      ),
                    Row(
                      children: [
                        IconButton(
                          tooltip: 'Прикрепить фото',
                          icon: const Icon(Icons.attach_file),
                          onPressed: () => setState(() => _attachments.add(TicketAttachment(
                                fileName: 'Фото ${_attachments.length + 1}.jpg',
                                fileType: AttachmentType.photo,
                              ))),
                        ),
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
  const _Bubble({required this.message});

  final TicketMessage message;

  @override
  Widget build(BuildContext context) {
    final c = context.evColors;
    final text = Theme.of(context).textTheme;
    final mine = message.fromClient;
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
                  padding: const EdgeInsets.only(top: EvSpace.s1),
                  child: Row(
                    mainAxisSize: MainAxisSize.min,
                    children: [
                      Icon(Icons.image_outlined, size: EvSize.iconSm, color: mine ? c.onPrimary : c.fgMuted),
                      const SizedBox(width: EvSpace.s1),
                      Text(a.fileName, style: text.bodySmall?.copyWith(color: mine ? c.onPrimary : c.fgMuted)),
                    ],
                  ),
                ),
              const SizedBox(height: EvSpace.s1),
              Text(
                formatDateTime(message.createdAt),
                style: text.bodySmall?.copyWith(color: mine ? c.onPrimary : c.fgMuted),
              ),
            ],
          ),
        ),
      ),
    );
  }
}
