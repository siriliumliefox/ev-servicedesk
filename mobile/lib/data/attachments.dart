// Вложения тикета на устройстве (ADR 0024 п. 9; лимиты — ADR 0017, docs/openapi.yaml /uploads/presign):
// выбор фото/видео (камера, галерея), проверка до загрузки, MIME для S3.
import 'dart:io';

import 'package:image_picker/image_picker.dart';

import 'models.dart';

const maxAttachments = 10;
const maxPhotoBytes = 20 * 1024 * 1024;
const maxVideoBytes = 200 * 1024 * 1024;

/// Фото уменьшается до 2560 px по большей стороне, JPEG 85: всегда меньше 20 МБ и без HEIC.
const photoMaxSide = 2560.0;
const photoQuality = 85;

/// MIME по расширению: backend проверяет Content-Type загруженного объекта (HEAD) — PUT идёт с этим заголовком.
const _mimeTypes = {
  'jpg': 'image/jpeg',
  'jpeg': 'image/jpeg',
  'png': 'image/png',
  'heic': 'image/heic',
  'heif': 'image/heif',
  'webp': 'image/webp',
  'mp4': 'video/mp4',
  'mov': 'video/quicktime',
};

const _photoMimeTypes = {'image/jpeg', 'image/png', 'image/heic', 'image/heif', 'image/webp'};
const _videoMimeTypes = {'video/mp4', 'video/quicktime'};

String? mimeType(LocalAttachment file) => _mimeTypes[file.extension];

/// Причина, по которой файл нельзя прикрепить, — до загрузки, без запроса к серверу; null — можно.
String? attachmentProblem(LocalAttachment file, {required int alreadyAttached}) {
  if (alreadyAttached >= maxAttachments) return 'Можно прикрепить не больше $maxAttachments файлов';
  final mime = mimeType(file);
  final allowed = file.fileType == AttachmentType.photo ? _photoMimeTypes : _videoMimeTypes;
  if (mime == null || !allowed.contains(mime)) {
    return 'Этот формат файла не подходит. Прикрепите фото (JPEG, PNG, HEIC) или видео (MP4, MOV)';
  }
  if (file.fileType == AttachmentType.photo && file.sizeBytes > maxPhotoBytes) {
    return 'Фото больше 20 МБ — выберите другое';
  }
  if (file.fileType == AttachmentType.video && file.sizeBytes > maxVideoBytes) {
    return 'Видео больше 200 МБ — снимите покороче';
  }
  return null;
}

/// Откуда берётся файл: системный выбор фото автотест нажать не может — в тестах фейк (ADR 0024 п. 9).
abstract class AttachmentSource {
  /// null — пользователь передумал.
  Future<LocalAttachment?> pick(AttachmentType type, {required bool camera});
}

class ImagePickerSource implements AttachmentSource {
  ImagePickerSource([ImagePicker? picker]) : _picker = picker ?? ImagePicker();

  final ImagePicker _picker;

  @override
  Future<LocalAttachment?> pick(AttachmentType type, {required bool camera}) async {
    final source = camera ? ImageSource.camera : ImageSource.gallery;
    final file = type == AttachmentType.photo
        ? await _picker.pickImage(
            source: source,
            maxWidth: photoMaxSide,
            maxHeight: photoMaxSide,
            imageQuality: photoQuality,
          )
        : await _picker.pickVideo(source: source);
    if (file == null) return null;
    return LocalAttachment(path: file.path, fileType: type, sizeBytes: await File(file.path).length());
  }
}
