"""Разовый запуск напоминаний о ТО (ADR 0019 п. 7): тесты, smoke, E2E на устройстве.

`python -m app.workers.maintenance_reminders [--date YYYY-MM-DD]` — создаёт положенные
напоминания и ставит их в очередь; отправляет worker уведомлений. `--date` — «сегодня» для
расчёта статусов (проверка на данных с искусственно «просроченными» агрегатами).
"""

import argparse
import sys
from datetime import date

from redis import Redis

from app.core.config import get_settings
from app.core.db import get_session_scope
from app.core.logging import configure_logging
from app.domain.notifications.outbox import Outbox
from app.domain.notifications.reminders import run_maintenance_reminders


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Напоминания о ТО (ADR 0019)")
    parser.add_argument("--date", type=date.fromisoformat, default=None)
    args = parser.parse_args(argv)
    configure_logging()
    settings = get_settings()
    redis = Redis.from_url(settings.redis_url, decode_responses=True)
    outbox = Outbox(redis, settings.redis_channel_prefix)
    with get_session_scope()() as db:
        created = run_maintenance_reminders(db, outbox, args.date)
    if created is None:
        print("Задачу сейчас выполняет другой экземпляр")
        return 1
    print(f"Напоминаний о ТО создано: {created}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
