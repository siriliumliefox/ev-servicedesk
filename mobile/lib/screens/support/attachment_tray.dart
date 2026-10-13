// Вложения в форме обращения и в чате (ADR 0024 п. 9): выбор (камера/галерея), проверка до загрузки, загрузка
// сразу после выбора — по одному, с прогрессом и повтором; «Отправить» — когда загружены все.
import 'dart:async';

import 'package:flutter/material.dart';

import '../../app/app_state.dart';
import '../../data/attachments.dart';
import '../../data/models.dart';
import '../../data/repository.dart';
import '../../theme/app_theme.dart';
import '../../ui/states.dart';

enum UploadStatus { uploading, done, failed }

class PendingAttachment {
  PendingAttachment(this.file);

  final LocalAttachment file;
  UploadStatus status = UploadStatus.uploading;
  double progress = 0;
  TicketAttachment? uploaded;
  Object? error;
}

/// Очередь загрузок одной формы: файлы загружаются по одному, в порядке выбора.
class AttachmentUploads extends ChangeNotifier {
  AttachmentUploads(this.repository);

  final ClientRepository repository;
  final List<PendingAttachment> _items = [];
  Future<void> _queue = Future.value();
  bool _disposed = false;

  List<PendingAttachment> get items => List.unmodifiable(_items);
  bool get isEmpty => _items.isEmpty;
  bool get busy => _items.any((a) => a.status == UploadStatus.uploading);
  bool get hasFailed => _items.any((a) => a.status == UploadStatus.failed);

  /// Загруженные — для запроса; пока что-то грузится или не загрузилось, отправлять нельзя.
  List<TicketAttachment> get uploaded => [for (final a in _items) a.uploaded!];

  /// Причина отказа (формат, размер, больше 10) — до загрузки; null — файл принят в очередь.
  String? add(LocalAttachment file) {
    final problem = attachmentProblem(file, alreadyAttached: _items.length);
    if (problem != null) return problem;
    final item = PendingAttachment(file);
    _items.add(item);
    _enqueue(item);
    notifyListeners();
    return null;
  }

  void retry(PendingAttachment item) {
    item
      ..status = UploadStatus.uploading
      ..progress = 0
      ..error = null;
    _enqueue(item);
    notifyListeners();
  }

  void remove(PendingAttachment item) {
    _items.remove(item);
    notifyListeners();
  }

  void clear() {
    _items.clear();
    notifyListeners();
  }

  void _enqueue(PendingAttachment item) {
    _queue = _queue.then((_) => _upload(item));
  }

  Future<void> _upload(PendingAttachment item) async {
    if (!_items.contains(item)) return; // удалён, пока ждал очереди
    try {
      item.uploaded = await repository.uploadAttachment(item.file, onProgress: (p) {
        item.progress = p;
        _notify();
      });
      item.status = UploadStatus.done;
    } on Exception catch (e) {
      item
        ..status = UploadStatus.failed
        ..error = e;
    }
    _notify();
  }

  void _notify() {
    if (!_disposed) notifyListeners();
  }

  @override
  void dispose() {
    _disposed = true;
    super.dispose();
  }
}

/// Кнопка «Прикрепить»: меню камера/галерея × фото/видео.
class AttachButton extends StatelessWidget {
  const AttachButton({super.key, required this.uploads, this.compact = false});

  final AttachmentUploads uploads;

  /// В строке чата — иконка; в форме — кнопка с подписью.
  final bool compact;

  Future<void> _choose(BuildContext context) async {
    final choice = await showModalBottomSheet<(AttachmentType, bool)>(
      context: context,
      builder: (context) => SafeArea(
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            for (final (type, camera, icon, label) in const [
              (AttachmentType.photo, true, Icons.photo_camera_outlined, 'Сфотографировать'),
              (AttachmentType.video, true, Icons.videocam_outlined, 'Снять видео'),
              (AttachmentType.photo, false, Icons.photo_library_outlined, 'Фото из галереи'),
              (AttachmentType.video, false, Icons.video_library_outlined, 'Видео из галереи'),
            ])
              ListTile(
                key: Key('attach-${type.name}-${camera ? 'camera' : 'gallery'}'),
                leading: Icon(icon),
                title: Text(label),
                onTap: () => Navigator.of(context).pop((type, camera)),
              ),
          ],
        ),
      ),
    );
    if (choice == null || !context.mounted) return;
    final LocalAttachment? file;
    try {
      file = await AppScope.read(context).attachmentSource.pick(choice.$1, camera: choice.$2);
    } on Exception {
      // Нет доступа к камере/галерее (запрещён в настройках) — системный диалог уже показан.
      if (context.mounted) showErrorSnack(context, 'Нет доступа к камере или фото — разрешите в настройках');
      return;
    }
    if (file == null || !context.mounted) return;
    final problem = uploads.add(file);
    if (problem != null) showErrorSnack(context, problem);
  }

  @override
  Widget build(BuildContext context) {
    final full = uploads.items.length >= maxAttachments;
    if (compact) {
      return IconButton(
        key: const Key('attach'),
        tooltip: 'Прикрепить фото или видео',
        icon: const Icon(Icons.attach_file),
        onPressed: full ? null : () => _choose(context),
      );
    }
    return OutlinedButton.icon(
      key: const Key('attach'),
      onPressed: full ? null : () => _choose(context),
      icon: const Icon(Icons.add_a_photo_outlined),
      label: const Text('Фото или видео'),
    );
  }
}

/// Выбранные файлы: прогресс загрузки, ошибка с «Повторить», удаление.
class AttachmentTray extends StatelessWidget {
  const AttachmentTray({super.key, required this.uploads});

  final AttachmentUploads uploads;

  @override
  Widget build(BuildContext context) {
    final c = context.evColors;
    return Wrap(
      spacing: EvSpace.s2,
      runSpacing: EvSpace.s2,
      children: [
        for (final (i, a) in uploads.items.indexed)
          InputChip(
            key: Key('attachment-$i'),
            avatar: switch (a.status) {
              UploadStatus.uploading => SizedBox.square(
                  dimension: EvSize.iconMd,
                  child: CircularProgressIndicator(strokeWidth: 2, value: a.progress > 0 ? a.progress : null),
                ),
              UploadStatus.done =>
                Icon(a.file.fileType == AttachmentType.photo ? Icons.image_outlined : Icons.movie_outlined),
              UploadStatus.failed => Icon(Icons.error_outline, color: c.dangerText),
            },
            label: Text(
              a.status == UploadStatus.failed ? 'Не загрузилось — повторить' : _label(a, i),
              semanticsLabel: switch (a.status) {
                UploadStatus.uploading => '${_label(a, i)}: загружается',
                UploadStatus.done => '${_label(a, i)}: загружено',
                UploadStatus.failed => '${_label(a, i)}: не загрузилось, нажмите, чтобы повторить',
              },
            ),
            onPressed: a.status == UploadStatus.failed ? () => uploads.retry(a) : null,
            onDeleted: () => uploads.remove(a),
            deleteButtonTooltipMessage: 'Убрать',
          ),
      ],
    );
  }

  static String _label(PendingAttachment a, int i) {
    final kind = a.file.fileType == AttachmentType.photo ? 'Фото' : 'Видео';
    final mb = a.file.sizeBytes / (1024 * 1024);
    return '$kind ${i + 1} · ${mb < 0.1 ? '<0,1' : mb.toStringAsFixed(1).replaceAll('.', ',')} МБ';
  }
}

/// Текст на кнопке/ошибка, пока вложения не готовы к отправке; null — готовы.
String? uploadsBlocker(AttachmentUploads uploads) {
  if (uploads.busy) return 'Дождитесь загрузки файлов';
  if (uploads.hasFailed) return 'Повторите загрузку или уберите файл';
  return null;
}
