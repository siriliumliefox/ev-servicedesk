"""SMS-коды входа (ADR 0005, 0013): только Redis, HMAC вместо кода, TTL и счётчик попыток.

Ключ `auth:code:{phone}` — хэш {h: HMAC, attempts: число вводов}, живёт TTL секунд.
Попытка резервируется атомарно (Lua) ДО сравнения кода: параллельные запросы не обходят
лимиты 5 вводов на код и N неверных вводов в сутки. Код одноразовый: удаляется только
тот код, который был проверен (compare-and-delete), — победитель среди параллельных один.
"""

from dataclasses import dataclass
from enum import Enum

from redis import Redis

from app.core import rate_limit
from app.core.config import Settings
from app.core.errors import ApiError, rate_limited
from app.core.security import generate_sms_code, hash_sms_code, sms_code_matches
from app.domain.auth.sms import SmsError, SmsProvider

CODE_PREFIX = "auth:code:"
SMS_TEXT = "EV-ServiceDesk: код входа {code}. Никому не сообщайте его."
DAY = 24 * 3600

# KEYS: код, суточный счётчик; ARGV: попыток на код, неверных вводов в сутки, окно (с).
# {0} — кода нет; {-1} — попытки кода исчерпаны (код удалён); {-2, ttl} — суточный лимит;
# {1, h, attempts} — попытка зарезервирована, можно сравнивать.
_RESERVE = """
local h = redis.call('HGET', KEYS[1], 'h')
if not h then return {0} end
local daily = redis.call('INCR', KEYS[2])
if daily == 1 then redis.call('EXPIRE', KEYS[2], ARGV[3]) end
if daily > tonumber(ARGV[2]) then return {-2, redis.call('TTL', KEYS[2])} end
local attempts = redis.call('HINCRBY', KEYS[1], 'attempts', 1)
if attempts > tonumber(ARGV[1]) then
  redis.call('DEL', KEYS[1])
  return {-1}
end
return {1, h, attempts}
"""

# Верный код не тратит попытку: он ещё может понадобиться после 422 PD_CONSENT_REQUIRED.
# Попытка кода возвращается только тому коду, который проверялся (ARGV[1] — его HMAC):
# выпущенный тем временем новый код не получает лишних попыток. Счётчики не уходят ниже 0.
_REFUND = """
if redis.call('HGET', KEYS[1], 'h') == ARGV[1] then
  local attempts = tonumber(redis.call('HGET', KEYS[1], 'attempts'))
  if attempts and attempts > 0 then redis.call('HINCRBY', KEYS[1], 'attempts', -1) end
end
local daily = tonumber(redis.call('GET', KEYS[2]))
if daily and daily > 0 then redis.call('DECR', KEYS[2]) end
return 1
"""

_CONSUME = """
if redis.call('HGET', KEYS[1], 'h') == ARGV[1] then return redis.call('DEL', KEYS[1]) end
return 0
"""


def code_key(phone: str) -> str:
    return CODE_PREFIX + phone


def _daily_key(phone: str) -> str:
    return rate_limit.PREFIX + f"verify-fail:{phone}"


class CodeCheck(Enum):
    OK = "ok"
    WRONG = "wrong"
    MISSING = "missing"  # не запрашивался, истёк TTL или исчерпаны попытки


@dataclass(frozen=True)
class CodeResult:
    status: CodeCheck
    attempts_left: int = 0
    code_hash: str = ""  # HMAC проверенного кода — для compare-and-delete в consume_code


def request_code(
    redis: Redis, sms: SmsProvider, settings: Settings, phone: str, client_ip: str
) -> int:
    """Выпускает и отправляет код; возвращает TTL в секундах. Лимиты — 429."""
    rate_limit.enforce(
        redis,
        f"sms-ip:{client_ip}",
        3600,
        settings.sms_requests_per_ip_hour,
        "Слишком много запросов кода с этого адреса",
    )

    cooldown_key = f"sms-cooldown:{phone}"
    wait = rate_limit.acquire_cooldown(redis, cooldown_key, settings.sms_resend_cooldown_seconds)
    if wait:
        raise rate_limited(wait, "Повторный запрос кода возможен позже")

    phone_key = f"sms-phone:{phone}"
    rate_limit.enforce(
        redis,
        phone_key,
        3600,
        settings.sms_requests_per_phone_hour,
        "Превышен лимит SMS на этот номер",
    )

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
        if not exc.delivery_unknown:
            # SMS точно не ушло: код недействителен, пауза и лимит номера не тратятся.
            redis.delete(key)
            rate_limit.reset(redis, cooldown_key)
            rate_limit.undo_hit(redis, phone_key)
        # Если доставка неизвестна (таймаут ответа A1), код остаётся действующим:
        # SMS могло дойти, а повтор раньше паузы создал бы платный дубль.
        if exc.invalid_recipient:
            raise ApiError(422, "PHONE_NOT_SUPPORTED", "SMS на этот номер не доставляется") from exc
        raise ApiError(503, "SMS_UNAVAILABLE", "Не удалось отправить SMS, повторите позже") from exc
    return settings.sms_code_ttl_seconds


def check_code(redis: Redis, settings: Settings, phone: str, code: str) -> CodeResult:
    """Проверяет код, не расходуя его. Каждый ввод сначала резервирует попытку."""
    keys = [code_key(phone), _daily_key(phone)]
    reserved = redis.register_script(_RESERVE)(
        keys=keys,
        args=[settings.sms_code_max_attempts, settings.verify_failures_per_phone_day, DAY],
    )
    status = int(reserved[0])
    if status == 0:
        return CodeResult(CodeCheck.MISSING)
    if status == -2:
        raise rate_limited(int(reserved[1]), "Превышен суточный лимит попыток ввода кода")
    if status == -1:
        raise rate_limited(
            settings.sms_resend_cooldown_seconds, "Исчерпаны попытки ввода кода, запросите новый"
        )

    expected, attempts = str(reserved[1]), int(reserved[2])
    if sms_code_matches(phone, code, expected, settings):
        redis.register_script(_REFUND)(keys=keys, args=[expected])
        return CodeResult(CodeCheck.OK, code_hash=expected)
    if attempts >= settings.sms_code_max_attempts:
        # Код сгорает (нужен новый запрос) — именно проверенный, а не выпущенный следом.
        redis.register_script(_CONSUME)(keys=[keys[0]], args=[expected])
        raise rate_limited(
            settings.sms_resend_cooldown_seconds, "Исчерпаны попытки ввода кода, запросите новый"
        )
    return CodeResult(CodeCheck.WRONG, attempts_left=settings.sms_code_max_attempts - attempts)


def consume_code(redis: Redis, phone: str, code_hash: str) -> bool:
    """Одноразовость: удаляет именно проверенный код; True — только у одного запроса."""
    return bool(redis.register_script(_CONSUME)(keys=[code_key(phone)], args=[code_hash]))
