"""Отправка исходящей очереди push (ADR 0019 п. 2, 9–11).

Пачка ждущих строк `notification_delivery` берётся `FOR UPDATE SKIP LOCKED` — реплики worker
не отправляют одно и то же дважды. Исход каждой отправки пишется в ту же строку:
`delivered_at` (FCM принял), повтор с паузой `base × 4^(n−1)` или `failed_at` + `error_code`;
мёртвый токен отзывается.
"""

from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.domain.notifications.push import Outcome, PushMessage, PushSender
from app.models import Notification, NotificationDelivery, PushToken
from app.models.enums import NotificationType

TITLES = {
    NotificationType.FIRMWARE: "Новая прошивка",
    NotificationType.MAINTENANCE: "Пора на ТО",
    NotificationType.NEWS: "Новости",
    NotificationType.PROMO: "Акция",
}
RETRY_FACTOR = 4


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


def dispatch_due(db: Session, sender: PushSender, settings: Settings) -> int:
    """Одна пачка ждущих доставок; возвращает число обработанных строк."""
    rows = db.execute(
        select(NotificationDelivery, PushToken, Notification)
        .join(PushToken, PushToken.id == NotificationDelivery.push_token_id)
        .join(Notification, Notification.id == NotificationDelivery.notification_id)
        .where(
            NotificationDelivery.delivered_at.is_(None),
            NotificationDelivery.failed_at.is_(None),
            NotificationDelivery.next_attempt_at <= datetime.now(UTC),
        )
        .order_by(NotificationDelivery.next_attempt_at, NotificationDelivery.id)
        .limit(settings.notifications_batch_size)
        .with_for_update(of=NotificationDelivery, skip_locked=True)
    ).all()
    for delivery, token, notification in rows:
        if token.revoked_at is not None:
            delivery.failed_at = datetime.now(UTC)
            delivery.error_code = "TOKEN_REVOKED"
            continue
        result = sender.send(message_for(notification, token.token))
        now = datetime.now(UTC)
        delivery.attempts += 1
        delivery.error_code = result.error_code
        if result.outcome is Outcome.SENT:
            delivery.delivered_at = now
        elif result.outcome is Outcome.INVALID_TOKEN:
            delivery.failed_at = now
            token.revoked_at = now
        elif result.outcome is Outcome.RETRY and delivery.attempts < settings.push_max_attempts:
            delivery.next_attempt_at = now + retry_delay(settings, delivery.attempts)
        else:
            delivery.failed_at = now
    db.commit()
    return len(rows)


def drain(db: Session, sender: PushSender, settings: Settings) -> int:
    """Отправляет, пока пачки полные; возвращает общее число обработанных строк."""
    total = 0
    while True:
        done = dispatch_due(db, sender, settings)
        total += done
        if done < settings.notifications_batch_size:
            return total
