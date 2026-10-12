"""Вложения тикетов и сообщений через S3 (ADR 0004, ADR 0017 п. 10).

Загрузка: presigned PUT в `uploads/{user_id}/{uuid}{расширение}` — из имени файла берётся
только расширение (имя может содержать ПД и не хранится). Привязка к тикету или сообщению:
1. `check_uploads` — без блокировок: ключ — среди загрузок текущего пользователя, MIME,
   размер и ETag — из HEAD (со слов S3, а не клиента);
2. `bind` — транзакция записи целиком. При входе копирует загрузки — до блокировки строки
   тикета (сетевой ввод-вывод S3 не держит блокировок БД): копия ровно проверенной версии
   (ETag) с проверенным MIME в ключ, уникальный для попытки, —
   `tickets/{ticket_id}/{новый uuid}{расширение}`. Внутри блока сценарий берёт блокировки,
   пишет тикет или сообщение и вызывает `attach` — строки вложений: UNIQUE по имени загрузки
   (`upload_name`) — одна загрузка становится ровно одним вложением. Commit выполняет `bind`
   при выходе из блока (сервисы глав 11–12 делают commit сами — здесь иначе, чтобы порядок
   «копии → строки → commit → удаление исходников» держала структура, а не договорённость).
При ошибке транзакция откатывается и копии этой попытки удаляются: ключи уникальны, поэтому
удаление не заденет объект другой транзакции. После commit исходный объект удаляется;
«сиротские» загрузки удаляет правило жизненного цикла бакета (24 ч).
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
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.core import rate_limit
from app.core.config import Settings
from app.core.errors import ApiError
from app.core.storage import CopySourceChanged, ObjectStorage, StorageError
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
    etag: str


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


def _not_found(index: int) -> ApiError:
    return _error(index, "ATTACHMENT_NOT_FOUND", "Файл не найден среди ваших загрузок")


def _already_used(index: int) -> ApiError:
    return _error(index, "ATTACHMENT_ALREADY_USED", "Файл уже прикреплён")


def check_uploads(
    db: Session,
    storage: ObjectStorage,
    settings: Settings,
    user: AppUser,
    inputs: Sequence[AttachmentInput],
) -> list[Upload]:
    """Проверка вложений запроса до записи в БД и без блокировок; ошибки — 422 с индексом.

    Уже привязанная загрузка отклоняется здесь заранее, без HEAD и копирования; окончательно
    повторную привязку исключает UNIQUE при вставке (`attach` в `bind`).
    """
    if len(inputs) > settings.max_attachments:
        raise ApiError(
            422,
            "TOO_MANY_ATTACHMENTS",
            f"Не больше {settings.max_attachments} вложений",
            details={"fields": [{"loc": ["body", "attachments"]}]},
        )
    names: list[str] = []
    for index, item in enumerate(inputs):
        match = _UPLOAD_KEY.fullmatch(item.file_url)
        if match is None or int(match["user_id"]) != user.id:
            raise _not_found(index)
        if match["name"] in names:
            raise _already_used(index)
        names.append(match["name"])
    if names:
        used = set(
            db.scalars(
                select(TicketAttachment.upload_name).where(TicketAttachment.upload_name.in_(names))
            )
        )
        for index, name in enumerate(names):
            if name in used:
                raise _already_used(index)

    uploads: list[Upload] = []
    for index, (item, name) in enumerate(zip(inputs, names, strict=True)):
        info = storage.head(item.file_url)
        if info is None or info.size == 0:  # пустой объект — загрузка не состоялась
            raise _not_found(index)
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
        uploads.append(Upload(item.file_url, name, item.file_type, mime_type, info.size, info.etag))
    return uploads


# Записывает строки вложений: attach(created_at=…, ticket_message_id=…).
Attach = Callable[..., None]


@contextmanager
def bind(
    db: Session,
    storage: ObjectStorage,
    user: AppUser,
    uploads: Sequence[Upload],
    *,
    ticket_id: int,
) -> Iterator[Attach]:
    """Транзакция привязки: копии → блок сценария с `attach` → commit → удаление исходников.

    Commit — при нормальном выходе из блока; блок без вызова `attach` при непустых `uploads`
    — ошибка программы (вложения иначе пропали бы молча). При любой ошибке, в т. ч. в
    commit, — откат БД и удаление копий этой попытки: ключи уникальны для попытки, поэтому
    удаление после отката (блокировки уже сняты) не заденет объект другой транзакции.
    """
    copied: list[str] = []
    attached = False

    def attach(*, created_at: datetime, ticket_message_id: int | None = None) -> None:
        nonlocal attached
        pairs = list(zip(uploads, copied, strict=True))
        _insert_rows(
            db,
            user,
            pairs,
            ticket_id=ticket_id,
            created_at=created_at,
            ticket_message_id=ticket_message_id,
        )
        attached = True

    try:
        _copy_uploads(storage, uploads, copied, ticket_id=ticket_id)
        yield attach
        if uploads and not attached:
            raise RuntimeError("attachments.bind: вложения не записаны (attach не вызван)")
        db.commit()
    except BaseException:
        db.rollback()
        _delete_quietly(storage, copied)
        raise
    # После commit: исходные объекты в uploads/ больше не нужны (иначе их удалит lifecycle).
    _delete_quietly(storage, [u.key for u in uploads])


def _copy_uploads(
    storage: ObjectStorage, uploads: Sequence[Upload], copied: list[str], *, ticket_id: int
) -> None:
    """Копирует загрузки в хранилище тикета — до блокировок БД; ключи копий — в `copied`.

    Копируется ровно проверенная версия (ETag из HEAD) с проверенным MIME: удалённая или
    перезаписанная после HEAD загрузка — 422 ATTACHMENT_NOT_FOUND, а не копия
    непроверенного файла.
    """
    for index, upload in enumerate(uploads):
        key = f"tickets/{ticket_id}/{uuid.uuid4()}{PurePosixPath(upload.name).suffix}"
        # До вызова: S3 мог выполнить копирование и ответить ошибкой (таймаут ответа).
        copied.append(key)
        try:
            storage.copy(upload.key, key, etag=upload.etag, content_type=upload.mime_type)
        except CopySourceChanged:
            raise _not_found(index) from None


def _insert_rows(
    db: Session,
    user: AppUser,
    pairs: Sequence[tuple[Upload, str]],
    *,
    ticket_id: int,
    created_at: datetime,
    ticket_message_id: int | None,
) -> None:
    """Строки ticket_attachment (загрузка, ключ копии), без commit; уже вложение — 422.

    created_at — момент записи тикета или сообщения (одно значение у строк одной записи).

    INSERT ... ON CONFLICT (upload_name) DO NOTHING: одновременная привязка той же загрузки
    ждёт commit или отката первой и только тогда вставляет или отказывает. Вставка — в порядке
    имён загрузок (один порядок ожиданий во всех транзакциях — без взаимоблокировок), а id
    выдаются заранее в порядке запроса: порядок вложений в ответе — как в запросе.
    """
    if not pairs:
        return
    sequence = func.pg_get_serial_sequence(TicketAttachment.__tablename__, "id")
    series = func.generate_series(1, len(pairs))
    ids = sorted(db.scalars(select(func.nextval(sequence)).select_from(series)))
    rows = sorted(zip(range(len(pairs)), ids, pairs, strict=True), key=lambda row: row[2][0].name)
    for index, attachment_id, (upload, key) in rows:
        inserted = db.scalar(
            insert(TicketAttachment)
            .values(
                id=attachment_id,
                ticket_id=ticket_id,
                ticket_message_id=ticket_message_id,
                object_key=key,
                upload_name=upload.name,
                file_type=upload.file_type,
                mime_type=upload.mime_type,
                size_bytes=upload.size_bytes,
                uploaded_by_user_id=user.id,
                created_at=created_at,
            )
            .on_conflict_do_nothing(index_elements=[TicketAttachment.upload_name])
            .returning(TicketAttachment.id)
        )
        if inserted is None:
            raise _already_used(index)


def _delete_quietly(storage: ObjectStorage, keys: Sequence[str]) -> None:
    for key in keys:
        try:
            storage.delete(key)
        except StorageError as exc:
            # Ключ объекта не пишем; лишний объект останется до ручной очистки или lifecycle.
            logger.warning("Не удалось удалить объект вложения: %s", type(exc).__name__)
