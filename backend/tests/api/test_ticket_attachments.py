"""Вложения тикетов и сообщений (ADR 0004, ADR 0017 п. 10, 14).

Правила привязки — на хранилище в памяти (`FakeObjectStorage`): загрузку по presigned PUT
имитирует `storage.put`. Перезапись загрузки после проверки — ещё и на настоящем S3 API
(MinIO из docker compose или контейнер backend-ci). Полный цикл «на staging» (ADR 0017
п. 14) — tests/api/test_ticket_checklist.py; presigned URL на MinIO —
tests/api/test_ticket_privacy.py.
"""

import re
from urllib.parse import unquote

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.storage import ObjectStorage, StorageUnavailable
from app.models import Ticket, TicketAttachment, TicketMessage
from app.models.enums import UserRole
from tests.api.conftest import API, ContractClient, Headers, add_vehicle, api_settings
from tests.api.ticket_support import (
    JPEG,
    MP4,
    UPLOAD_KEY,
    create_ticket,
    presign,
    put_upload,
)

UUID = r"[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}"


def copy_key(ticket_id: int, extension: str = ".jpg") -> re.Pattern[str]:
    """Ключ копии вложения: tickets/{ticket_id}/{новый uuid}{расширение загрузки}."""
    return re.compile(rf"tickets/{ticket_id}/{UUID}{re.escape(extension)}")


@pytest.fixture
def owner(as_client) -> Headers:
    return as_client("+375294400001")


@pytest.fixture
def vehicle(client: TestClient, owner: Headers) -> dict:
    return add_vehicle(client, owner)


def uploaded(
    client: TestClient,
    headers: Headers,
    storage: ObjectStorage,
    data: bytes = JPEG,
    mime: str = "image/jpeg",
    file_type: str = "photo",
) -> dict:
    """Загрузка клиентом по presigned PUT → элемент attachments запроса."""
    target = presign(client, headers, file_type=file_type)
    put_upload(storage, target, data, mime)
    return {"file_url": target["file_url"], "file_type": file_type}


# ---------- Presign ----------


def test_presign_roles_and_validation(client, owner, as_staff):
    # admin пишет в чат любого тикета (RBAC-04) — и загружает вложения (решение 2026-10-12).
    admin_headers, admin = as_staff("+375294400002", UserRole.ADMIN)
    assert UPLOAD_KEY.fullmatch(presign(client, admin_headers)["file_url"]).group(1) == str(
        admin.id
    )
    engineer_headers, _ = as_staff("+375294400003")
    presign(client, engineer_headers)
    for body in (
        {"file_name": "", "file_type": "photo"},
        {"file_name": "a.jpg", "file_type": "pdf"},
    ):
        r = client.post(f"{API}/uploads/presign", json=body, headers=owner)
        assert r.status_code == 422


def test_presign_rate_limit(client, app, owner):
    app.dependency_overrides[get_settings] = lambda: api_settings(upload_presign_per_user_hour=2)
    presign(client, owner)
    presign(client, owner)
    r = client.post(
        f"{API}/uploads/presign", json={"file_name": "a.jpg", "file_type": "photo"}, headers=owner
    )
    assert r.status_code == 429
    assert int(r.headers["Retry-After"]) >= 1


# ---------- Привязка ----------


def test_attachment_is_copied_and_presigned_on_read(client, owner, vehicle, storage, db: Session):
    item = uploaded(client, owner, storage, mime="Image/JPEG; charset=binary")
    r = create_ticket(client, owner, vehicle["id"], attachments=[item])
    assert r.status_code == 201, r.text
    ticket = r.json()

    [row] = db.scalars(select(TicketAttachment).where(TicketAttachment.ticket_id == ticket["id"]))
    name = item["file_url"].rsplit("/", 1)[1]
    assert copy_key(ticket["id"]).fullmatch(row.object_key), row.object_key
    assert row.upload_name == name and name not in row.object_key, "ключ копии — новый"
    assert (row.mime_type, row.size_bytes, row.ticket_message_id) == ("image/jpeg", len(JPEG), None)
    # MIME копии — проверенный (без параметров), а не присланный клиентом.
    assert storage.objects[row.object_key] == (JPEG, "image/jpeg")
    assert item["file_url"] not in storage.objects, "исходная загрузка удалена после привязки"

    [att] = ticket["attachments"]
    assert att["file_type"] == "photo"
    assert "X-Fake-Method=GET" in att["file_url"] and row.object_key in unquote(att["file_url"])
    assert "X-Fake-Content-Type=image%2Fjpeg" in att["file_url"], "Content-Type ответа — из БД"


@pytest.mark.parametrize("operation", ["createTicket", "createTicketMessage"])
def test_upload_overwritten_after_check_is_not_copied(
    client, owner, vehicle, storage, monkeypatch, db: Session, operation
):
    """Загрузка перезаписана тем же presigned PUT между HEAD и копированием (TOCTOU).

    Копируется только проверенная версия (ETag): иначе в tickets/ оказался бы HTML на 30 МБ
    с записью «image/jpeg, 68 байт» в БД — в обход списка MIME и лимита размера.
    """
    tid = create_ticket(client, owner, vehicle["id"]).json()["id"]
    item = uploaded(client, owner, storage)
    real_head = storage.head

    def head_then_swap(key: str):
        info = real_head(key)
        storage.put(key, b"<html>" * 5_000_000, "text/html")  # гонка: PUT после HEAD
        return info

    monkeypatch.setattr(storage, "head", head_then_swap)
    if operation == "createTicket":
        r = create_ticket(client, owner, vehicle["id"], attachments=[item])
    else:
        r = client.post(
            f"{API}/tickets/{tid}/messages",
            json={"body": "Фото", "attachments": [item]},
            headers=owner,
        )
    assert r.status_code == 422, r.text
    assert r.json()["error"]["code"] == "ATTACHMENT_NOT_FOUND"
    assert r.json()["error"]["details"]["fields"] == [
        {"loc": ["body", "attachments", 0, "file_url"]}
    ]
    assert not [k for k in storage.objects if k.startswith("tickets/")], "копии нет"
    assert db.scalars(select(TicketAttachment)).all() == []


def test_message_attachments(client, owner, vehicle, storage, db: Session):
    tid = create_ticket(client, owner, vehicle["id"]).json()["id"]
    video = uploaded(client, owner, storage, MP4, "video/mp4", "video")
    r = client.post(
        f"{API}/tickets/{tid}/messages",
        json={"body": "Видео", "attachments": [video]},
        headers=owner,
    )
    assert r.status_code == 201, r.text
    message = r.json()
    assert [a["file_type"] for a in message["attachments"]] == ["video"]
    row = db.scalars(select(TicketAttachment).where(TicketAttachment.ticket_id == tid)).one()
    assert row.ticket_message_id == message["id"]

    r = client.get(f"{API}/tickets/{tid}", headers=owner)
    assert r.json()["attachments"] == [], "вложения сообщений — не вложения тикета"
    r = client.get(f"{API}/tickets/{tid}/messages", headers=owner)
    assert [a["file_type"] for a in r.json()["items"][0]["attachments"]] == ["video"]


def test_timestamps_of_one_write_are_equal(client, owner, vehicle, storage, db: Session):
    """Тикет, сообщение и их вложения: одна метка «момент записи» (ADR 0017, «Уточнения»)."""
    photo = uploaded(client, owner, storage, b"\xff\xd8\xff\xe0jpeg", "image/jpeg")
    tid = create_ticket(client, owner, vehicle["id"], attachments=[photo]).json()["id"]
    ticket = db.get(Ticket, tid)
    row = db.scalars(select(TicketAttachment).where(TicketAttachment.ticket_id == tid)).one()
    assert ticket.updated_at == ticket.created_at == row.created_at

    video = uploaded(client, owner, storage, MP4, "video/mp4", "video")
    r = client.post(
        f"{API}/tickets/{tid}/messages",
        json={"body": "Видео", "attachments": [video]},
        headers=owner,
    )
    assert r.status_code == 201, r.text
    message = db.get(TicketMessage, r.json()["id"])
    row = db.scalars(
        select(TicketAttachment).where(TicketAttachment.ticket_message_id == message.id)
    ).one()
    assert row.created_at == message.created_at


def test_attachment_errors(client, owner, as_client, vehicle, storage, app, db: Session):
    stranger = as_client("+375294400011")

    def code(attachments: list[dict]) -> str:
        r = create_ticket(client, owner, vehicle["id"], attachments=attachments)
        assert r.status_code == 422, r.text
        return r.json()["error"]["code"]

    foreign = uploaded(client, stranger, storage)
    assert code([foreign]) == "ATTACHMENT_NOT_FOUND", "чужая загрузка"
    never_uploaded = {"file_url": presign(client, owner)["file_url"], "file_type": "photo"}
    assert code([never_uploaded]) == "ATTACHMENT_NOT_FOUND"
    assert code([{"file_url": "tickets/1/x.jpg", "file_type": "photo"}]) == "ATTACHMENT_NOT_FOUND"
    traversal = uploaded(client, owner, storage)
    prefix, name = traversal["file_url"].rsplit("/", 1)
    sneaky = {"file_url": f"{prefix}/../{prefix}/{name}", "file_type": "photo"}
    assert code([sneaky]) == "ATTACHMENT_NOT_FOUND"
    empty = uploaded(client, owner, storage, data=b"")
    assert code([empty]) == "ATTACHMENT_NOT_FOUND"

    pdf = uploaded(client, owner, storage, mime="application/pdf")
    assert code([pdf]) == "ATTACHMENT_TYPE_NOT_ALLOWED"
    mismatch = uploaded(client, owner, storage, mime="video/mp4")  # file_type=photo
    assert code([mismatch]) == "ATTACHMENT_TYPE_NOT_ALLOWED"
    gif = uploaded(client, owner, storage, mime="image/gif")
    assert code([gif]) == "ATTACHMENT_TYPE_NOT_ALLOWED"

    item = uploaded(client, owner, storage)
    assert code([item, item]) == "ATTACHMENT_ALREADY_USED"
    # Управляющие символы C1 (U+0080–U+009F) — как C0: 422 (ADR 0017, «Уточнения»).
    for text in ("a\x85b", "a\x9bb", "a\u0080b", "a\u009fb"):
        r = client.post(
            f"{API}/tickets",
            json={"vehicle_id": vehicle["id"], "category": "audio", "description": text},
            headers=owner,
        )
        assert r.status_code == 422 and r.json()["error"]["code"] == "VALIDATION_ERROR", text
    assert code([uploaded(client, owner, storage) for _ in range(11)]) == "TOO_MANY_ATTACHMENTS"

    assert create_ticket(client, owner, vehicle["id"], attachments=[item]).status_code == 201
    storage.put(item["file_url"], JPEG, "image/jpeg")  # повторная загрузка в тот же ключ
    assert code([item]) == "ATTACHMENT_ALREADY_USED"

    app.dependency_overrides[get_settings] = lambda: api_settings(attachment_photo_max_bytes=10)
    assert code([uploaded(client, owner, storage)]) == "ATTACHMENT_TOO_LARGE"

    # Отказ не оставляет ни тикета, ни копий в tickets/.
    assert len(db.scalars(select(TicketAttachment)).all()) == 1
    assert sum(k.startswith("tickets/") for k in storage.objects) == 1


def test_failed_binding_removes_copies(client, owner, vehicle, storage, monkeypatch, db: Session):
    first, second = uploaded(client, owner, storage), uploaded(client, owner, storage)
    real_copy = storage.copy

    def flaky_copy(src: str, dst: str, **kwargs) -> None:
        if src == second["file_url"]:
            raise RuntimeError("сбой S3 при копировании")
        real_copy(src, dst, **kwargs)

    monkeypatch.setattr(storage, "copy", flaky_copy)
    with pytest.raises(RuntimeError):
        create_ticket(client, owner, vehicle["id"], attachments=[first, second])
    assert not [k for k in storage.objects if k.startswith("tickets/")], "копия удалена"
    assert first["file_url"] in storage.objects, "исходная загрузка не тронута"
    assert db.scalars(select(TicketAttachment)).all() == []


def test_copy_reported_as_failed_is_removed(app, owner, vehicle, storage, monkeypatch, db: Session):
    """S3 выполнил копирование, но ответ потерян (таймаут): копия не остаётся «сиротой».

    Под tickets/ правило жизненного цикла не действует, а тикета для неё нет.
    """
    item = uploaded(ContractClient(app), owner, storage)
    real_copy = storage.copy

    def copy_then_timeout(src: str, dst: str, **kwargs) -> None:
        real_copy(src, dst, **kwargs)
        raise StorageUnavailable("S3 copy_object: ReadTimeoutError")

    monkeypatch.setattr(storage, "copy", copy_then_timeout)
    r = create_ticket(
        ContractClient(app, raise_server_exceptions=False), owner, vehicle["id"], attachments=[item]
    )
    assert r.status_code == 500
    assert not [k for k in storage.objects if k.startswith("tickets/")], "копия удалена"
    assert item["file_url"] in storage.objects
    assert db.scalars(select(TicketAttachment)).all() == []


def test_each_binding_attempt_copies_to_new_key(client, owner, vehicle, storage, monkeypatch):
    """Ключ копии уникален для попытки: удаление копий неудачной попытки не заденет объект
    удачной (той же загрузки в тот же тикет), даже если выполняется после её commit.
    """
    tid = create_ticket(client, owner, vehicle["id"]).json()["id"]
    item = uploaded(client, owner, storage)
    destinations: list[str] = []
    real_copy = storage.copy

    def recording_copy(src: str, dst: str, **kwargs) -> None:
        destinations.append(dst)
        real_copy(src, dst, **kwargs)
        if len(destinations) == 1:
            raise StorageUnavailable("S3 copy_object: ReadTimeoutError")

    monkeypatch.setattr(storage, "copy", recording_copy)
    message = {"body": "Фото", "attachments": [item]}
    failing = ContractClient(client.app, raise_server_exceptions=False)
    assert (
        failing.post(f"{API}/tickets/{tid}/messages", json=message, headers=owner).status_code
        == 500
    )
    r = client.post(f"{API}/tickets/{tid}/messages", json=message, headers=owner)
    assert r.status_code == 201, r.text
    first, second = destinations
    assert first != second and all(copy_key(tid).fullmatch(k) for k in destinations)
    assert first not in storage.objects and second in storage.objects


def test_storage_unavailable_is_server_error(app, owner, vehicle, storage):
    item = uploaded(ContractClient(app), owner, storage)
    storage.available = False
    r = create_ticket(
        ContractClient(app, raise_server_exceptions=False), owner, vehicle["id"], attachments=[item]
    )
    assert r.status_code == 500


def test_upload_overwritten_after_check_on_minio(
    client, owner, vehicle, minio, monkeypatch, db: Session
):
    """TOCTOU на настоящем S3 API: перезапись тем же presigned PUT после HEAD — копии нет."""
    target = presign(client, owner, name="panel.jpg")
    put_upload(minio, target, JPEG, "image/jpeg")
    real_head = minio.head

    def head_then_swap(key: str):
        info = real_head(key)
        put_upload(minio, target, b"<html>" * 1000, "text/html")
        return info

    monkeypatch.setattr(minio, "head", head_then_swap)
    item = {"file_url": target["file_url"], "file_type": "photo"}
    r = create_ticket(client, owner, vehicle["id"], attachments=[item])
    assert r.status_code == 422, r.text
    assert r.json()["error"]["code"] == "ATTACHMENT_NOT_FOUND"
    assert db.scalars(select(TicketAttachment)).all() == []
