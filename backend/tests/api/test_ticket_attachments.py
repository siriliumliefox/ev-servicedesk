"""Вложения тикетов и сообщений (ADR 0004, ADR 0017 п. 10, 14).

Правила привязки — на хранилище в памяти (`FakeObjectStorage`): загрузку по presigned PUT
имитирует `storage.put`. Полный цикл «на staging» (ADR 0017 п. 14) — на настоящем S3 API
(MinIO из docker compose или контейнер backend-ci): реальные токены Auth → presign → PUT →
тикет с вложением → карточка → claim → чат → resolved → presigned GET.
"""

import re
from urllib.parse import unquote, urlsplit

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.storage import FakeObjectStorage, S3ObjectStorage, get_storage
from app.models import TicketAttachment
from app.models.enums import UserRole
from tests.api.conftest import API, add_vehicle, api_settings, assert_contract

Headers = dict[str, str]
JPEG = b"\xff\xd8\xff\xe0" + b"0" * 64
UPLOAD_KEY = re.compile(r"uploads/(\d+)/[0-9a-f-]{36}(\.[a-z0-9]+)?")


@pytest.fixture
def owner(as_client) -> Headers:
    return as_client("+375294400001")


@pytest.fixture
def vehicle(client: TestClient, owner: Headers) -> dict:
    return add_vehicle(client, owner)


def presign(client: TestClient, headers: Headers, name="IMG 0001.JPG", file_type="photo") -> dict:
    r = client.post(
        f"{API}/uploads/presign", json={"file_name": name, "file_type": file_type}, headers=headers
    )
    assert r.status_code == 200, r.text
    assert_contract(r, "createPresignedUpload")
    return r.json()


def uploaded(
    client: TestClient,
    headers: Headers,
    storage: FakeObjectStorage,
    data: bytes = JPEG,
    mime: str = "image/jpeg",
    file_type: str = "photo",
) -> dict:
    """Загрузка клиентом по presigned PUT (в памяти) → элемент attachments запроса."""
    file_url = presign(client, headers, file_type=file_type)["file_url"]
    storage.put(file_url, data, mime)
    return {"file_url": file_url, "file_type": file_type}


def create(client: TestClient, headers: Headers, vehicle_id: int, attachments: list[dict]):
    return client.post(
        f"{API}/tickets",
        json={
            "vehicle_id": vehicle_id,
            "category": "audio",
            "description": "Хрипит динамик",
            "attachments": attachments,
        },
        headers=headers,
    )


# ---------- Presign ----------


def test_presign_key_layout(client, owner, storage):
    body = presign(client, owner, name="Паспорт Иванова.JPG")
    match = UPLOAD_KEY.fullmatch(body["file_url"])
    assert match, body["file_url"]
    assert match.group(2) == ".jpg", "только расширение, в нижнем регистре"
    assert "Иванова" not in body["file_url"] and "Иванова" not in body["upload_url"]
    assert unquote(urlsplit(body["upload_url"]).path).endswith(body["file_url"])
    assert "X-Fake-Method=PUT" in body["upload_url"]

    for name, file_type, ext in (
        ("clip.MOV", "video", ".mov"),
        ("photo.exe", "photo", None),
        ("clip.jpg", "video", None),  # расширение не по типу — отбрасывается
        ("../../etc/passwd", "photo", None),
        ("noext", "photo", None),
    ):
        key = presign(client, owner, name=name, file_type=file_type)["file_url"]
        assert UPLOAD_KEY.fullmatch(key).group(2) == ext, name


def test_presign_roles_and_validation(client, owner, as_staff):
    admin_headers, _ = as_staff("+375294400002", UserRole.ADMIN)
    r = client.post(
        f"{API}/uploads/presign",
        json={"file_name": "a.jpg", "file_type": "photo"},
        headers=admin_headers,
    )
    assert r.status_code == 403
    assert_contract(r, "createPresignedUpload")
    engineer_headers, _ = as_staff("+375294400003")
    presign(client, engineer_headers)
    for body in (
        {"file_name": "", "file_type": "photo"},
        {"file_name": "a.jpg", "file_type": "pdf"},
    ):
        r = client.post(f"{API}/uploads/presign", json=body, headers=owner)
        assert r.status_code == 422
        assert_contract(r, "createPresignedUpload")


def test_presign_rate_limit(client, app, owner):
    app.dependency_overrides[get_settings] = lambda: api_settings(upload_presign_per_user_hour=2)
    presign(client, owner)
    presign(client, owner)
    r = client.post(
        f"{API}/uploads/presign", json={"file_name": "a.jpg", "file_type": "photo"}, headers=owner
    )
    assert r.status_code == 429
    assert_contract(r, "createPresignedUpload")
    assert int(r.headers["Retry-After"]) >= 1


# ---------- Привязка ----------


def test_attachment_is_copied_and_presigned_on_read(client, owner, vehicle, storage, db: Session):
    item = uploaded(client, owner, storage, mime="Image/JPEG; charset=binary")
    r = create(client, owner, vehicle["id"], [item])
    assert r.status_code == 201, r.text
    assert_contract(r, "createTicket")
    ticket = r.json()

    [row] = db.scalars(select(TicketAttachment).where(TicketAttachment.ticket_id == ticket["id"]))
    name = item["file_url"].rsplit("/", 1)[1]
    assert row.object_key == f"tickets/{ticket['id']}/{name}"
    assert (row.mime_type, row.size_bytes, row.ticket_message_id) == ("image/jpeg", len(JPEG), None)
    assert storage.objects[row.object_key][0] == JPEG
    assert item["file_url"] not in storage.objects, "исходная загрузка удалена после привязки"

    [att] = ticket["attachments"]
    assert att["file_type"] == "photo"
    assert "X-Fake-Method=GET" in att["file_url"] and row.object_key in unquote(att["file_url"])


def test_message_attachments(client, owner, vehicle, storage, db: Session):
    tid = create(client, owner, vehicle["id"], []).json()["id"]
    video = uploaded(client, owner, storage, b"\x00\x00\x00\x18ftypmp42", "video/mp4", "video")
    r = client.post(
        f"{API}/tickets/{tid}/messages",
        json={"body": "Видео", "attachments": [video]},
        headers=owner,
    )
    assert r.status_code == 201, r.text
    assert_contract(r, "createTicketMessage")
    message = r.json()
    assert [a["file_type"] for a in message["attachments"]] == ["video"]
    row = db.scalars(select(TicketAttachment).where(TicketAttachment.ticket_id == tid)).one()
    assert row.ticket_message_id == message["id"]

    r = client.get(f"{API}/tickets/{tid}", headers=owner)
    assert r.json()["attachments"] == [], "вложения сообщений — не вложения тикета"
    r = client.get(f"{API}/tickets/{tid}/messages", headers=owner)
    assert [a["file_type"] for a in r.json()["items"][0]["attachments"]] == ["video"]


def test_attachment_errors(client, owner, as_client, vehicle, storage, app, db: Session):
    stranger = as_client("+375294400011")

    def code(attachments: list[dict]) -> str:
        r = create(client, owner, vehicle["id"], attachments)
        assert r.status_code == 422, r.text
        assert_contract(r, "createTicket")
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
    assert code([uploaded(client, owner, storage) for _ in range(11)]) == "TOO_MANY_ATTACHMENTS"

    assert create(client, owner, vehicle["id"], [item]).status_code == 201
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

    def flaky_copy(src: str, dst: str) -> None:
        if src == second["file_url"]:
            raise RuntimeError("сбой S3 при копировании")
        real_copy(src, dst)

    monkeypatch.setattr(storage, "copy", flaky_copy)
    with pytest.raises(RuntimeError):
        create(client, owner, vehicle["id"], [first, second])
    assert not [k for k in storage.objects if k.startswith("tickets/")], "копия удалена"
    assert first["file_url"] in storage.objects, "исходная загрузка не тронута"
    assert db.scalars(select(TicketAttachment)).all() == []


def test_storage_unavailable_is_server_error(app, owner, vehicle, storage):
    item = uploaded(TestClient(app), owner, storage)
    storage.available = False
    r = create(TestClient(app, raise_server_exceptions=False), owner, vehicle["id"], [item])
    assert r.status_code == 500
    assert_contract(r, "createTicket")


# ---------- Полный цикл на MinIO (ADR 0017 п. 14) ----------


@pytest.fixture
def minio(s3_storage: S3ObjectStorage, app) -> S3ObjectStorage:
    app.dependency_overrides[get_storage] = lambda: s3_storage
    return s3_storage


def test_full_cycle_on_minio(client, owner, as_staff, vehicle, minio, db: Session):
    data = b"\x89PNG\r\n\x1a\n" + bytes(range(256)) * 4
    target = presign(client, owner, name="screen.png")
    r = httpx.put(target["upload_url"], content=data, headers={"Content-Type": "image/png"})
    assert r.status_code == 200, r.text

    r = create(
        client, owner, vehicle["id"], [{"file_url": target["file_url"], "file_type": "photo"}]
    )
    assert r.status_code == 201, r.text
    ticket = r.json()
    tid = ticket["id"]
    assert ticket["vehicle_model"]["brand"] == "Zeekr"
    assert (
        "firmware_version_at_creation" in ticket
        and "aggregate_statuses" in ticket["vehicle_context"]
    )
    assert minio.head(target["file_url"]) is None, "исходная загрузка удалена"
    info = minio.head(f"tickets/{tid}/{target['file_url'].rsplit('/', 1)[1]}")
    assert info is not None and (info.size, info.content_type) == (len(data), "image/png")

    eng_headers, _ = as_staff("+375294400021")
    assert client.post(f"{API}/tickets/{tid}/claim", headers=eng_headers).status_code == 200

    reply = presign(client, eng_headers, name="diag.mp4", file_type="video")
    clip = b"\x00\x00\x00\x18ftypmp42" + b"\x00" * 128
    r = httpx.put(reply["upload_url"], content=clip, headers={"Content-Type": "video/mp4"})
    assert r.status_code == 200
    r = client.post(
        f"{API}/tickets/{tid}/messages",
        json={
            "body": "Обновите прошивку",
            "attachments": [{"file_url": reply["file_url"], "file_type": "video"}],
        },
        headers=eng_headers,
    )
    assert r.status_code == 201, r.text
    assert_contract(r, "createTicketMessage")

    r = client.patch(
        f"{API}/tickets/{tid}/status", json={"status": "resolved"}, headers=eng_headers
    )
    assert r.status_code == 200 and r.json()["status"] == "resolved"

    r = client.get(f"{API}/tickets/{tid}", headers=owner)
    assert_contract(r, "getTicket")
    [att] = r.json()["attachments"]
    got = httpx.get(att["file_url"])
    assert got.status_code == 200 and got.content == data, "presigned GET отдаёт тот же файл"

    r = client.get(f"{API}/tickets/{tid}/messages", headers=owner)
    [message] = r.json()["items"]
    assert message["author"]["phone"] is None
    assert httpx.get(message["attachments"][0]["file_url"]).content == clip

    # Чужая загрузка в MinIO не привязывается: префикс владельца проверяется до HEAD.
    stranger = presign(client, eng_headers)
    httpx.put(stranger["upload_url"], content=JPEG, headers={"Content-Type": "image/jpeg"})
    r = create(
        client, owner, vehicle["id"], [{"file_url": stranger["file_url"], "file_type": "photo"}]
    )
    assert r.status_code == 422 and r.json()["error"]["code"] == "ATTACHMENT_NOT_FOUND"
