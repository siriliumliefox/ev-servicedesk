"""Отправка исходящей очереди push (ADR 0019 п. 2, 9–11).

Строки очереди «арендуются»: короткая транзакция берёт пачку `FOR UPDATE SKIP LOCKED` и
сдвигает `next_attempt_at` на срок аренды — реплики worker не берут одно и то же. Отправка в
FCM идёт вне транзакции, исход каждой строки пишется своим коротким COMMIT: `delivered_at`
(FCM принял), повтор с паузой `base × 4^(n−1)` или `failed_at` + `error_code`; мёртвый токен
отзывается. Так сбой посреди пачки не откатывает уже отправленные push (повторной рассылки
нет), а запросы API (`opened`) не ждут всю пачку. Окно «отправлено, исход не записан»
(падение процесса между вызовом FCM и COMMIT) — at-least-once: после аренды строка уйдёт ещё раз.
"""

import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.domain.notifications.push import Outcome, PushMessage, PushResult, PushSender
from app.models import Notification, NotificationDelivery, PushToken
from app.models.enums import NotificationType

TITLES = {
    NotificationType.FIRMWARE: "Новая прошивка",
    NotificationType.MAINTENANCE: "Пора на ТО",
    NotificationType.NEWS: "Новости",
    NotificationType.PROMO: "Акция",
}
RETRY_FACTOR = 4

logger = logging.getLogger(__name__)


def message_for(notification: Notification, token: str) -> PushMessage:
    """Заголовок по типу, текст уведомления и идентификаторы для перехода (без ПД)."""
    data = {"notification_id": str(notification.id), "type": notification.type.value}
    if notification.vehicle_id is not None:
        data["vehicle_id"] = str(notification.vehicle_id)
    if notification.aggregate_type_id is not None:
        data["aggregate_type_id"] = str(notification.aggregate_type_id)
    return PushMessage(token, TITLES[notification.type], notification.message, data)


def retry_delay(settings: Settings, attempts: int) -> timedelta:
    return timedelta(seconds=settings.push_retry_base_seconds * RETRY_FACTOR ** (attempts - 1))


@dataclass(frozen=True)
class _Leased:
    delivery_id: int
    token_id: int
    message: PushMessage


def _lease(db: Session, settings: Settings) -> tuple[list[_Leased], int]:
    """Арендованные строки и число строк, закрытых сразу (токен уже отозван)."""
    now = datetime.now(UTC)
    rows = db.execute(
        select(NotificationDelivery, PushToken, Notification)
        .join(PushToken, PushToken.id == NotificationDelivery.push_token_id)
        .join(Notification, Notification.id == NotificationDelivery.notification_id)
        .where(
            NotificationDelivery.delivered_at.is_(None),
            NotificationDelivery.failed_at.is_(None),
            NotificationDelivery.next_attempt_at <= now,
        )
        .order_by(NotificationDelivery.next_attempt_at, NotificationDelivery.id)
        .limit(settings.notifications_batch_size)
        .with_for_update(of=NotificationDelivery, skip_locked=True)
    ).all()
    leased = []
    closed = 0
    for delivery, token, notification in rows:
        if token.revoked_at is not None:
            delivery.failed_at = now
            delivery.error_code = "TOKEN_REVOKED"
            closed += 1
            continue
        delivery.next_attempt_at = now + timedelta(seconds=settings.push_lease_seconds)
        leased.append(_Leased(delivery.id, token.id, message_for(notification, token.token)))
    db.commit()
    return leased, closed


def _send(sender: PushSender, message: PushMessage) -> PushResult:
    try:
        return sender.send(message)
    except Exception:  # noqa: BLE001 — сбой отправителя не должен ронять worker
        logger.exception("Сбой отправителя push")
        return PushResult(Outcome.RETRY, "SENDER_ERROR")


def _record(
    db: Session, settings: Settings, item: _Leased, result: PushResult, *, attempted: bool = True
) -> None:
    """Исход одной доставки — отдельной короткой транзакцией."""
    delivery = db.get_one(
        NotificationDelivery, item.delivery_id, with_for_update=True, populate_existing=True
    )
    now = datetime.now(UTC)
    if attempted:
        delivery.attempts += 1
    delivery.error_code = result.error_code
    if result.outcome is Outcome.SENT:
        delivery.delivered_at = now
    elif result.outcome is Outcome.INVALID_TOKEN:
        delivery.failed_at = now
        db.execute(
            update(PushToken)
            .where(PushToken.id == item.token_id, PushToken.revoked_at.is_(None))
            .values(revoked_at=now)
        )
    elif result.outcome is Outcome.RETRY and delivery.attempts < settings.push_max_attempts:
        delivery.next_attempt_at = now + retry_delay(settings, delivery.attempts)
    else:
        delivery.failed_at = now
    if result.outcome is not Outcome.SENT:
        # Без токена и текста: только id строки журнала и код FCM.
        logger.warning(
            "Push не доставлен: delivery %s, %s, попытка %s",
            delivery.id,
            result.error_code,
            delivery.attempts,
        )
    db.commit()


def _token_revoked(db: Session, token_id: int) -> bool:
    """Токен могли отозвать после аренды (мёртвый токен в той же пачке, выход из аккаунта)."""
    return db.scalar(select(PushToken.revoked_at).where(PushToken.id == token_id)) is not None


def dispatch_due(
    db: Session,
    sender: PushSender,
    settings: Settings,
    stopping: Callable[[], bool] = lambda: False,
) -> int:
    """Одна пачка ждущих доставок; возвращает число обработанных строк.

    При остановке процесса недоотправленные строки остаются арендованными и уйдут после
    истечения аренды — без повторной отправки уже доставленных.
    """
    leased, done = _lease(db, settings)
    for item in leased:
        if stopping():
            break
        if _token_revoked(db, item.token_id):
            _record(
                db, settings, item, PushResult(Outcome.FAILED, "TOKEN_REVOKED"), attempted=False
            )
        else:
            db.commit()  # не держать транзакцию открытой во время сетевого вызова
            _record(db, settings, item, _send(sender, item.message))
        done += 1
    return done


def drain(
    db: Session,
    sender: PushSender,
    settings: Settings,
    stopping: Callable[[], bool] = lambda: False,
) -> int:
    """Отправляет, пока пачки полные и процесс не останавливается; возвращает число строк."""
    total = 0
    while not stopping():
        done = dispatch_due(db, sender, settings, stopping)
        total += done
        if done < settings.notifications_batch_size:
            break
    return total
