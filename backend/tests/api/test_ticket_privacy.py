"""ПД и выдача файлов в Tickets Service и Uploads (Глава 13, ADR 0017 п. 10, 12).

- контакты сотрудника скрыты от клиента в REST и в кадрах WebSocket по роли получателя;
- описания, тексты, имена файлов и ключи объектов не попадают в логи;
- ключ загрузки не содержит имени файла;
- file_url при чтении — presigned GET на 15 минут, подписанный для публичного адреса S3;
  полный путь вложения на MinIO: presign → PUT → копия в tickets/ → чтение тремя ролями.

Участники и тикеты — tests/api/ticket_world.py; доступ — tests/api/test_ticket_security.py.
"""

import json
import logging
import re
import uuid
from collections.abc import Iterable
from contextlib import ExitStack
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import parse_qs, unquote, urlencode, urlsplit, urlunsplit

import botocore.auth
import httpx
import pytest
from botocore.config import Config as BotoConfig
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core import storage as storage_module
from app.core.storage import ObjectStorage, S3ObjectStorage, StorageUnavailable, get_storage
from app.models import TicketAttachment
from tests.api.conftest import API, ContractClient, error_code, telegram_widget
from tests.api.ticket_support import JPEG, MP4, UPLOAD_KEY, presign, put_upload
from tests.api.ticket_world import (
    ADMIN,
    ASSIGNED,
    CLIENTS,
    ENGINEER,
    OWNER,
    PHONES,
    STAFF,
    World,
    build_world,
)
from tests.api.ticket_ws import assert_frame, auth, connect, receive, receive_event
from tests.support.storage import FakeObjectStorage

PNG = b"\x89PNG\r\n\x1a\n" + bytes(range(256)) * 4


@pytest.fixture
def world(client: TestClient, login_client, as_staff, make_ticket, db: Session) -> World:
    return build_world(client, login_client, as_staff, make_ticket, db)


# ---------- ПД: контакты сотрудника скрыты от клиента (п. 12) ----------


def give_contacts(client: TestClient, world: World, db: Session) -> dict[str, tuple[str, str]]:
    """Телефон и Telegram у всех авторов: клиент привязывает Telegram сам, персоналу — в БД."""
    contacts = {}
    for n, actor in enumerate((OWNER, ENGINEER, ADMIN)):
        telegram_id = f"7731{n}"
        if actor == OWNER:
            r = client.post(
                f"{API}/auth/telegram/link",
                json=telegram_widget(telegram_id),
                headers=world.headers(actor),
            )
            assert r.status_code == 200, r.text
        else:
            world.users[actor].telegram_id = telegram_id
        contacts[actor] = (PHONES[actor], telegram_id)
    db.commit()
    return contacts


def seen_contacts(viewer: str, author: str, contacts: dict) -> tuple[str | None, str | None]:
    """Телефон и Telegram автора глазами получателя: клиенту контакты сотрудника — null."""
    return (None, None) if viewer in CLIENTS and author in STAFF else contacts[author]


def test_rest_hides_staff_contacts_from_client(client, world, db):
    contacts = give_contacts(client, world, db)
    tid = world.tickets[ASSIGNED]
    authors = {}
    for author in (OWNER, ENGINEER, ADMIN):
        r = client.post(
            f"{API}/tickets/{tid}/messages",
            json={"body": f"Сообщение: {author}"},
            headers=world.headers(author),
        )
        assert r.status_code == 201, r.text
        me = r.json()["author"]
        assert (me["phone"], me["telegram_id"]) == contacts[author], "автор видит себя полностью"
        authors[r.json()["id"]] = author

    for viewer in (OWNER, ENGINEER, ADMIN):
        r = client.get(f"{API}/tickets/{tid}/messages", headers=world.headers(viewer))
        items = r.json()["items"]
        assert {m["id"] for m in items} == set(authors)
        for m in items:
            author = authors[m["id"]]
            got = (m["author"]["phone"], m["author"]["telegram_id"])
            assert got == seen_contacts(viewer, author, contacts), (viewer, author)

    # Ни один ответ Tickets клиенту не содержит контактов персонала.
    for path in ("/tickets", f"/tickets/{tid}", f"/tickets/{tid}/messages"):
        text = client.get(f"{API}{path}", headers=world.headers(OWNER)).text
        for staff in (ENGINEER, ADMIN):
            assert not any(value in text for value in contacts[staff]), (path, staff)


def test_ws_frames_hide_staff_contacts_per_recipient(
    client, world, db, real_redis, storage, settings
):
    contacts = give_contacts(client, world, db)
    tid = world.tickets[ASSIGNED]
    get_ttl = settings.presign_get_ttl_seconds
    # Авторизация — сразу после подключения каждого сокета (тайм-аут кадра auth).
    with ExitStack() as stack:
        sockets = {}
        for actor in (OWNER, ENGINEER, ADMIN):
            sockets[actor] = ws = stack.enter_context(connect(client, tid))
            auth(ws, world.tokens[actor])

        for author in (OWNER, ENGINEER, ADMIN):
            body: dict[str, Any] = {"body": f"Сообщение: {author}"}
            upload = presign(client, world.headers(author), "фото.jpg")
            put_upload(storage, upload, JPEG, "image/jpeg")
            body["attachments"] = [{"file_url": upload["file_url"], "file_type": "photo"}]
            r = client.post(
                f"{API}/tickets/{tid}/messages", json=body, headers=world.headers(author)
            )
            assert r.status_code == 201, r.text

            for viewer, ws in sockets.items():
                raw = receive(ws)["text"]
                data = assert_frame(json.loads(raw), "message.created", "TicketMessage")
                assert data["id"] == r.json()["id"]
                got = (data["author"]["phone"], data["author"]["telegram_id"])
                assert got == seen_contacts(viewer, author, contacts), (viewer, author)
                if viewer in CLIENTS and author in STAFF:
                    assert not any(value in raw for value in contacts[author]), (viewer, author)
                for attachment in data["attachments"]:  # presigned GET, не ключ загрузки
                    url = unquote(attachment["file_url"])
                    assert f"/tickets/{tid}/" in url and "/uploads/" not in url
                    assert "X-Fake-Method=GET" in url and f"X-Fake-Expires={get_ttl}" in url
                    assert "X-Fake-Content-Type=image/jpeg" in url, "Content-Type ответа — из БД"


# ---------- ПД: тексты, имена файлов и ключи объектов не пишутся в логи ----------

SECRET_DESCRIPTION = "Описание-ПД-q7z: Иванов Иван Иванович, ул. Тайная, 5"
SECRET_BODIES = {
    OWNER: "Текст-ПД-k3x: паспорт MP1234567",
    ENGINEER: "Ответ-ПД-w9v: перезвоните на +375291112233",
}
SECRET_FILES = {  # имя файла, тип вложения, MIME, содержимое
    OWNER: ("Паспорт-Иванова-q7z.jpg", "photo", "image/jpeg", JPEG),
    ENGINEER: ("Видео-Петрова-w9v.mp4", "video", "video/mp4", MP4),
}
SECRET_FRAGMENTS = ("Иванов", "Петрова", "MP1234567", "375291112233", "q7z", "k3x", "w9v")
# Транспорт S3 (botocore, urllib3) на DEBUG пишет URL запросов — с ключом объекта. Это
# отладка библиотек, а не журнал приложения: root-логгер по умолчанию — WARNING, приложение
# его не понижает.
S3_TRANSPORT_LOGGERS = ("botocore", "boto3", "urllib3", "s3transfer")
_FORMATTER = logging.Formatter("%(name)s %(levelname)s %(message)s")


def leaks(
    records: Iterable[logging.LogRecord], secrets: Iterable[str], skip: tuple[str, ...] = ()
) -> list[str]:
    """Секреты в записях лога: текст, шаблон, аргументы, трассировка и extra-поля."""
    found = []
    secrets = [s for s in secrets if s]
    for record in records:
        if record.name.startswith(skip):
            continue
        haystack = "\n".join(
            (_FORMATTER.format(record), repr(record.msg), repr(record.args), repr(vars(record)))
        )
        found += [f"{record.name} {record.levelname}: {s!r}" for s in secrets if s in haystack]
    return found


@pytest.fixture(params=["memory", "minio"])
def attachment_storage(request, storage: ObjectStorage) -> ObjectStorage:
    """Хранилище вложений: в памяти и настоящий S3 API (MinIO)."""
    if request.param == "memory":
        return storage
    return request.getfixturevalue("minio")


def test_logs_have_no_texts_file_names_or_object_keys(
    client, world, attachment_storage, db, caplog
):
    caplog.set_level(logging.DEBUG)
    uploaded: list[str] = []

    def attach(actor: str) -> dict[str, str]:
        file_name, file_type, mime, data = SECRET_FILES[actor]
        upload = presign(client, world.headers(actor), file_name, file_type)
        put_upload(attachment_storage, upload, data, mime)
        uploaded.append(upload["file_url"])
        return {"file_url": upload["file_url"], "file_type": file_type}

    r = client.post(
        f"{API}/tickets",
        json={
            "vehicle_id": world.vehicles[OWNER],
            "category": "audio",
            "description": SECRET_DESCRIPTION,
            "attachments": [attach(OWNER)],
        },
        headers=world.headers(OWNER),
    )
    assert r.status_code == 201, r.text
    tid = r.json()["id"]
    r = client.post(f"{API}/tickets/{tid}/claim", headers=world.headers(ENGINEER))
    assert r.status_code == 200, r.text
    for actor in (OWNER, ENGINEER):
        r = client.post(
            f"{API}/tickets/{tid}/messages",
            json={"body": SECRET_BODIES[actor], "attachments": [attach(actor)]},
            headers=world.headers(actor),
        )
        assert r.status_code == 201, r.text
    for actor in (OWNER, ENGINEER, ADMIN):
        for path in ("/tickets", f"/tickets/{tid}", f"/tickets/{tid}/messages"):
            assert client.get(f"{API}{path}", headers=world.headers(actor)).status_code == 200
    # Отказы тоже не пишут присланное: повторная привязка и чужая загрузка.
    for file_url in (uploaded[0], uploaded[-1]):
        r = client.post(
            f"{API}/tickets/{tid}/messages",
            json={
                "body": SECRET_BODIES[OWNER],
                "attachments": [{"file_url": file_url, "file_type": "photo"}],
            },
            headers=world.headers(OWNER),
        )
        assert r.status_code == 422, r.text

    names = [key.rsplit("/", 1)[1] for key in uploaded]
    copies = list(db.scalars(select(TicketAttachment.object_key)))
    assert len(copies) == len(uploaded)
    secrets = [
        SECRET_DESCRIPTION,
        *SECRET_BODIES.values(),
        *(file_name for file_name, *_ in SECRET_FILES.values()),
        *SECRET_FRAGMENTS,
        *uploaded,
        *names,
        *copies,
        *(key.rsplit("/", 1)[1] for key in copies),
    ]
    skip = () if isinstance(attachment_storage, FakeObjectStorage) else S3_TRANSPORT_LOGGERS
    assert caplog.records, "логи перехватываются"
    assert not leaks(caplog.records, secrets, skip)


def test_failed_cleanup_is_logged_without_object_key(client, world, storage, monkeypatch, caplog):
    upload = presign(client, world.headers(OWNER), "Паспорт-Иванова-q7z.jpg")
    put_upload(storage, upload, JPEG, "image/jpeg")

    def failing_delete(key: str) -> None:
        raise StorageUnavailable(f"S3 delete_object: нет связи, {key}")

    monkeypatch.setattr(storage, "delete", failing_delete)
    caplog.set_level(logging.DEBUG)
    r = client.post(
        f"{API}/tickets",
        json={
            "vehicle_id": world.vehicles[OWNER],
            "category": "audio",
            "description": SECRET_DESCRIPTION,
            "attachments": [{"file_url": upload["file_url"], "file_type": "photo"}],
        },
        headers=world.headers(OWNER),
    )
    assert r.status_code == 201, "исходная загрузка останется до правила жизненного цикла"
    warned = [rec for rec in caplog.records if rec.name == "app.domain.tickets.attachments"]
    assert warned and warned[0].levelno == logging.WARNING
    name = upload["file_url"].rsplit("/", 1)[1]
    assert not leaks(caplog.records, [upload["file_url"], name, "Иванова", SECRET_DESCRIPTION])


def test_s3_outage_error_log_has_no_object_key(app, world, storage, monkeypatch, caplog):
    client = ContractClient(app, raise_server_exceptions=False)
    upload = presign(client, world.headers(OWNER), "Паспорт-Иванова-q7z.jpg")
    # Без повторных попыток botocore: тест не ждёт backoff; сбой тот же — нет соединения.
    no_retries = BotoConfig(retries={"max_attempts": 1, "mode": "standard"})
    monkeypatch.setattr(
        storage_module, "_BOTO_CONFIG", storage_module._BOTO_CONFIG.merge(no_retries)
    )
    down = S3ObjectStorage(
        endpoint="http://127.0.0.1:9",  # порт discard: соединение отклоняется
        bucket="ev-servicedesk-down-test",
        access_key="test-access",
        secret_key="test-secret",
        region="us-east-1",
    )
    app.dependency_overrides[get_storage] = lambda: down
    caplog.set_level(logging.WARNING)  # как в production: отладка библиотек не пишется
    r = client.post(
        f"{API}/tickets",
        json={
            "vehicle_id": world.vehicles[OWNER],
            "category": "audio",
            "description": "x",
            "attachments": [{"file_url": upload["file_url"], "file_type": "photo"}],
        },
        headers=world.headers(OWNER),
    )
    assert r.status_code == 500
    assert caplog.records, "сбой залогирован"
    name = upload["file_url"].rsplit("/", 1)[1]
    assert not leaks(caplog.records, [upload["file_url"], name])


# ---------- Presigned URL (п. 10) ----------

ALLOWED_EXTENSIONS = {".jpg", ".jpeg", ".png", ".heic", ".heif", ".webp", ".mp4", ".mov"}
UPLOAD_NAMES = [  # имя файла, тип вложения, расширение ключа
    ("Паспорт Иванова И.И.JPG", "photo", ".jpg"),
    ("IMG_20260101_375291234567.jpeg", "photo", ".jpeg"),
    ("C:\\Users\\Ivanov\\Desktop\\права.png", "photo", ".png"),
    ("../../../etc/Петров/evil.webp", "photo", ".webp"),
    ("../../etc/passwd", "photo", None),
    ("selfie.HEIC", "photo", ".heic"),
    ("Видео с регистратора.MOV", "video", ".mov"),
    ("dashcam.mp4", "video", ".mp4"),
    ("скан.jpg.exe", "photo", None),
    ("отчёт.pdf", "photo", None),
    ("clip.jpg", "video", None),
    (".jpg", "photo", None),
    ("без расширения", "photo", None),
    ("снимок.jpg ", "photo", None),
    ("имя%2F..%2Fsecret.png", "photo", ".png"),
    ("Сидоров_" + "я" * 240 + ".jpg", "photo", ".jpg"),
]


def test_upload_key_never_contains_file_name(client, world, settings):
    owner_id = world.users[OWNER].id
    keys = set()
    for file_name, file_type, extension in UPLOAD_NAMES:
        upload = presign(client, world.headers(OWNER), file_name, file_type)
        key = upload["file_url"]
        match = UPLOAD_KEY.fullmatch(key)
        assert match, (file_name, key)
        assert int(match.group(1)) == owner_id, "префикс — только свой user_id"
        assert uuid.UUID(match.group(2)).version == 4, "имя объекта — случайный UUID"
        assert match.group(3) == extension, file_name
        assert match.group(3) is None or match.group(3) in ALLOWED_EXTENSIONS
        keys.add(key)

        url = urlsplit(upload["upload_url"])
        assert unquote(url.path).endswith(f"/{key}")
        query = {k: v[0] for k, v in parse_qs(url.query).items()}
        assert query == {
            "X-Fake-Method": "PUT",
            "X-Fake-Expires": str(settings.presign_put_ttl_seconds),
        }
        # Ни одно слово имени не попадает ни в ключ, ни в URL загрузки (UUID исключён).
        rest = unquote(upload["upload_url"]).replace(match.group(2), "").lower()
        for word in re.findall(r"[^\W_]{3,}", file_name):
            if f".{word.lower()}" not in ALLOWED_EXTENSIONS:
                assert word.lower() not in rest, (file_name, word)
    assert len(keys) == len(UPLOAD_NAMES), "каждая загрузка — новый ключ"


PUBLIC_S3 = "https://files.ev-servicedesk.test"
SIGV4_PARAMS = {
    "X-Amz-Algorithm",
    "X-Amz-Credential",
    "X-Amz-Date",
    "X-Amz-Expires",
    "X-Amz-SignedHeaders",
    "X-Amz-Signature",
}


@pytest.fixture
def public_s3(s3_storage: S3ObjectStorage, s3_config: dict[str, str], app: FastAPI):
    """MinIO за публичным адресом: операции — на s3_config["endpoint"], подпись — для PUBLIC_S3."""
    public = S3ObjectStorage(**s3_config, public_endpoint=PUBLIC_S3)
    app.dependency_overrides[get_storage] = lambda: public
    return public


def assert_presigned(
    url: str, path: str | re.Pattern[str], ttl: int, content_type: str | None = None
) -> datetime:
    """Presigned URL SigV4 для публичного адреса S3 на `ttl` секунд; возвращает время подписи.

    content_type — Content-Type ответа GET (response-content-type входит в подпись).
    """
    parts = urlsplit(url)
    assert f"{parts.scheme}://{parts.netloc}" == PUBLIC_S3, url
    if isinstance(path, re.Pattern):
        assert path.fullmatch(unquote(parts.path)), url
    else:
        assert unquote(parts.path) == path, url
    query = {k: v[0] for k, v in parse_qs(parts.query).items()}
    if content_type is not None:
        assert query.pop("response-content-type") == content_type, url
    assert set(query) == SIGV4_PARAMS, url
    assert query["X-Amz-Algorithm"] == "AWS4-HMAC-SHA256"
    assert query["X-Amz-Expires"] == str(ttl)
    assert query["X-Amz-SignedHeaders"] == "host"
    assert query["X-Amz-Credential"].endswith("/s3/aws4_request")
    return datetime.strptime(query["X-Amz-Date"], "%Y%m%dT%H%M%SZ").replace(tzinfo=UTC)


def send(
    url: str, s3_config: dict[str, str], method: str = "GET", host: str | None = None, **kwargs
) -> httpx.Response:
    """Запрос по presigned URL к MinIO теста с заголовком Host публичного адреса.

    Подпись SigV4 включает Host: запрос принимается, только если URL подписан для этого
    адреса. host="" — без подмены (Host внутреннего адреса MinIO).
    """
    parts = urlsplit(url)
    internal = urlsplit(s3_config["endpoint"])
    target = urlunsplit((internal.scheme, internal.netloc, parts.path, parts.query, ""))
    headers = dict(kwargs.pop("headers", {}))
    if host != "":
        headers["Host"] = host or parts.netloc
    return httpx.request(method, target, headers=headers, timeout=10, **kwargs)


def with_query(url: str, **changes: str | None) -> str:
    parts = urlsplit(url)
    query = {k: v[0] for k, v in parse_qs(parts.query).items()} | changes
    query = {k: v for k, v in query.items() if v is not None}
    return urlunsplit(parts._replace(query=urlencode(query)))


def test_presigned_urls_signed_for_public_endpoint_and_expire(
    client, world, public_s3, s3_config, settings, real_redis, monkeypatch
):
    bucket = s3_config["bucket"]
    get_ttl, put_ttl = settings.presign_get_ttl_seconds, settings.presign_put_ttl_seconds
    assert get_ttl == put_ttl == 15 * 60, "ADR 0017 п. 10: 15 минут"
    now = datetime.now(UTC)

    # Загрузка: presigned PUT для публичного адреса; имени файла нет ни в ключе, ни в URL.
    photo = presign(client, world.headers(OWNER), "Паспорт Иванова 7731.PNG")
    signed_at = assert_presigned(photo["upload_url"], f"/{bucket}/{photo['file_url']}", put_ttl)
    assert abs(now - signed_at) < timedelta(minutes=2)
    assert "Иванова" not in unquote(photo["upload_url"]) and "7731" not in photo["upload_url"]
    png = {"content": PNG, "headers": {"Content-Type": "image/png"}}
    r = send(photo["upload_url"], s3_config, "PUT", host="", **png)
    assert r.status_code == 403, "подпись не для внутреннего адреса MinIO"
    r = send(photo["upload_url"], s3_config, "PUT", **png)
    assert r.status_code == 200, r.text

    r = client.post(
        f"{API}/tickets",
        json={
            "vehicle_id": world.vehicles[OWNER],
            "category": "audio",
            "description": "Хрипит динамик",
            "attachments": [{"file_url": photo["file_url"], "file_type": "photo"}],
        },
        headers=world.headers(OWNER),
    )
    assert r.status_code == 201, r.text
    tid = r.json()["id"]
    read_urls = [r.json()["attachments"][0]["file_url"]]
    # Ключ копии — новый uuid в tickets/{tid}/ (уникален для попытки привязки); копия —
    # с проверенным MIME, исходная загрузка удалена.
    photo_path = unquote(urlsplit(read_urls[0]).path)
    assert re.fullmatch(rf"/{bucket}/tickets/{tid}/[0-9a-f-]{{36}}\.png", photo_path), photo_path
    info = public_s3.head(photo_path.removeprefix(f"/{bucket}/"))
    assert info is not None and (info.size, info.content_type) == (len(PNG), "image/png")
    assert public_s3.head(photo["file_url"]) is None, "исходная загрузка удалена"
    r = client.post(f"{API}/tickets/{tid}/claim", headers=world.headers(ENGINEER))
    assert r.status_code == 200, r.text

    # Ответ инженера с видео — клиент получает его и по WebSocket.
    clip = presign(client, world.headers(ENGINEER), "diag.mp4", "video")
    r = send(
        clip["upload_url"], s3_config, "PUT", content=MP4, headers={"Content-Type": "video/mp4"}
    )
    assert r.status_code == 200, r.text
    with connect(client, tid) as ws:
        auth(ws, world.tokens[OWNER])
        r = client.post(
            f"{API}/tickets/{tid}/messages",
            json={
                "body": "Запись диагностики",
                "attachments": [{"file_url": clip["file_url"], "file_type": "video"}],
            },
            headers=world.headers(ENGINEER),
        )
        assert r.status_code == 201, r.text
        clip_urls = [r.json()["attachments"][0]["file_url"]]
        clip_path = unquote(urlsplit(clip_urls[0]).path)
        assert re.fullmatch(rf"/{bucket}/tickets/{tid}/[0-9a-f-]{{36}}\.mp4", clip_path)
        frame = assert_frame(receive_event(ws), "message.created", "TicketMessage")
        clip_urls.append(frame["attachments"][0]["file_url"])

    for actor in (OWNER, ENGINEER, ADMIN):
        r = client.get(f"{API}/tickets/{tid}", headers=world.headers(actor))
        read_urls.append(r.json()["attachments"][0]["file_url"])
        r = client.get(f"{API}/tickets/{tid}/messages", headers=world.headers(actor))
        clip_urls += [a["file_url"] for m in r.json()["items"] for a in m["attachments"]]

    # Фото: ответ createTicket и карточка трём ролям; видео: ответ POST, кадр WebSocket и
    # история трём ролям.
    for urls, path, content, mime, count in (
        (read_urls, photo_path, PNG, "image/png", 4),
        (clip_urls, clip_path, MP4, "video/mp4", 5),
    ):
        assert len(urls) == count
        for url in urls:
            signed_at = assert_presigned(url, path, get_ttl, mime)
            assert abs(now - signed_at) < timedelta(minutes=2)
            got = send(url, s3_config)
            assert got.status_code == 200 and got.content == content, got.text
            assert got.headers["content-type"] == mime

    # Чужая загрузка в MinIO не привязывается: префикс владельца проверяется до HEAD.
    foreign = presign(client, world.headers(ENGINEER))
    r = send(foreign["upload_url"], s3_config, "PUT", **png)
    assert r.status_code == 200, r.text
    r = client.post(
        f"{API}/tickets",
        json={
            "vehicle_id": world.vehicles[OWNER],
            "category": "audio",
            "description": "Чужое фото",
            "attachments": [{"file_url": foreign["file_url"], "file_type": "photo"}],
        },
        headers=world.headers(OWNER),
    )
    assert r.status_code == 422 and error_code(r) == "ATTACHMENT_NOT_FOUND", r.text

    url = read_urls[-1]
    assert send(url, s3_config, host="").status_code == 403, "подпись — для публичного адреса"
    assert send(url, s3_config, "PUT", content=b"x").status_code == 403, "GET не даёт записи"
    longer = with_query(url, **{"X-Amz-Expires": str(7 * 24 * 3600)})
    assert send(longer, s3_config).status_code == 403, "срок входит в подпись"
    html = with_query(url, **{"response-content-type": "text/html"})
    assert send(html, s3_config).status_code == 403, "Content-Type ответа входит в подпись"
    unsigned = urlunsplit(urlsplit(url)._replace(query=""))
    assert send(unsigned, s3_config).status_code == 403, "публичного доступа к объектам нет"

    # Срок действия: URL, подписанный больше 15 минут назад, MinIO уже не принимает.
    # Подпись — локально (без запроса в S3), поэтому часы подписи сдвигаются только на чтение.
    signed_now = botocore.auth.get_current_datetime
    with monkeypatch.context() as m:
        m.setattr(
            botocore.auth,
            "get_current_datetime",
            lambda *a, **kw: signed_now(*a, **kw) - timedelta(seconds=get_ttl + 120),
        )
        r = client.get(f"{API}/tickets/{tid}", headers=world.headers(OWNER))
    stale = r.json()["attachments"][0]["file_url"]
    signed_at = assert_presigned(stale, photo_path, get_ttl, "image/png")
    assert datetime.now(UTC) - signed_at > timedelta(seconds=get_ttl)
    expired = send(stale, s3_config)
    assert expired.status_code == 403 and "expired" in expired.text.lower(), expired.text
