"""Гонки Tickets Service (Глава 13, ADR 0017): одновременные HTTP-запросы на отдельных соединениях.

Прочие API-тесты обращаются к одной сессии под блокировкой — запросы там идут по очереди.
Здесь, как в production, у каждого запроса и каждого обращения WebSocket своя сессия и своё
соединение PostgreSQL: данные фиксируются по-настоящему и удаляются после теста (`purge`).
Токены — настоящие (вход клиента по SMS, персонала — по паролю). Тикеты создаются со
случайным большим id — вторая защита от чужих событий, кроме префикса каналов прогона.

- claim (ADR 0017 п. 5): из 8 инженеров тикет берёт ровно один, остальным — 409;
- первичный ответ (п. 1) фиксируется однократно — первым в чате сообщением персонала;
- одна загрузка — ровно одно вложение (п. 10, «Уточнения»: UNIQUE по имени загрузки);
  вставка — в одном порядке во всех транзакциях (без взаимоблокировок), копии — в ключи,
  уникальные для попытки, а сетевой ввод-вывод S3 не держит блокировку строки тикета;
- создание тикета и удаление авто упорядочены блокировкой авто (п. 6);
- сообщение и решение тикета упорядочены блокировкой строки (п. 8): в решённый — 409;
  временные метки — момент записи под блокировкой, а не начало транзакции запроса;
- нагрузка чата (чек-лист главы 13): 20 одновременных сообщений без потерь — в БД,
  в истории и у двух подписчиков WebSocket.
Тесты гонок проверены мутацией: без атомарного условия или блокировки они падают.
"""

import random
import threading
import time
from collections.abc import Callable, Iterator
from datetime import UTC, datetime, timedelta
from typing import Any, NamedTuple

import anyio
import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from redis import Redis
from sqlalchemy import Engine, delete, or_, select, text
from sqlalchemy.orm import Session, sessionmaker
from starlette.testclient import WebSocketTestSession

from app.api.deps import get_sms_provider
from app.core.config import Settings, get_settings
from app.core.db import get_db, get_session_scope
from app.core.redis import get_pubsub_hub, get_redis
from app.core.storage import ObjectStorage, S3ObjectStorage, get_storage
from app.domain.auth.sms import FakeSmsProvider
from app.domain.tickets import access, attachments, service
from app.domain.vehicles import access as vehicle_access
from app.main import create_app
from app.models import AppUser, PdConsent, Ticket, TicketAttachment, TicketMessage, Vehicle
from app.models.enums import TicketCategory, TicketStatus, UserRole
from tests.api.conftest import API, add_vehicle, assert_contract, bearer, pubsub_hub
from tests.api.test_concurrency import storm
from tests.api.test_ticket_events import assert_frame, auth, connect, receive_event
from tests.conftest import _s3_admin

Headers = dict[str, str]

PREFIX = "+37529713"  # телефоны пользователей модуля: по ним `purge` находит данные теста
VIN = "L6TZ0010000013001"
THREADS = 8
CLAIM_ROUNDS = 5
MESSAGES = 20  # чек-лист главы 13: «20 одновременных сообщений без потерь»
ROUNDS = 20
RESOLVE_STEP_SECONDS = 0.0002  # сдвиг старта решения по раундам: 0…3,8 мс
JPEG = b"\xff\xd8\xff\xe0" + b"0" * 64
ATTACHMENT_REJECTED = {"ATTACHMENT_ALREADY_USED", "ATTACHMENT_NOT_FOUND"}  # ADR 0017, «Уточнения»


def phone(n: int) -> str:
    return f"{PREFIX}{n:04d}"


def error_code(response: httpx.Response) -> str:
    return response.json()["error"]["code"]


# ---------- Приложение с сессией на запрос и очистка ----------


@pytest.fixture
def db(migrated_engine: Engine) -> Iterator[Session]:
    """Сессия подготовки (make_staff, тикеты): commit настоящий — данные видят все соединения."""
    with Session(migrated_engine, expire_on_commit=False) as session:
        yield session


@pytest.fixture
def app(
    settings: Settings,
    migrated_engine: Engine,
    real_redis: Redis,
    sms: FakeSmsProvider,
    storage: ObjectStorage,
) -> FastAPI:
    """Как `app.core.db`: сессия на запрос и на каждое обращение WebSocket к БД."""
    application = create_app(settings)
    sessions = sessionmaker(bind=migrated_engine, expire_on_commit=False)

    def session_per_request() -> Iterator[Session]:
        with sessions() as session:
            yield session

    overrides = application.dependency_overrides
    overrides[get_settings] = lambda: settings
    overrides[get_db] = session_per_request
    overrides[get_session_scope] = lambda: sessions
    overrides[get_redis] = lambda: real_redis
    hub = pubsub_hub(settings)
    overrides[get_pubsub_hub] = lambda: hub
    overrides[get_sms_provider] = lambda: sms
    overrides[get_storage] = lambda: storage
    return application


def purge(engine: Engine) -> None:
    """Удаляет данные теста: пользователей с PREFIX, их авто, тикеты, сообщения и вложения.

    Согласие на обработку ПД неудаляемо (trg_pd_consent_guard, глава 2) — охрана снимается
    только внутри транзакции очистки: DDL в PostgreSQL транзакционен, а ALTER TABLE держит
    блокировку таблицы до commit, так что другие соединения таблицу без охраны не видят.
    """
    users = select(AppUser.id).where(AppUser.phone.startswith(PREFIX))
    vehicles = select(Vehicle.id).where(Vehicle.user_id.in_(users))
    tickets = select(Ticket.id).where(
        or_(Ticket.vehicle_id.in_(vehicles), Ticket.assigned_engineer_id.in_(users))
    )
    with engine.begin() as conn:
        conn.execute(delete(TicketAttachment).where(TicketAttachment.ticket_id.in_(tickets)))
        conn.execute(delete(TicketMessage).where(TicketMessage.ticket_id.in_(tickets)))
        conn.execute(delete(Ticket).where(Ticket.id.in_(tickets)))
        conn.execute(delete(Vehicle).where(Vehicle.id.in_(vehicles)))
        conn.execute(text("ALTER TABLE pd_consent DISABLE TRIGGER trg_pd_consent_guard"))
        conn.execute(delete(PdConsent).where(PdConsent.user_id.in_(users)))
        conn.execute(text("ALTER TABLE pd_consent ENABLE TRIGGER trg_pd_consent_guard"))
        conn.execute(delete(AppUser).where(AppUser.id.in_(users)))  # refresh_token — CASCADE


@pytest.fixture(autouse=True)
def _purge(migrated_engine: Engine) -> Iterator[None]:
    """autouse — создаётся первой и разбирается последней: после закрытия сессий теста."""
    yield
    purge(migrated_engine)


class Owner(NamedTuple):
    headers: Headers
    token: str
    vehicle_id: int


@pytest.fixture
def owner(client: TestClient, login_client: Callable[[str], dict]) -> Owner:
    """Клиент (вход по SMS) со своим авто."""
    access_token = login_client(phone(1))["access_token"]
    headers = bearer(access_token)
    return Owner(headers, access_token, add_vehicle(client, headers, vin=VIN)["id"])


@pytest.fixture
def http(app: FastAPI) -> Iterator[TestClient]:
    """Клиент для одновременных запросов: цикл событий (портал) запущен заранее, как у одного
    процесса uvicorn, — после барьера запросы сразу попадают в приложение, а синхронные
    обработчики идут параллельно в пуле потоков, каждый со своей сессией.
    """
    with TestClient(app) as running:
        yield running


@pytest.fixture
def minio(app: FastAPI, s3_storage: S3ObjectStorage) -> S3ObjectStorage:
    """Вложения — на настоящем S3 API (MinIO): HEAD, копирование и удаление в гонке."""
    app.dependency_overrides[get_storage] = lambda: s3_storage
    return s3_storage


def open_ticket(db: Session, vehicle_id: int, engineer: AppUser | None = None) -> int:
    """Тикет в очереди (`new`) или у `engineer` (`in_progress`) со случайным id (см. модуль)."""
    ticket = Ticket(
        id=random.randrange(10**12, 10**13),
        vehicle_id=vehicle_id,
        category=TicketCategory.APP_CRASH,
        status=TicketStatus.IN_PROGRESS if engineer else TicketStatus.NEW,
        description="Приложение закрывается при запуске",
        assigned_engineer_id=engineer.id if engineer else None,
        sla_due_at=datetime.now(UTC) + timedelta(hours=4),
    )
    db.add(ticket)
    db.commit()
    return ticket.id


def fetch_ticket(engine: Engine, ticket_id: int) -> Ticket:
    with Session(engine) as check:
        return check.get_one(Ticket, ticket_id)


def fetch_messages(engine: Engine, ticket_id: int) -> list[TicketMessage]:
    with Session(engine) as check:
        return list(
            check.scalars(
                select(TicketMessage)
                .where(TicketMessage.ticket_id == ticket_id)
                .order_by(TicketMessage.id)
            )
        )


def post_message(
    http: TestClient,
    ticket_id: int,
    headers: Headers,
    body: str,
    attachments: list[dict] | None = None,
) -> httpx.Response:
    return http.post(
        f"{API}/tickets/{ticket_id}/messages",
        json={"body": body, "attachments": attachments or []},
        headers=headers,
    )


def change_status(
    http: TestClient, ticket_id: int, headers: Headers, status: str
) -> httpx.Response:
    return http.patch(f"{API}/tickets/{ticket_id}/status", json={"status": status}, headers=headers)


def responses(results: list[object]) -> list[Any]:
    """Результаты `storm` без исключений (исключение — сбой запроса, показываем его)."""
    assert not [r for r in results if isinstance(r, BaseException)], results
    return results


# ---------- Claim (ADR 0017 п. 5) ----------


def test_parallel_claims_have_one_winner(
    http: TestClient, db: Session, owner: Owner, as_staff, migrated_engine: Engine
):
    """8 инженеров одновременно берут тикет из очереди; раунды — на новых тикетах."""
    engineers = [as_staff(phone(100 + i)) for i in range(THREADS)]
    for _ in range(CLAIM_ROUNDS):
        ticket_id = open_ticket(db, owner.vehicle_id)
        crowd = iter(engineers)

        def claim() -> tuple[AppUser, httpx.Response]:
            headers, engineer = next(crowd)
            return engineer, http.post(f"{API}/tickets/{ticket_id}/claim", headers=headers)

        results = responses(storm(THREADS, claim))
        for _, r in results:
            assert_contract(r, "claimTicket")
        won = [(engineer, r) for engineer, r in results if r.status_code == 200]
        lost = [r for _, r in results if r.status_code != 200]
        assert len(won) == 1, [r.status_code for _, r in results]
        expected = [(409, "TICKET_ALREADY_CLAIMED")] * (THREADS - 1)
        assert [(r.status_code, error_code(r)) for r in lost] == expected

        [(winner, response)] = won
        assert (response.json()["assigned_engineer_id"], response.json()["status"]) == (
            winner.id,
            "in_progress",
        )
        ticket = fetch_ticket(migrated_engine, ticket_id)
        assert (ticket.assigned_engineer_id, ticket.status) == (
            winner.id,
            TicketStatus.IN_PROGRESS,
        )


# ---------- Первичный ответ (ADR 0017 п. 1) ----------


def test_parallel_first_staff_replies_set_first_response_once(
    http: TestClient, db: Session, owner: Owner, as_staff, migrated_engine: Engine
):
    """Инженер и админ отвечают одновременно: первичный ответ — первое в чате (по id) сообщение
    персонала, и позже он не перезаписывается. created_at и first_response_at — момент записи
    под блокировкой тикета, поэтому первое по id — и самое раннее.
    """
    eng_headers, engineer = as_staff(phone(201))
    admin_headers, admin = as_staff(phone(202), UserRole.ADMIN)
    ticket_id = open_ticket(db, owner.vehicle_id, engineer)
    assert post_message(http, ticket_id, owner.headers, "Есть новости?").status_code == 201
    assert fetch_ticket(migrated_engine, ticket_id).first_response_at is None, "клиент — не ответ"

    staff = iter([eng_headers, admin_headers])
    results = responses(storm(2, lambda: post_message(http, ticket_id, next(staff), "Смотрим")))
    assert [r.status_code for r in results] == [201, 201], [r.text for r in results]

    staff_ids = (engineer.id, admin.id)
    replies = [m for m in fetch_messages(migrated_engine, ticket_id) if m.author_id in staff_ids]
    assert {m.author_id for m in replies} == {engineer.id, admin.id}
    first = replies[0]  # порядок чата — по id (ADR 0017 п. 8)
    assert first.created_at == min(m.created_at for m in replies)
    assert fetch_ticket(migrated_engine, ticket_id).first_response_at == first.created_at

    # Последующие ответы персонала первичный ответ не перезаписывают.
    assert post_message(http, ticket_id, admin_headers, "Обновите прошивку").status_code == 201
    assert fetch_ticket(migrated_engine, ticket_id).first_response_at == first.created_at


# ---------- Одна загрузка — одно вложение (ADR 0017 п. 10, «Уточнения») ----------


def upload(client: TestClient, headers: Headers) -> str:
    """Фото, загруженное клиентом в MinIO по presigned PUT; возвращает file_url."""
    r = client.post(
        f"{API}/uploads/presign",
        json={"file_name": "panel.jpg", "file_type": "photo"},
        headers=headers,
    )
    assert r.status_code == 200, r.text
    target = r.json()
    put = httpx.put(target["upload_url"], content=JPEG, headers={"Content-Type": "image/jpeg"})
    assert put.status_code == 200, put.text
    return target["file_url"]


def bucket_keys(s3_config: dict[str, str]) -> list[str]:
    """Все ключи тестового бакета (`s3_storage` очищает его перед тестом)."""
    client = _s3_admin(s3_config)
    try:
        pages = client.get_paginator("list_objects_v2").paginate(Bucket=s3_config["bucket"])
        return sorted(obj["Key"] for page in pages for obj in page.get("Contents", []))
    finally:
        client.close()


def attachment_rows(engine: Engine, *names: str) -> list[TicketAttachment]:
    with Session(engine) as check:
        return list(
            check.scalars(
                select(TicketAttachment)
                .where(TicketAttachment.upload_name.in_(names))
                .order_by(TicketAttachment.id)
            )
        )


def test_same_upload_binds_once_under_parallel_requests(
    http: TestClient,
    client: TestClient,
    db: Session,
    owner: Owner,
    minio: S3ObjectStorage,
    s3_config: dict[str, str],
    migrated_engine: Engine,
):
    """Загрузка в 6 одновременных запросах: 3 сообщения в разные тикеты и 3 новых тикета."""
    tickets = [open_ticket(db, owner.vehicle_id) for _ in range(3)]
    file_url = upload(client, owner.headers)
    name = file_url.rsplit("/", 1)[1]
    attachments = [{"file_url": file_url, "file_type": "photo"}]
    new_ticket = {
        "vehicle_id": owner.vehicle_id,
        "category": "app_crash",
        "description": "Фото панели",
        "attachments": attachments,
    }
    message = {"body": "Фото панели", "attachments": attachments}
    jobs = iter(
        [
            *[("createTicketMessage", f"{API}/tickets/{tid}/messages", message) for tid in tickets],
            *[("createTicket", f"{API}/tickets", new_ticket)] * 3,
        ]
    )

    def bind() -> tuple[str, httpx.Response]:
        operation, path, body = next(jobs)
        return operation, http.post(path, json=body, headers=owner.headers)

    results = responses(storm(6, bind))
    for operation, r in results:
        assert_contract(r, operation)
    assert sorted(r.status_code for _, r in results) == [201] + [422] * 5, [
        r.text for _, r in results
    ]
    assert {error_code(r) for _, r in results if r.status_code == 422} <= ATTACHMENT_REJECTED

    [row] = attachment_rows(migrated_engine, name)
    assert bucket_keys(s3_config) == [row.object_key], "одна копия, исходник удалён, сирот нет"


@pytest.mark.parametrize("first_commits", [True, False], ids=["commit", "rollback"])
def test_second_binding_of_upload_waits_for_first(
    http: TestClient,
    client: TestClient,
    db: Session,
    owner: Owner,
    minio: S3ObjectStorage,
    s3_config: dict[str, str],
    migrated_engine: Engine,
    monkeypatch: pytest.MonkeyPatch,
    first_commits: bool,
):
    """Первая привязка записала строку вложения и не завершена — вторая ждёт её исхода.

    UNIQUE по имени загрузки: после commit первой вторая получает 422
    ATTACHMENT_ALREADY_USED и удаляет свою копию; после отката первой — привязывает сама.
    """
    first_ticket = open_ticket(db, owner.vehicle_id)
    second_ticket = open_ticket(db, owner.vehicle_id)
    file_url = upload(client, owner.headers)
    name = file_url.rsplit("/", 1)[1]
    attachments_in = [{"file_url": file_url, "file_type": "photo"}]

    inserted, release = threading.Event(), threading.Event()
    original = attachments.add_rows

    def paused_add_rows(*args: Any, **kwargs: Any) -> None:
        original(*args, **kwargs)
        if not inserted.is_set():
            inserted.set()
            release.wait(5)
            if not first_commits:
                raise access.ticket_resolved()  # отказ после вставки: откат транзакции

    monkeypatch.setattr(attachments, "add_rows", paused_add_rows)
    outcome: dict[int, httpx.Response] = {}

    def send(ticket_id: int) -> None:
        outcome[ticket_id] = post_message(http, ticket_id, owner.headers, "Фото", attachments_in)

    first = threading.Thread(target=send, args=(first_ticket,))
    second = threading.Thread(target=send, args=(second_ticket,))
    first.start()
    try:
        assert inserted.wait(5), "первая привязка не дошла до записи вложения"
        second.start()
        second.join(0.5)
        assert second.is_alive(), "вторая привязка той же загрузки не ждёт исхода первой"
    finally:
        release.set()
        first.join(5)
        if second.ident is not None:
            second.join(5)

    winner, loser = (
        (first_ticket, second_ticket) if first_commits else (second_ticket, first_ticket)
    )
    assert outcome[winner].status_code == 201, outcome[winner].text
    rejected = outcome[loser]
    assert_contract(rejected, "createTicketMessage")
    expected = "ATTACHMENT_ALREADY_USED" if first_commits else "TICKET_RESOLVED"
    assert (rejected.status_code, error_code(rejected)) == (422 if first_commits else 409, expected)
    [row] = attachment_rows(migrated_engine, name)
    assert row.ticket_id == winner
    assert bucket_keys(s3_config) == [row.object_key], "копия проигравшего удалена"


def test_reversed_attachment_lists_do_not_deadlock(
    http: TestClient,
    client: TestClient,
    db: Session,
    owner: Owner,
    minio: S3ObjectStorage,
    s3_config: dict[str, str],
    migrated_engine: Engine,
    monkeypatch: pytest.MonkeyPatch,
):
    """[x, y] и [y, x] одновременно: вставка — в порядке имён, без взаимоблокировки (500).

    Барьер перед записью вложений: оба запроса вставляют одновременно. В порядке запроса
    каждый занял бы первое имя и ждал бы второе — PostgreSQL прервал бы один из них.
    """
    tickets = [open_ticket(db, owner.vehicle_id) for _ in range(2)]
    x, y = upload(client, owner.headers), upload(client, owner.headers)
    barrier = threading.Barrier(2, timeout=5)
    original = attachments.add_rows

    def together(*args: Any, **kwargs: Any) -> None:
        barrier.wait()
        original(*args, **kwargs)

    monkeypatch.setattr(attachments, "add_rows", together)
    jobs = iter(zip(tickets, ([x, y], [y, x]), strict=True))

    def send() -> httpx.Response:
        ticket_id, urls = next(jobs)
        items = [{"file_url": url, "file_type": "photo"} for url in urls]
        return post_message(http, ticket_id, owner.headers, "Фото", items)

    results = responses(storm(2, send))
    for r in results:
        assert_contract(r, "createTicketMessage")
    assert sorted(r.status_code for r in results) == [201, 422], [r.text for r in results]
    [won] = [r for r in results if r.status_code == 201]
    [lost] = [r for r in results if r.status_code == 422]
    assert error_code(lost) == "ATTACHMENT_ALREADY_USED"
    rows = attachment_rows(migrated_engine, *(url.rsplit("/", 1)[1] for url in (x, y)))
    assert {row.ticket_message_id for row in rows} == {won.json()["id"]} and len(rows) == 2
    assert bucket_keys(s3_config) == sorted(row.object_key for row in rows)


def test_storage_io_does_not_hold_ticket_lock(
    http: TestClient,
    client: TestClient,
    db: Session,
    owner: Owner,
    as_staff,
    minio: S3ObjectStorage,
    monkeypatch: pytest.MonkeyPatch,
):
    """Копирование в S3 остановлено — смена статуса того же тикета не ждёт его.

    Медленный S3 (таймауты, повторы, 10 вложений) не блокирует строку тикета: claim, смену
    статуса и другие сообщения.
    """
    eng_headers, engineer = as_staff(phone(431))
    ticket_id = open_ticket(db, owner.vehicle_id, engineer)
    file_url = upload(client, owner.headers)

    copying, release = threading.Event(), threading.Event()
    original_copy = minio.copy

    def paused_copy(*args: Any, **kwargs: Any) -> None:
        copying.set()
        release.wait(5)
        original_copy(*args, **kwargs)

    monkeypatch.setattr(minio, "copy", paused_copy)
    outcome: dict[str, httpx.Response] = {}

    def write() -> None:
        items = [{"file_url": file_url, "file_type": "photo"}]
        outcome["message"] = post_message(http, ticket_id, owner.headers, "Фото", items)

    writer = threading.Thread(target=write)
    writer.start()
    try:
        assert copying.wait(5), "сообщение не дошло до копирования"
        r = change_status(http, ticket_id, eng_headers, "waiting_vendor")
        assert writer.is_alive(), "копирование уже завершилось — проверка без смысла"
    finally:
        release.set()
        writer.join(5)
    assert r.status_code == 200, r.text
    assert outcome["message"].status_code == 201, outcome["message"].text


# ---------- Создание тикета и удаление авто (ADR 0017 п. 6) ----------


def create_ticket(http: TestClient, owner: Owner) -> httpx.Response:
    return http.post(
        f"{API}/tickets",
        json={"vehicle_id": owner.vehicle_id, "category": "audio", "description": "Хрипит"},
        headers=owner.headers,
    )


def test_vehicle_deleted_before_ticket_write_is_404(
    http: TestClient, owner: Owner, migrated_engine: Engine, monkeypatch: pytest.MonkeyPatch
):
    """Авто удалено, пока создание работало с S3 (до записи) — 404, тикета нет."""
    copying, release = threading.Event(), threading.Event()
    original = attachments.copy_uploads

    def paused_copy_uploads(*args: Any, **kwargs: Any) -> list[str]:
        copying.set()
        release.wait(5)
        return original(*args, **kwargs)

    monkeypatch.setattr(attachments, "copy_uploads", paused_copy_uploads)
    outcome: dict[str, httpx.Response] = {}
    creator = threading.Thread(target=lambda: outcome.update(create=create_ticket(http, owner)))
    creator.start()
    try:
        assert copying.wait(5), "создание не дошло до копирования вложений"
        r = http.delete(f"{API}/vehicles/{owner.vehicle_id}", headers=owner.headers)
        assert r.status_code == 204, r.text
    finally:
        release.set()
        creator.join(5)
    created = outcome["create"]
    assert_contract(created, "createTicket")
    assert (created.status_code, error_code(created)) == (404, "NOT_FOUND")
    with Session(migrated_engine) as check:
        assert (
            check.scalars(select(Ticket).where(Ticket.vehicle_id == owner.vehicle_id)).all() == []
        )


def test_vehicle_delete_waits_for_ticket_write(
    http: TestClient, owner: Owner, migrated_engine: Engine, monkeypatch: pytest.MonkeyPatch
):
    """Создание держит авто (FOR SHARE) до commit — удаление ждёт и выполняется после.

    Тикет создан на активном авто; после удаления он, как и прочие тикеты удалённого авто,
    клиенту не виден.
    """
    writing, release = threading.Event(), threading.Event()
    original = vehicle_access.for_new_ticket

    def paused_for_new_ticket(*args: Any) -> Vehicle:
        vehicle = original(*args)  # авто проверено, тикет ещё не записан
        writing.set()
        release.wait(5)
        return vehicle

    monkeypatch.setattr(vehicle_access, "for_new_ticket", paused_for_new_ticket)
    outcome: dict[str, httpx.Response] = {}

    def remove() -> None:
        outcome["delete"] = http.delete(f"{API}/vehicles/{owner.vehicle_id}", headers=owner.headers)

    creator = threading.Thread(target=lambda: outcome.update(create=create_ticket(http, owner)))
    remover = threading.Thread(target=remove)
    creator.start()
    try:
        assert writing.wait(5), "создание не дошло до записи"
        remover.start()
        remover.join(0.5)
        assert remover.is_alive(), "удаление авто не ждёт создания тикета"
    finally:
        release.set()
        creator.join(5)
        if remover.ident is not None:
            remover.join(5)
    assert outcome["create"].status_code == 201, outcome["create"].text
    assert outcome["delete"].status_code == 204, outcome["delete"].text
    ticket = fetch_ticket(migrated_engine, outcome["create"].json()["id"])
    with Session(migrated_engine) as check:
        vehicle = check.get_one(Vehicle, owner.vehicle_id)
        assert vehicle.deleted_at is not None and ticket.created_at < vehicle.deleted_at


# ---------- Сообщение и решение тикета (ADR 0017 п. 4, 8) ----------


def test_message_and_resolve_race(
    http: TestClient, db: Session, owner: Owner, as_staff, migrated_engine: Engine
):
    """Раунды «сообщение клиента ↔ решение инженером»: сообщение либо до решения, либо 409.

    При одновременном старте решение всегда берёт блокировку первым (у сообщения перед ней
    ещё лимит в Redis), поэтому старт решения сдвигается по раундам: в окрестности момента,
    когда запросы приходят к блокировке одновременно, встречаются обе ветки гонки.
    """
    eng_headers, engineer = as_staff(phone(401))
    ticket_id = open_ticket(db, owner.vehicle_id, engineer)
    outcomes: list[int] = []
    for n in range(ROUNDS):
        body = f"Вопрос {n}"

        def resolve(delay: float = RESOLVE_STEP_SECONDS * n) -> httpx.Response:
            time.sleep(delay)
            return change_status(http, ticket_id, eng_headers, "resolved")

        jobs = iter(
            [
                ("message", lambda: post_message(http, ticket_id, owner.headers, body)),
                ("resolve", resolve),
            ]
        )

        def run() -> tuple[str, httpx.Response]:
            kind, call = next(jobs)
            return kind, call()

        outcome = dict(responses(storm(2, run)))
        assert outcome["resolve"].status_code == 200, outcome["resolve"].text
        message = outcome["message"]
        assert_contract(message, "createTicketMessage")
        outcomes.append(message.status_code)
        stored = [m for m in fetch_messages(migrated_engine, ticket_id) if m.body == body]
        if message.status_code == 201:
            assert [m.id for m in stored] == [message.json()["id"]]
        else:
            assert (message.status_code, error_code(message)) == (409, "TICKET_RESOLVED")
            assert stored == [], "отклонённое сообщение не записано"
        assert fetch_ticket(migrated_engine, ticket_id).status is TicketStatus.RESOLVED
        assert change_status(http, ticket_id, eng_headers, "in_progress").status_code == 200

    assert len(fetch_messages(migrated_engine, ticket_id)) == outcomes.count(201), outcomes


def test_message_waits_for_resolve_holding_ticket_lock(
    http: TestClient,
    db: Session,
    owner: Owner,
    as_staff,
    migrated_engine: Engine,
    monkeypatch: pytest.MonkeyPatch,
):
    """Решение держит строку тикета (FOR UPDATE) — сообщение ждёт commit и получает 409."""
    eng_headers, engineer = as_staff(phone(411))
    ticket_id = open_ticket(db, owner.vehicle_id, engineer)

    locked, release = threading.Event(), threading.Event()
    original = service.transition

    def paused_transition(*args: Any) -> Any:
        change = original(*args)
        locked.set()
        release.wait(5)
        return change

    monkeypatch.setattr(service, "transition", paused_transition)
    outcome: dict[str, httpx.Response] = {}

    def resolve() -> None:
        outcome["resolve"] = change_status(http, ticket_id, eng_headers, "resolved")

    def write() -> None:
        outcome["message"] = post_message(http, ticket_id, owner.headers, "Ещё вопрос")

    resolver = threading.Thread(target=resolve)
    writer = threading.Thread(target=write)
    resolver.start()
    try:
        assert locked.wait(5), "решение не дошло до смены статуса"
        writer.start()
        writer.join(0.5)
        assert writer.is_alive(), "сообщение не ждёт блокировку тикета, захваченную решением"
    finally:
        release.set()
        resolver.join(5)
        if writer.ident is not None:
            writer.join(5)

    assert outcome["resolve"].status_code == 200
    message = outcome["message"]
    assert (message.status_code, error_code(message)) == (409, "TICKET_RESOLVED")
    assert fetch_messages(migrated_engine, ticket_id) == []


class MisdatedError(AssertionError):
    """Временные метки противоречат порядку записи под блокировкой."""


def test_message_accepted_before_resolve_is_not_dated_after_it(
    http: TestClient,
    db: Session,
    owner: Owner,
    as_staff,
    migrated_engine: Engine,
    monkeypatch: pytest.MonkeyPatch,
):
    """Сообщение принято до решения — значит, created_at не позже resolved_at.

    Транзакция запроса начинается с чтения пользователя токена (`get_current_user`), а
    `now()` в PostgreSQL — время начала транзакции. Решение, начатое раньше, но получившее
    блокировку тикета позже сообщения (задержка между входом и блокировкой: пул потоков,
    планировщик), ставит resolved_at раньше created_at уже принятого сообщения.
    """
    eng_headers, engineer = as_staff(phone(421))
    ticket_id = open_ticket(db, owner.vehicle_id, engineer)

    started, release = threading.Event(), threading.Event()
    original = access.for_update

    def delayed_for_update(session: Session, user: AppUser, tid: int) -> Ticket:
        if user.role is UserRole.ENGINEER and not started.is_set():
            started.set()  # транзакция решения уже начата: пользователь токена прочитан
            release.wait(5)
        return original(session, user, tid)

    monkeypatch.setattr(access, "for_update", delayed_for_update)
    outcome: dict[str, httpx.Response] = {}

    def resolve() -> None:
        outcome["resolve"] = change_status(http, ticket_id, eng_headers, "resolved")

    resolver = threading.Thread(target=resolve)
    resolver.start()
    try:
        assert started.wait(5), "решение не дошло до блокировки тикета"
        message = post_message(http, ticket_id, owner.headers, "Успел до решения")
    finally:
        release.set()
        resolver.join(5)

    assert message.status_code == 201, message.text
    assert outcome["resolve"].status_code == 200
    [stored] = fetch_messages(migrated_engine, ticket_id)
    resolved_at = fetch_ticket(migrated_engine, ticket_id).resolved_at
    if stored.created_at > resolved_at:
        raise MisdatedError(f"created_at {stored.created_at} > resolved_at {resolved_at}")


# ---------- Нагрузка чата (чек-лист главы 13) ----------


def assert_quiet(ws: WebSocketTestSession, seconds: float = 0.3) -> None:
    """За `seconds` подписчику больше ничего не пришло (нет дублей и лишних событий)."""

    async def _poll() -> dict[str, Any] | None:
        with anyio.move_on_after(seconds):
            return await ws._send_rx.receive()
        return None

    assert ws.portal.call(_poll) is None, "лишний кадр после всех сообщений"


def test_chat_load_parallel_messages_without_loss(
    http: TestClient,
    client: TestClient,
    db: Session,
    owner: Owner,
    as_staff,
    migrated_engine: Engine,
):
    """20 одновременных сообщений (клиент и инженер по 10): все в БД, в истории и у подписчиков."""
    eng_headers, engineer = as_staff(phone(501))
    ticket_id = open_ticket(db, owner.vehicle_id, engineer)
    eng_token = eng_headers["Authorization"].removeprefix("Bearer ")

    with connect(client, ticket_id) as client_ws, connect(client, ticket_id) as eng_ws:
        auth(client_ws, owner.token)  # `ready` — подписка подтверждена, события не теряются
        auth(eng_ws, eng_token)

        jobs = iter([(n, eng_headers if n % 2 else owner.headers) for n in range(MESSAGES)])

        def send() -> httpx.Response:
            n, headers = next(jobs)
            return post_message(http, ticket_id, headers, f"Сообщение {n}")

        results = responses(storm(MESSAGES, send))
        assert [r.status_code for r in results] == [201] * MESSAGES, [r.text for r in results]
        sent = {r.json()["id"]: r.json()["body"] for r in results}
        assert len(sent) == MESSAGES and set(sent.values()) == {
            f"Сообщение {n}" for n in range(MESSAGES)
        }

        for ws in (client_ws, eng_ws):
            frames = [
                assert_frame(receive_event(ws), "message.created", "TicketMessage")
                for _ in range(MESSAGES)
            ]
            assert sorted(f["id"] for f in frames) == sorted(sent), "каждое сообщение — один раз"
            assert {f["id"]: f["body"] for f in frames} == sent
            assert_quiet(ws)

    r = client.get(
        f"{API}/tickets/{ticket_id}/messages", params={"page_size": 100}, headers=owner.headers
    )
    assert r.status_code == 200
    assert_contract(r, "listTicketMessages")
    history = r.json()
    assert history["meta"]["total_items"] == MESSAGES
    assert [m["id"] for m in history["items"]] == sorted(sent), "история — по id по возрастанию"
    stored = fetch_messages(migrated_engine, ticket_id)
    assert [m.id for m in stored] == sorted(sent)
    # created_at — момент записи под блокировкой тикета: растёт вместе с id.
    times = [m.created_at for m in stored]
    assert times == sorted(times), "created_at не монотонен по id"
