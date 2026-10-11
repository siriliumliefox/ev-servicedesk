"""Вложения тикетов и сообщений через S3 (ADR 0004, ADR 0017 п. 10).

Загрузка: presigned PUT в `uploads/{user_id}/{uuid}{расширение}` — из имени файла берётся
только расширение (имя может содержать ПД и не хранится). Привязка к тикету или сообщению:
ключ — среди загрузок текущего пользователя, MIME и размер — из HEAD (со слов S3, а не
клиента), затем копия в `tickets/{ticket_id}/{uuid}{расширение}`. После commit исходный
объект удаляется; «сиротские» загрузки удаляет правило жизненного цикла бакета (24 ч).
Ключи объектов и имена файлов в логи не пишутся.
"""

import logging
import re
import uuid
from collections.abc import Callable, Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import PurePosixPath
from typing import Protocol

from redis import Redis
from sqlalchemy import exists, func, select
from sqlalchemy.orm import Session

from app.core import rate_limit
from app.core.config import Settings
from app.core.errors import ApiError
from app.core.storage import ObjectNotFound, ObjectStorage, StorageError
from app.models import AppUser, TicketAttachment
from app.models.enums import AttachmentType

logger = logging.getLogger(__name__)

# Расширение ключа — по типу вложения; прочие отбрасываются (MIME всё равно проверяет HEAD).
EXTENSIONS: dict[AttachmentType, frozenset[str]] = {
    AttachmentType.PHOTO: frozenset({".jpg", ".jpeg", ".png", ".heic", ".heif", ".webp"}),
    AttachmentType.VIDEO: frozenset({".mp4", ".mov"}),
}
_UUID = r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"
_UPLOAD_KEY = re.compile(
    rf"uploads/(?P<user_id>[1-9][0-9]{{0,18}})/(?P<name>{_UUID}(?:\.[a-z0-9]{{1,5}})?)"
)

Presign = Callable[[str], str]


class AttachmentInput(Protocol):
    """Элемент `attachments` запроса (TicketAttachmentInput)."""

    file_url: str
    file_type: AttachmentType


@dataclass(frozen=True)
class PresignedUpload:
    upload_url: str
    file_url: str
    expires_at: datetime


@dataclass(frozen=True)
class Upload:
    """Проверенная загрузка: ключ, имя объекта ({uuid}{расширение}) и метаданные из HEAD."""

    key: str
    name: str
    file_type: AttachmentType
    mime_type: str
    size_bytes: int


def presigner(storage: ObjectStorage, settings: Settings) -> Presign:
    """file_url вложения при чтении — presigned GET на 15 минут (ADR 0017 п. 10)."""
    return lambda key: storage.presign_get(key, settings.presign_get_ttl_seconds)


def upload_key(user_id: int, file_name: str, file_type: AttachmentType) -> str:
    extension = PurePosixPath(file_name.replace("\\", "/")).suffix.lower()
    if extension not in EXTENSIONS[file_type]:
        extension = ""
    return f"uploads/{user_id}/{uuid.uuid4()}{extension}"


def presign_upload(
    redis: Redis,
    settings: Settings,
    storage: ObjectStorage,
    user: AppUser,
    file_name: str,
    file_type: AttachmentType,
) -> PresignedUpload:
    """POST /uploads/presign: URL загрузки напрямую в S3, минуя backend."""
    rate_limit.enforce(
        redis,
        f"upload-presign:{user.id}",
        3600,
        settings.upload_presign_per_user_hour,
        "Слишком много загрузок — попробуйте позже",
    )
    key = upload_key(user.id, file_name, file_type)
    ttl = settings.presign_put_ttl_seconds
    expires_at = datetime.now(UTC) + timedelta(seconds=ttl)
    return PresignedUpload(storage.presign_put(key, ttl), key, expires_at)


def _error(index: int, code: str, message: str) -> ApiError:
    loc = ["body", "attachments", index, "file_url"]
    return ApiError(422, code, message, details={"fields": [{"loc": loc}]})


def _media_type(content_type: str) -> str:
    """MIME без параметров и регистра: «Image/JPEG; charset=…» → «image/jpeg»."""
    return content_type.split(";", 1)[0].strip().lower()


def _allowed(settings: Settings, file_type: AttachmentType) -> tuple[tuple[str, ...], int]:
    if file_type is AttachmentType.PHOTO:
        return settings.attachment_photo_mime_types, settings.attachment_photo_max_bytes
    return settings.attachment_video_mime_types, settings.attachment_video_max_bytes


def _already_used(db: Session, name: str) -> bool:
    """Объект уже привязан: имя {uuid}{расширение} уникально, ключ привязки — tickets/{id}/{имя}.

    Транзакционная advisory-блокировка по имени упорядочивает одновременные привязки одной
    загрузки: вторая ждёт commit первой и видит её строку.
    """
    db.execute(select(func.pg_advisory_xact_lock(func.hashtextextended(name, 0))))
    return bool(db.scalar(select(exists().where(TicketAttachment.object_key.endswith(f"/{name}")))))


def check_uploads(
    db: Session,
    storage: ObjectStorage,
    settings: Settings,
    user: AppUser,
    inputs: Sequence[AttachmentInput],
) -> list[Upload]:
    """Проверка вложений запроса до записи в БД; ошибки — 422 с индексом вложения."""
    if len(inputs) > settings.max_attachments:
        raise ApiError(
            422,
            "TOO_MANY_ATTACHMENTS",
            f"Не больше {settings.max_attachments} вложений",
            details={"fields": [{"loc": ["body", "attachments"]}]},
        )
    uploads: list[Upload] = []
    seen: set[str] = set()
    for index, item in enumerate(inputs):
        match = _UPLOAD_KEY.fullmatch(item.file_url)
        if match is None or int(match["user_id"]) != user.id:
            raise _error(index, "ATTACHMENT_NOT_FOUND", "Файл не найден среди ваших загрузок")
        name = match["name"]
        if name in seen or _already_used(db, name):
            raise _error(index, "ATTACHMENT_ALREADY_USED", "Файл уже прикреплён")
        seen.add(name)
        info = storage.head(item.file_url)
        if info is None or info.size == 0:  # пустой объект — загрузка не состоялась
            raise _error(index, "ATTACHMENT_NOT_FOUND", "Файл не найден среди ваших загрузок")
        mime_types, max_bytes = _allowed(settings, item.file_type)
        mime_type = _media_type(info.content_type)
        if mime_type not in mime_types:
            raise _error(
                index,
                "ATTACHMENT_TYPE_NOT_ALLOWED",
                f"Недопустимый тип файла для {item.file_type}: {', '.join(mime_types)}",
            )
        if info.size > max_bytes:
            raise _error(
                index,
                "ATTACHMENT_TOO_LARGE",
                f"Файл больше {max_bytes // (1024 * 1024)} МБ",
            )
        uploads.append(Upload(item.file_url, name, item.file_type, mime_type, info.size))
    return uploads


@contextmanager
def binding(db: Session, storage: ObjectStorage) -> Iterator[list[str]]:
    """Транзакция привязки: при ошибке — откат БД и удаление уже скопированных объектов.

    Блок должен завершаться commit; скопированные ключи накапливаются в отдаваемом списке.
    """
    copied: list[str] = []
    try:
        yield copied
    except BaseException:
        db.rollback()
        _delete_quietly(storage, copied)
        raise


def bind(
    db: Session,
    storage: ObjectStorage,
    user: AppUser,
    uploads: Sequence[Upload],
    copied: list[str],
    *,
    ticket_id: int,
    ticket_message_id: int | None = None,
) -> None:
    """Копирует загрузки в хранилище тикета и добавляет строки ticket_attachment (без commit)."""
    for index, upload in enumerate(uploads):
        key = f"tickets/{ticket_id}/{upload.name}"
        try:
            storage.copy(upload.key, key)
        except ObjectNotFound as exc:  # удалён между HEAD и копированием
            raise _error(
                index, "ATTACHMENT_NOT_FOUND", "Файл не найден среди ваших загрузок"
            ) from exc
        copied.append(key)
        db.add(
            TicketAttachment(
                ticket_id=ticket_id,
                ticket_message_id=ticket_message_id,
                object_key=key,
                file_type=upload.file_type,
                mime_type=upload.mime_type,
                size_bytes=upload.size_bytes,
                uploaded_by_user_id=user.id,
            )
        )
    db.flush()


def discard_uploads(storage: ObjectStorage, uploads: Sequence[Upload]) -> None:
    """После commit: исходные объекты в uploads/ больше не нужны (иначе их удалит lifecycle)."""
    _delete_quietly(storage, [u.key for u in uploads])


def _delete_quietly(storage: ObjectStorage, keys: Sequence[str]) -> None:
    for key in keys:
        try:
            storage.delete(key)
        except StorageError as exc:
            # Ключ объекта не пишем; лишний объект останется до ручной очистки или lifecycle.
            logger.warning("Не удалось удалить объект вложения: %s", type(exc).__name__)
