"""Анонимизация ПД после отзыва согласия и сроки хранения (Глава 25, ADR 0029 пп. 18–19).

Путь клиента целиком: вход, авто, тикет с сообщением и вложением, push-токен, уведомление →
отзыв согласия → проход worker'а: SMS «данные удалены» до обнуления телефона, затем ПД удалены
везде, обезличенная история и доказательство согласия сохранены, номер снова свободен.
"""

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta

import pytest
from prometheus_client import REGISTRY
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core import rate_limit
from app.domain.auth.sms import FakeSmsProvider, SmsError
from app.domain.users import privacy
from app.models import (
    AppUser,
    Notification,
    NotificationDelivery,
    NotificationRecipient,
    PdConsent,
    PushToken,
    RefreshToken,
    Ticket,
    TicketAttachment,
    TicketMessage,
    Vehicle,
)
from app.models.enums import AttachmentType, NotificationType, TicketStatus
from app.workers.privacy import SMS_TEXT, PrivacyWorker
from tests.api.conftest import API, ZEEKR_VIN, add_vehicle, bearer, register
from tests.api.ticket_support import create

PHONE = "+375296700001"
OBJECT_KEY = "tickets/{tid}/0a1b2c3d.jpg"


@pytest.fixture
def worker_for(settings, db: Session, real_redis, storage):
    @contextmanager
    def scope() -> Iterator[Session]:
        yield db

    def _make(sms=None, now=None) -> PrivacyWorker:
        kwargs = {"now": now} if now else {}
        return PrivacyWorker(
            settings, scope, real_redis, sms or FakeSmsProvider(), storage, **kwargs
        )

    return _make


def count(db: Session, model, *where) -> int:
    return db.scalar(select(func.count()).select_from(model).where(*where))


@pytest.fixture
def client_with_data(client, login_client, db: Session, storage):
    """Клиент с ПД во всех местах; возвращает (user_id, ticket_id, сессия)."""
    session = login_client(PHONE)
    headers = bearer(session["access_token"])
    vehicle = add_vehicle(client, headers, ZEEKR_VIN)
    ticket = create(
        client, headers, vehicle["id"], category="sim", description="Не ловит сеть дома"
    )
    user_id = session["user"]["id"]
    db.add(TicketMessage(ticket_id=ticket["id"], author_id=user_id, body="Мой адрес: Советская 15"))
    key = OBJECT_KEY.format(tid=ticket["id"])
    storage.put(key, b"jpeg", "image/jpeg")
    db.add(
        TicketAttachment(
            ticket_id=ticket["id"],
            object_key=key,
            upload_name="0a1b2c3d.jpg",
            file_type=AttachmentType.PHOTO,
            mime_type="image/jpeg",
            size_bytes=4,
            uploaded_by_user_id=user_id,
        )
    )
    register(client, headers, "fcm-anon-token:" + "q" * 40)
    note = Notification(type=NotificationType.NEWS, message="Новости сервиса")
    db.add(note)
    db.flush()
    db.add(NotificationRecipient(notification_id=note.id, user_id=user_id))
    db.commit()
    assert client.delete(f"{API}/auth/pd-consent", headers=headers).status_code == 202
    return user_id, ticket["id"], session


def test_anonymization_removes_personal_data_everywhere(
    client, client_with_data, worker_for, db: Session, storage, login_client, real_redis
):
    user_id, ticket_id, _ = client_with_data
    sms = FakeSmsProvider()
    worker = worker_for(sms)
    worker.anonymize_due()
    assert sms.last_text(PHONE) == SMS_TEXT, "уведомление — до обнуления телефона"

    db.expire_all()
    user = db.get(AppUser, user_id)
    assert (user.phone, user.telegram_id) == (None, None) and user.anonymized_at is not None
    vehicle = db.scalars(select(Vehicle).where(Vehicle.user_id == user_id)).one()
    assert vehicle.vin == privacy.ANONYMIZED_VIN and vehicle.deleted_at is not None
    ticket = db.get(Ticket, ticket_id)
    assert ticket.description == privacy.REDACTED and ticket.status is TicketStatus.RESOLVED
    bodies = db.scalars(select(TicketMessage.body).where(TicketMessage.ticket_id == ticket_id))
    assert set(bodies) == {privacy.REDACTED}
    assert count(db, TicketAttachment, TicketAttachment.ticket_id == ticket_id) == 0
    assert OBJECT_KEY.format(tid=ticket_id) not in storage.objects, "объект S3 удалён"
    for model in (PushToken, NotificationRecipient, RefreshToken):
        assert count(db, model, model.user_id == user_id) == 0, model.__name__
    assert count(db, PdConsent, PdConsent.user_id == user_id) == 1, "доказательство согласия"

    # Повторный проход — клиента нет в очереди, SMS не повторяется.
    sms.outbox.clear()
    worker.anonymize_due()
    assert sms.last_text(PHONE) is None
    assert user_id not in {item.user_id for item in privacy.due(db)}
    # Номер свободен: прежний владелец регистрируется заново — новый пользователь без истории.
    rate_limit.reset(real_redis, f"sms-cooldown:{PHONE}")
    again = login_client(PHONE)
    assert again["is_new_user"] and again["user"]["id"] != user_id
    r = client.get(f"{API}/vehicles", headers=bearer(again["access_token"]))
    assert r.json()["items"] == []


def test_consent_given_again_cancels_anonymization(
    client_with_data, worker_for, login_client, db, real_redis
):
    user_id, _, _ = client_with_data
    rate_limit.reset(real_redis, f"sms-cooldown:{PHONE}")
    login_client(PHONE)  # вход с согласием новой редакции — согласие снова действует
    worker_for().anonymize_due()
    db.expire_all()
    assert db.get(AppUser, user_id).phone == PHONE


class _DownSms:
    sent_count = 0

    def send(self, phone: str, text: str) -> None:
        raise SmsError("down")


def test_sms_failure_postpones_until_deadline_nears(client_with_data, worker_for, db):
    user_id, _, _ = client_with_data
    worker_for(_DownSms()).anonymize_due()
    db.expire_all()
    assert db.get(AppUser, user_id).phone == PHONE, "SMS не дошло — ждём следующего прохода"
    late = lambda: datetime.now(UTC) + privacy.LATE  # noqa: E731
    worker_for(_DownSms(), now=late).anonymize_due()
    db.expire_all()
    assert db.get(AppUser, user_id).anonymized_at is not None, "срок важнее уведомления"


def test_storage_failure_rolls_back_and_retries(client_with_data, worker_for, db, storage):
    user_id, ticket_id, _ = client_with_data
    storage.available = False
    with pytest.raises(Exception):
        worker_for().anonymize_due()
    db.rollback()
    db.expire_all()
    assert db.get(AppUser, user_id).phone == PHONE, "ничего не удалено частично"
    assert count(db, TicketAttachment, TicketAttachment.ticket_id == ticket_id) == 1
    storage.available = True
    worker_for().anonymize_due()
    db.expire_all()
    assert db.get(AppUser, user_id).anonymized_at is not None


def test_test_phone_gets_no_sms(app, client, login_client, worker_for, settings, db):
    test_settings = settings.model_copy(update={"sms_test_phones": PHONE, "sms_test_code": "4321"})
    session = login_client(PHONE)
    assert (
        client.delete(f"{API}/auth/pd-consent", headers=bearer(session["access_token"])).status_code
        == 202
    )
    sms = FakeSmsProvider()
    worker = worker_for(sms)
    worker.settings = test_settings
    worker.anonymize_due()
    assert sms.last_text(PHONE) is None
    db.expire_all()
    assert db.get(AppUser, session["user"]["id"]).anonymized_at is not None


def test_retention_purges_only_expired(client, login_client, db: Session, worker_for):
    session = login_client(PHONE)
    user_id = session["user"]["id"]
    register(client, bearer(session["access_token"]), "fcm-keep:" + "k" * 40)
    now = datetime.now(UTC)
    old, recent = now - timedelta(days=31), now - timedelta(days=1)
    db.add_all(
        [
            RefreshToken(user_id=user_id, token_hash="a" * 64, expires_at=old),
            RefreshToken(user_id=user_id, token_hash="b" * 64, expires_at=now, revoked_at=old),
            RefreshToken(user_id=user_id, token_hash="c" * 64, expires_at=now, revoked_at=recent),
            PushToken(user_id=user_id, token="fcm-old:" + "o" * 40, revoked_at=old),
        ]
    )
    old_note = Notification(type=NotificationType.NEWS, message="Акция")
    new_note = Notification(type=NotificationType.NEWS, message="Новости")
    db.add_all([old_note, new_note])
    db.flush()
    keep = db.scalars(select(PushToken).where(PushToken.revoked_at.is_(None))).one()
    db.add_all(
        [
            NotificationDelivery(
                notification_id=old_note.id,
                push_token_id=keep.id,
                created_at=now - timedelta(days=181),
            ),
            NotificationDelivery(notification_id=new_note.id, push_token_id=keep.id),
        ]
    )
    db.commit()
    purged = worker_for().purge()
    assert (purged.refresh_tokens, purged.push_tokens, purged.deliveries) == (2, 1, 1)
    assert count(db, RefreshToken, RefreshToken.user_id == user_id) == 2  # текущий + свежий отзыв
    assert worker_for().purge() is not None, "новый worker — сразу"


def test_queue_metrics(client_with_data, worker_for, db: Session) -> None:
    """Очередь анонимизации в метриках (глава 26): дольше 14 дней — critical-алерт. В общей БД
    тестов могут быть и другие клиенты в очереди — сверка с запросом, а не с константой."""
    worker = worker_for()
    before, oldest = privacy.queue_stats(db)
    assert before >= 1 and oldest is not None
    worker.observe_queue()
    assert REGISTRY.get_sample_value("ev_privacy_queue_size") == before
    assert REGISTRY.get_sample_value("ev_privacy_queue_oldest_age_seconds") >= 0
    worker.run_once()
    after, _ = privacy.queue_stats(db)
    assert after < before
    assert REGISTRY.get_sample_value("ev_privacy_queue_size") == after
