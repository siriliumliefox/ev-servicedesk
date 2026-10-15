"""Места одновременных подключений в Redis (глава 24, ADR 0028 п. 15).

Лимит общий для всех процессов uvicorn: в памяти процесса он умножался бы на их число.
Место упавшего процесса освобождается по истечении аренды.
"""

import time

from redis import Redis

from app.core.rate_limit import Slot


def slot(redis: Redis, member: str, lease: int = 60) -> Slot:
    return Slot(redis, "ws-user:7", member, lease)


def test_limit_is_shared_between_processes(real_redis: Redis) -> None:
    # Разные экземпляры Slot — как подключения в разных процессах: общее только Redis.
    assert slot(real_redis, "a").acquire(2)
    assert slot(real_redis, "b").acquire(2)
    assert not slot(real_redis, "c").acquire(2)
    slot(real_redis, "a").release()
    assert slot(real_redis, "c").acquire(2), "закрытое подключение освобождает место"


def test_expired_lease_frees_place_of_crashed_process(real_redis: Redis) -> None:
    assert slot(real_redis, "crashed", lease=1).acquire(1)
    assert not slot(real_redis, "next").acquire(1)
    time.sleep(2.1)
    assert slot(real_redis, "next").acquire(1), "аренда упавшего процесса истекла"


def test_renew_keeps_live_connection(real_redis: Redis) -> None:
    live = slot(real_redis, "live", lease=2)
    assert live.acquire(1)
    for _ in range(3):
        time.sleep(1.1)
        live.renew()
    assert not slot(real_redis, "other").acquire(1), "продлённая аренда держит место"
    assert real_redis.ttl("auth:rl:ws-user:7") > 0, "ключ не живёт вечно"


def test_renew_of_released_slot_does_not_resurrect_it(real_redis: Redis) -> None:
    gone = slot(real_redis, "gone")
    assert gone.acquire(1)
    gone.release()
    gone.renew()
    assert slot(real_redis, "new").acquire(1)
