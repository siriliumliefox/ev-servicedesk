// Новое обращение (POST /tickets). Минимизация ввода (ТЗ раздел 6): авто и категория — выбором,
// описание подставляется из дерева решений / карточки агрегата; модель и прошивка прикрепляются сами.
// Фото/видео — POST /uploads/presign (глава 15); в прототипе вложение имитируется.
import 'package:flutter/material.dart';

import '../../app/app_state.dart';
import '../../data/models.dart';
import '../../theme/app_theme.dart';
import '../../ui/states.dart';
import 'ticket_chat_screen.dart';

class TicketCreateScreen extends StatefulWidget {
  const TicketCreateScreen({
    super.key,
    required this.vehicleId,
    this.category,
    this.description,
    this.sourceArticleId,
    this.sourceNodeId,
  });

  final int vehicleId;
  final TicketCategory? category;
  final String? description;
  final int? sourceArticleId;
  final int? sourceNodeId;

  @override
  State<TicketCreateScreen> createState() => _TicketCreateScreenState();
}

class _TicketCreateScreenState extends State<TicketCreateScreen> {
  late int _vehicleId = widget.vehicleId;
  late TicketCategory? _category = widget.category;
  late final _description = TextEditingController(text: widget.description);
  final List<TicketAttachment> _attachments = [];
  String? _categoryError;
  String? _descriptionError;
  bool _busy = false;

  @override
  void dispose() {
    _description.dispose();
    super.dispose();
  }

  void _attach(AttachmentType type) {
    final n = _attachments.where((a) => a.fileType == type).length + 1;
    setState(() => _attachments.add(TicketAttachment(
          fileName: type == AttachmentType.photo ? 'Фото $n.jpg' : 'Видео $n.mp4',
          fileType: type,
        )));
  }

  Future<void> _submit() async {
    setState(() {
      _categoryError = _category == null ? 'Выберите, что случилось' : null;
      _descriptionError = _description.text.trim().isEmpty ? 'Опишите проблему в паре слов' : null;
    });
    if (_categoryError != null || _descriptionError != null) return;
    setState(() => _busy = true);
    try {
      final ticket = await AppScope.read(context).repository.createTicket(TicketDraft(
            vehicleId: _vehicleId,
            category: _category!,
            description: _description.text.trim(),
            sourceArticleId: widget.sourceArticleId,
            sourceNodeId: widget.sourceNodeId,
            attachments: List.of(_attachments),
          ));
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text('Обращение №${ticket.id} создано. Инженер ответит в чате')),
      );
      AppScope.read(context).refreshUnread();
      Navigator.of(context).pushReplacement(MaterialPageRoute<void>(builder: (_) => TicketChatScreen(ticket: ticket)));
    } on Exception catch (e) {
      if (mounted) showErrorSnack(context, e);
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final c = context.evColors;
    final text = Theme.of(context).textTheme;
    final app = AppScope.of(context);
    final vehicle = app.vehicles.firstWhere((v) => v.id == _vehicleId);
    return Scaffold(
      appBar: AppBar(title: const Text('Новое обращение')),
      body: SafeArea(
        child: ListView(
          padding: const EdgeInsets.all(EvSpace.s4),
          children: [
            if (app.vehicles.length > 1) ...[
              DropdownButtonFormField<int>(
                isExpanded: true,
                initialValue: _vehicleId,
                decoration: const InputDecoration(labelText: 'Автомобиль'),
                items: [
                  for (final v in app.vehicles)
                    DropdownMenuItem(value: v.id, child: Text('${v.vehicleModel.title} · ${v.vinMasked}')),
                ],
                onChanged: (id) => setState(() => _vehicleId = id!),
              ),
              const SizedBox(height: EvSpace.s6),
            ],
            Text('Что случилось?', style: text.titleMedium),
            const SizedBox(height: EvSpace.s2),
            Wrap(
              spacing: EvSpace.s2,
              runSpacing: EvSpace.s2,
              children: [
                for (final cat in TicketCategory.values)
                  ChoiceChip(
                    key: Key('category-${cat.name}'),
                    label: Text(cat.label),
                    selected: _category == cat,
                    onSelected: (_) => setState(() {
                      _category = cat;
                      _categoryError = null;
                    }),
                  ),
              ],
            ),
            if (_categoryError != null) ...[
              const SizedBox(height: EvSpace.s1),
              Text(_categoryError!, style: EvTypeMobile.caption.copyWith(color: c.dangerText)),
            ],
            const SizedBox(height: EvSpace.s6),
            TextField(
              key: const Key('description'),
              controller: _description,
              minLines: 3,
              maxLines: 8,
              textCapitalization: TextCapitalization.sentences,
              decoration: InputDecoration(labelText: 'Описание', errorText: _descriptionError),
            ),
            const SizedBox(height: EvSpace.s4),
            Wrap(
              spacing: EvSpace.s2,
              runSpacing: EvSpace.s2,
              children: [
                OutlinedButton.icon(
                  onPressed: () => _attach(AttachmentType.photo),
                  icon: const Icon(Icons.photo_camera_outlined),
                  label: const Text('Фото'),
                ),
                OutlinedButton.icon(
                  onPressed: () => _attach(AttachmentType.video),
                  icon: const Icon(Icons.videocam_outlined),
                  label: const Text('Видео'),
                ),
              ],
            ),
            if (_attachments.isNotEmpty) ...[
              const SizedBox(height: EvSpace.s3),
              Wrap(
                spacing: EvSpace.s2,
                runSpacing: EvSpace.s2,
                children: [
                  for (final a in _attachments)
                    InputChip(
                      avatar: Icon(a.fileType == AttachmentType.photo ? Icons.image_outlined : Icons.movie_outlined),
                      label: Text(a.fileName),
                      onDeleted: () => setState(() => _attachments.remove(a)),
                    ),
                ],
              ),
            ],
            const SizedBox(height: EvSpace.s6),
            Container(
              padding: const EdgeInsets.all(EvSpace.s3),
              decoration: BoxDecoration(
                color: c.surfaceSubtle,
                borderRadius: const BorderRadius.all(Radius.circular(EvRadius.md)),
              ),
              child: Row(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Icon(Icons.info_outline, size: EvSize.iconMd, color: c.infoText),
                  const SizedBox(width: EvSpace.s2),
                  Expanded(
                    child: Text(
                      'Прикрепим автоматически: ${vehicle.vehicleModel.title}'
                      '${vehicle.currentFirmwareVersion != null ? ', прошивка ${vehicle.currentFirmwareVersion}' : ''}',
                      style: text.bodyMedium,
                    ),
                  ),
                ],
              ),
            ),
            const SizedBox(height: EvSpace.s6),
            FilledButton(
              key: const Key('submit-ticket'),
              onPressed: _busy ? null : _submit,
              child: _busy ? const ButtonProgress() : const Text('Отправить'),
            ),
          ],
        ),
      ),
    );
  }
}
