"""SMS-коды входа (ADR 0005, 0013): только Redis, HMAC вместо кода, TTL и счётчик попыток.

Ключ `auth:code:{phone}` — хэш {h: HMAC, attempts: число неверных вводов}, живёт TTL секунд.
Код одноразовый: после успешного входа ключ удаляется (DEL — победитель один).
"""

from dataclasses import dataclass
from enum import Enum

from redis import Redis

from app.core.config import Settings
from app.core.errors import ApiError, rate_limited
from app.core.security import generate_sms_code, hash_sms_code, sms_code_matches
from app.domain.auth import rate_limit
from app.domain.auth.sms import SmsError, SmsProvider

CODE_PREFIX = "auth:code:"
SMS_TEXT = "EV-ServiceDesk: код входа {code}. Никому не сообщайте его."


def code_key(phone: str) -> str:
    return CODE_PREFIX + phone


class CodeCheck(Enum):
    OK = "ok"
    WRONG = "wrong"
    MISSING = "missing"  # не запрашивался, истёк TTL или исчерпаны попытки


@dataclass(frozen=True)
class CodeResult:
    status: CodeCheck
    attempts_left: int = 0


def request_code(
    redis: Redis, sms: SmsProvider, settings: Settings, phone: str, client_ip: str
) -> int:
    """Выпускает и отправляет код; возвращает TTL в секундах. Лимиты — 429."""
    ip_hit = rate_limit.hit(redis, f"sms-ip:{client_ip}", 3600)
    if ip_hit.exceeded(settings.sms_requests_per_ip_hour):
        raise rate_limited(ip_hit.retry_after, "Слишком много запросов кода с этого адреса")

    wait = rate_limit.acquire_cooldown(
        redis, f"sms-cooldown:{phone}", settings.sms_resend_cooldown_seconds
    )
    if wait:
        raise rate_limited(wait, "Повторный запрос кода возможен позже")

    phone_hit = rate_limit.hit(redis, f"sms-phone:{phone}", 3600)
    if phone_hit.exceeded(settings.sms_requests_per_phone_hour):
        raise rate_limited(phone_hit.retry_after, "Превышен лимит SMS на этот номер")

    code = generate_sms_code(settings.sms_code_length)
    key = code_key(phone)
    with redis.pipeline(transaction=True) as pipe:
        pipe.delete(key)  # новый код сбрасывает старый и счётчик попыток
        pipe.hset(key, mapping={"h": hash_sms_code(phone, code, settings), "attempts": 0})
        pipe.expire(key, settings.sms_code_ttl_seconds)
        pipe.execute()

    try:
        sms.send(phone, SMS_TEXT.format(code=code))
    except SmsError as exc:
        redis.delete(key)
        if exc.invalid_recipient:
            raise ApiError(422, "PHONE_NOT_SUPPORTED", "SMS на этот номер не доставляется") from exc
        raise ApiError(503, "SMS_UNAVAILABLE", "Не удалось отправить SMS, повторите позже") from exc
    return settings.sms_code_ttl_seconds


def check_code(redis: Redis, settings: Settings, phone: str, code: str) -> CodeResult:
    """Проверяет код, не расходуя его. Неверный ввод увеличивает счётчик попыток."""
    failures = rate_limit.peek(redis, f"verify-fail:{phone}")
    if failures.count >= settings.verify_failures_per_phone_day:
        raise rate_limited(failures.retry_after, "Превышен суточный лимит попыток ввода кода")

    key = code_key(phone)
    expected = redis.hget(key, "h")
    if expected is None:
        return CodeResult(CodeCheck.MISSING)
    if sms_code_matches(phone, code, expected, settings):
        return CodeResult(CodeCheck.OK)

    with redis.pipeline(transaction=True) as pipe:
        pipe.hincrby(key, "attempts", 1)
        pipe.ttl(key)
        attempts, ttl = pipe.execute()
    rate_limit.hit(redis, f"verify-fail:{phone}", 24 * 3600)
    if ttl == -1:
        # Ключ удалили параллельно (вход/новый код), HINCRBY создал его заново без TTL.
        redis.delete(key)
        return CodeResult(CodeCheck.MISSING)
    if attempts >= settings.sms_code_max_attempts:
        redis.delete(key)  # код сгорает: нужен новый запрос
        raise rate_limited(
            settings.sms_resend_cooldown_seconds, "Исчерпаны попытки ввода кода, запросите новый"
        )
    return CodeResult(CodeCheck.WRONG, attempts_left=settings.sms_code_max_attempts - attempts)


def consume_code(redis: Redis, phone: str) -> bool:
    """Одноразовость: True только у одного из параллельных запросов."""
    return bool(redis.delete(code_key(phone)))
