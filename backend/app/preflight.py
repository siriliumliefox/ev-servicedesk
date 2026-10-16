"""Проверка перед стартом API (глава 24, ADR 0028 п. 18): `python -m app.preflight`.

С несколькими процессами uvicorn (WEB_CONCURRENCY) упавший при старте процесс перезапускает
супервизор, и контейнер не завершается — fail closed пропадал бы. Поэтому до запуска uvicorn,
в одном процессе: настройки (секреты-заглушки, фейковые SMS и push в production — ошибка
`Settings`) и вне local/test — доступный бакет S3 (ADR 0017 п. 11). Ошибка — ненулевой код
выхода и причина в логе; проверка в lifespan каждого процесса остаётся второй линией.
"""

import sys

from app.core.config import SAFE_ENVIRONMENTS, get_settings
from app.core.storage import get_storage


def main() -> int:
    settings = get_settings()
    if settings.environment not in SAFE_ENVIRONMENTS:
        get_storage().check_bucket()
    return 0


if __name__ == "__main__":
    sys.exit(main())
