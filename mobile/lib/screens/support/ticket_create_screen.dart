// Новое обращение (POST /tickets). Минимизация ввода (ТЗ раздел 6): авто и категория — выбором,
// описание подставляется из дерева решений / карточки агрегата; модель и прошивка прикрепляются сами.
// Запись на замену/ТО из карточки агрегата — та же форма (глава 9): пожелание по времени уходит в description,
// дату и время предлагает инженер в чате (полей визита в контракте API v1 нет).
// Фото/видео — POST /uploads/presign (глава 15); в прототипе вложение имитируется.
import 'package:flutter/material.dart';

import '../../app/app_state.dart';
import '../../data/models.dart';
import '../../theme/app_theme.dart';
import '../../ui/info_note.dart';
import '../../ui/states.dart';
import 'ticket_chat_screen.dart';

/// Запись в сервис из карточки агрегата: заголовок формы и начало описания.
enum ServiceBooking {
  replacement('Запись на замену'),
  maintenance('Запись на ТО');

  const ServiceBooking(this.title);

  final String title;
}

/// «Когда удобно приехать» — пожелание клиента, необязательное (эталон C3 — 3 тапа).
const visitTimeOptions = ['Будни, утро', 'Будни, вечер', 'Выходные', 'Любое время'];

/// Запись не подтверждена, пока инженер не предложит время, — говорим об этом прямо (глава 9, C3).
const bookingSentNotice = 'Заявка на запись отправлена. Инженер предложит дату и время в этом чате';

class TicketCreateScreen extends StatefulWidget {
  const TicketCreateScreen({
    super.key,
    this.vehicleId,
    this.category,
    this.description,
    this.sourceArticleId,
    this.sourceNodeId,
    this.booking,
  });

  /// Авто известно (карточка агрегата). Без него при нескольких авто на аккаунте выбор обязателен:
  /// дерево неполадок и «Новое обращение» к машине не привязаны (глава 9); единственное авто выбрано сразу.
  final int? vehicleId;
  final TicketCategory? category;
  final String? description;
  final int? sourceArticleId;
  final int? sourceNodeId;

  /// Запись на замену/ТО: вместо «Что случилось?» — «Когда удобно приехать», категория — «Агрегаты / ТО».
  final ServiceBooking? booking;

  @override
  State<TicketCreateScreen> createState() => _TicketCreateScreenState();
}

class _TicketCreateScreenState extends State<TicketCreateScreen> {
  late int? _vehicleId = widget.vehicleId;
  late TicketCategory? _category = widget.booking != null ? TicketCategory.maintenance : widget.category;
  late final _description = TextEditingController(text: widget.description);
  final List<TicketAttachment> _attachments = [];
  String? _visitTime;
  final _scroll = ScrollController();
  final _vehicleQuestion = GlobalKey();
  final _categoryQuestion = GlobalKey();
  String? _vehicleError;
  String? _categoryError;
  String? _descriptionError;
  bool _busy = false;

  bool get _booking => widget.booking != null;

  @override
  void dispose() {
    _description.dispose();
    _scroll.dispose();
    super.dispose();
  }

  int? _selectedVehicleId(List<Vehicle> vehicles) => _vehicleId ?? (vehicles.length == 1 ? vehicles.single.id : null);

  /// Пожелание по времени — последней строкой описания: инженер видит его в карточке тикета и в чате.
  String get _ticketDescription => [
        _description.text.trim(),
        if (_visitTime != null) 'Когда удобно приехать: $_visitTime',
      ].join('\n');

  void _attach(AttachmentType type) {
    final n = _attachments.where((a) => a.fileType == type).length + 1;
    setState(() => _attachments.add(TicketAttachment(
          fileName: type == AttachmentType.photo ? 'Фото $n.jpg' : 'Видео $n.mp4',
          fileType: type,
        )));
  }

  Future<void> _submit() async {
    final app = AppScope.read(context);
    final vehicleId = _selectedVehicleId(app.vehicles);
    setState(() {
      _vehicleError = vehicleId == null ? 'Выберите автомобиль' : null;
      _categoryError = _category == null ? 'Выберите, что случилось' : null;
      _descriptionError = _description.text.trim().isNotEmpty
          ? null
          : _booking
              ? 'Опишите, что нужно сделать'
              : 'Опишите проблему в паре слов';
    });
    if (_vehicleError != null || _categoryError != null) {
      await _revealQuestion(_vehicleError != null ? _vehicleQuestion : _categoryQuestion);
      return;
    }
    if (_descriptionError != null) return;
    setState(() => _busy = true);
    try {
      final ticket = await app.repository.createTicket(TicketDraft(
        vehicleId: vehicleId!,
        category: _category!,
        description: _ticketDescription,
        sourceArticleId: widget.sourceArticleId,
        sourceNodeId: widget.sourceNodeId,
        attachments: List.of(_attachments),
      ));
      if (!mounted) return;
      // Заявка на запись — пояснение остаётся над перепиской; обычное обращение — короткое уведомление.
      if (!_booking) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text('Обращение №${ticket.id} создано. Инженер ответит в чате')),
        );
      }
      app.refreshUnread();
      Navigator.of(context).pushReplacement(MaterialPageRoute<void>(
        builder: (_) => TicketChatScreen(ticket: ticket, notice: _booking ? bookingSentNotice : null),
      ));
    } on Exception catch (e) {
      if (mounted) showErrorSnack(context, e);
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  /// «Отправить» — внизу формы, а выбор авто и категории — вверху: после длинного описания из дерева, на маленьком
  /// экране или с клавиатурой их ошибка оказывается над видимой областью, и нажатие внешне ничего не делает
  /// (глава 9, ревью M5). Прокручиваем к вопросу, чтобы были видны он сам, варианты и ошибка под ними.
  Future<void> _revealQuestion(GlobalKey question) async {
    await WidgetsBinding.instance.endOfFrame; // ошибка уже в разметке
    if (!mounted) return;
    // Вопрос далеко за кэшем ListView (элемент не построен) — сначала к началу формы: оба вопроса — в её начале.
    if (question.currentContext == null && _scroll.hasClients) {
      _scroll.jumpTo(0);
      await WidgetsBinding.instance.endOfFrame;
    }
    final target = question.currentContext;
    if (target == null || !target.mounted) return;
    await Scrollable.ensureVisible(
      target,
      duration: EvDuration.normal,
      alignmentPolicy: ScrollPositionAlignmentPolicy.keepVisibleAtStart,
    );
  }

  @override
  Widget build(BuildContext context) {
    final c = context.evColors;
    final text = Theme.of(context).textTheme;
    final app = AppScope.of(context);
    final vehicleId = _selectedVehicleId(app.vehicles);
    final vehicle = app.vehicles.where((v) => v.id == vehicleId).firstOrNull;
    return Scaffold(
      appBar: AppBar(title: Text(widget.booking?.title ?? 'Новое обращение')),
      body: SafeArea(
        child: ListView(
          controller: _scroll,
          padding: const EdgeInsets.all(EvSpace.s4),
          children: [
            if (app.vehicles.length > 1) ...[
              Text('По какому автомобилю?', key: _vehicleQuestion, style: text.titleMedium),
              const SizedBox(height: EvSpace.s2),
              Wrap(
                spacing: EvSpace.s2,
                runSpacing: EvSpace.s2,
                children: [
                  for (final v in app.vehicles)
                    ChoiceChip(
                      key: Key('vehicle-${v.id}'),
                      label: Text('${v.vehicleModel.title} · ${v.vinMasked}'),
                      selected: v.id == vehicleId,
                      onSelected: (_) => setState(() {
                        _vehicleId = v.id;
                        _vehicleError = null;
                      }),
                    ),
                ],
              ),
              if (_vehicleError != null) FieldError(_vehicleError!),
              const SizedBox(height: EvSpace.s6),
            ],
            if (_booking) ...[
              Text('Когда удобно приехать', style: text.titleMedium),
              const SizedBox(height: EvSpace.s1),
              Text(
                'Необязательно. Точные дату и время предложит инженер',
                style: text.bodyMedium?.copyWith(color: c.fgMuted),
              ),
              const SizedBox(height: EvSpace.s2),
              Wrap(
                spacing: EvSpace.s2,
                runSpacing: EvSpace.s2,
                children: [
                  for (final (i, option) in visitTimeOptions.indexed)
                    ChoiceChip(
                      key: Key('visit-time-$i'),
                      label: Text(option),
                      selected: _visitTime == option,
                      onSelected: (selected) => setState(() => _visitTime = selected ? option : null),
                    ),
                ],
              ),
            ] else ...[
              Text('Что случилось?', key: _categoryQuestion, style: text.titleMedium),
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
              if (_categoryError != null) FieldError(_categoryError!),
            ],
            const SizedBox(height: EvSpace.s6),
            TextField(
              key: const Key('description'),
              controller: _description,
              minLines: 3,
              maxLines: 8,
              textCapitalization: TextCapitalization.sentences,
              decoration: InputDecoration(
                labelText: _booking ? 'Что нужно сделать' : 'Описание',
                errorText: _descriptionError,
              ),
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
            InfoNote(
              text: vehicle == null
                  ? 'Прикрепим автоматически модель и версию прошивки выбранного автомобиля'
                  : 'Прикрепим автоматически: ${vehicle.vehicleModel.title}'
                      '${vehicle.currentFirmwareVersion != null ? ', прошивка ${vehicle.currentFirmwareVersion}' : ''}',
            ),
            const SizedBox(height: EvSpace.s6),
            FilledButton(
              key: const Key('submit-ticket'),
              onPressed: _busy ? null : _submit,
              child: _busy ? const ButtonProgress() : Text(_booking ? 'Отправить заявку' : 'Отправить'),
            ),
          ],
        ),
      ),
    );
  }
}
