"""Отправка исходящей очереди push (ADR 0019 п. 2, 9–11).

Строки очереди «арендуются»: короткая транзакция берёт пачку `FOR UPDATE SKIP LOCKED` и
сдвигает `next_attempt_at` на срок аренды — реплики worker не берут одно и то же. Отправка в
FCM идёт вне транзакции (параллельно, `push_send_concurrency`), исход каждой строки пишется
своим коротким COMMIT: `delivered_at`
(FCM принял), повтор с паузой `base × 4^(n−1)` или `failed_at` + `error_code`; мёртвый токен
отзывается. Так сбой посреди пачки не откатывает уже отправленные push (повторной рассылки
нет), а запросы API (`opened`) не ждут всю пачку. Окно «отправлено, исход не записан»
(падение процесса между вызовом FCM и COMMIT) — at-least-once: после аренды строка уйдёт ещё раз.

Право на уведомление проверяется заново при аренде (ADR 0021 п. 5): получатель — активный
клиент с действующим согласием ПД, авто уведомления не удалено и всё ещё его. Иначе доставка
закрывается без отправки (`RECIPIENT_NOT_ELIGIBLE`): блокировка, отзыв согласия, удаление или
передача авто после постановки в очередь не приводят к push.
"""

import contextlib
import logging
from collections import defaultdict, deque
from collections.abc import Callable
from concurrent.futures import FIRST_COMPLETED, Executor, Future, ThreadPoolExecutor, wait
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import ColumnElement, and_, exists, or_, select, update
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.domain.notifications.push import Outcome, PushMessage, PushResult, PushSender
from app.domain.notifications.service import eligible_client
from app.models import AppUser, Notification, NotificationDelivery, PushToken, Vehicle
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


def _recipient_eligible() -> ColumnElement[bool]:
    """Владелец токена всё ещё вправе получить уведомление (строка запроса `_lease`)."""
    owns_vehicle = exists(
        select(Vehicle.id).where(
            Vehicle.id == Notification.vehicle_id,
            Vehicle.user_id == PushToken.user_id,
            Vehicle.deleted_at.is_(None),
        )
    )
    return and_(
        exists(select(AppUser.id).where(AppUser.id == PushToken.user_id, *eligible_client())),
        or_(Notification.vehicle_id.is_(None), owns_vehicle),
    )


def _lease(db: Session, settings: Settings) -> tuple[list[_Leased], int]:
    """Арендованные строки и число строк, закрытых сразу (токен отозван, получатель не вправе)."""
    now = datetime.now(UTC)
    rows = db.execute(
        select(
            NotificationDelivery,
            PushToken,
            Notification,
            _recipient_eligible().label("eligible"),
        )
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
    for delivery, token, notification, eligible in rows:
        if token.revoked_at is not None or not eligible:
            delivery.failed_at = now
            delivery.error_code = (
                "TOKEN_REVOKED" if token.revoked_at is not None else "RECIPIENT_NOT_ELIGIBLE"
            )
            closed += 1
            continue
        delivery.next_attempt_at = now + timedelta(seconds=settings.push_lease_seconds)
        leased.append(_Leased(delivery.id, token.id, message_for(notification, token.token)))
    db.commit()
    return leased, closed


def send_safely(sender: PushSender, message: PushMessage) -> PushResult:
    """Отправка без исключений: сбой отправителя — повтор (RETRY), worker не падает."""
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


class _Inline(Executor):
    """Отправка в вызывающем потоке — когда параллельность выключена (`push_send_concurrency=1`)."""

    def submit(self, fn: Callable[..., PushResult], /, *args: object) -> Future[PushResult]:
        future: Future[PushResult] = Future()
        future.set_result(fn(*args))
        return future


def dispatch_due(
    db: Session,
    sender: PushSender,
    settings: Settings,
    stopping: Callable[[], bool] = lambda: False,
    pool: Executor | None = None,
) -> int:
    """Одна пачка ждущих доставок; возвращает число обработанных строк.

    С `pool` вызовы FCM идут параллельно (ADR 0028 п. 12): ответ FCM ~100 мс, и рассылка на
    10 000 получателей последовательно заняла бы ~17 мин. Параллельно — разные токены; доставки
    одного токена — по очереди: исход предыдущей записан до проверки следующей, и мёртвый токен
    не уходит в FCM повторно. БД — только в этом потоке (сессия не потокобезопасна).

    При остановке процесса новые отправки не начинаются, начатые дописываются; неотправленные
    строки остаются арендованными и уйдут после истечения аренды — без повторной отправки уже
    доставленных.
    """
    runner = pool or _Inline()
    leased, done = _lease(db, settings)
    queues: dict[int, deque[_Leased]] = defaultdict(deque)
    for item in leased:
        queues[item.token_id].append(item)
    in_flight: dict[Future[PushResult], _Leased] = {}

    def start_next(token_id: int) -> int:
        """Следующая доставка токена — в отправку; возвращает число закрытых без отправки."""
        closed = 0
        queue = queues[token_id]
        while queue and not stopping():
            item = queue.popleft()
            if _token_revoked(db, item.token_id):
                failed = PushResult(Outcome.FAILED, "TOKEN_REVOKED")
                _record(db, settings, item, failed, attempted=False)
                closed += 1
                continue
            db.commit()  # не держать транзакцию открытой во время сетевого вызова
            in_flight[runner.submit(send_safely, sender, item.message)] = item
            break
        return closed

    for token_id in list(queues):
        done += start_next(token_id)
    while in_flight:
        finished, _ = wait(in_flight, return_when=FIRST_COMPLETED)
        for future in finished:
            item = in_flight.pop(future)
            _record(db, settings, item, future.result())
            done += 1 + start_next(item.token_id)
    return done


def drain(
    db: Session,
    sender: PushSender,
    settings: Settings,
    stopping: Callable[[], bool] = lambda: False,
) -> int:
    """Отправляет, пока пачки полные и процесс не останавливается; возвращает число строк.

    Параллельность отправки — `push_send_concurrency` (1 — последовательно, без пула).
    """
    total = 0
    with contextlib.ExitStack() as stack:
        pool = None
        if settings.push_send_concurrency > 1:
            pool = stack.enter_context(ThreadPoolExecutor(settings.push_send_concurrency))
        while not stopping():
            done = dispatch_due(db, sender, settings, stopping, pool)
            total += done
            if done < settings.notifications_batch_size:
                break
    return total
