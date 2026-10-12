"""Глава 14 (#63, ADR 0018 п. 12): пять сценариев «Устранение неполадок» с деревьями решений.

По одной опубликованной статье на каждую категорию ошибки (= категория тикета): сбой
приложения после русификации, навигация, звук и Bluetooth, связь SIM/eSIM, напоминание о ТО.
Общие для всех моделей (vehicle_model_id NULL); версия 1 — снимок с деревом. Каждое дерево
проходит проверку тупиков (tests/api/test_knowledge_checklist.py). Тексты утверждает
владелец проекта; дальнейшая правка — админ-панель (новые версии).

Revision ID: 0011
Revises: 0010
Create Date: 2026-10-12
"""

from collections.abc import Sequence
from typing import Any

from alembic import op

revision: str = "0011"
down_revision: str | None = "0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SOLVED = "Проблема решена. Если она повторится — пройдите шаги снова или создайте обращение."
ESCALATE = (
    "Самостоятельно решить не удалось — создайте обращение. Инженер увидит пройденные шаги "
    "и свяжется с вами в чате."
)

# Узел: ключ → (вопрос, [(вариант, ключ узла)], is_root, is_escalation). Без вариантов и не
# эскалация — решение («Проблема решена»).
Node = tuple[str, list[tuple[str, str]], bool, bool]

SCENARIOS: list[dict[str, Any]] = [
    {
        "category": "app_crash",
        "title": "Приложение на мультимедиа вылетает или не запускается",
        "content": (
            "Чаще всего приложение закрывается из-за переполненной памяти, устаревшего кэша "
            "или обновления прошивки, которое сбросило настройки русификации.\n\n"
            "Выполняйте шаги на стоянке, с включённым зажиганием."
        ),
        "nodes": {
            "root": (
                "Приложение закрывается сразу при запуске или через некоторое время работы?",
                [("Сразу при запуске", "reboot"), ("Через некоторое время", "memory")],
                True,
                False,
            ),
            "reboot": (
                "Перезагрузите мультимедиа: заглушите авто, закройте двери и подождите "
                "5 минут, затем включите зажигание. Приложение запускается?",
                [("Да, работает", "solved"), ("Нет, по-прежнему закрывается", "cache")],
                False,
                False,
            ),
            "memory": (
                "Откройте Настройки → Хранилище. Свободно меньше 1 ГБ?",
                [("Да, меньше 1 ГБ", "cleanup"), ("Нет, памяти достаточно", "cache")],
                False,
                False,
            ),
            "cleanup": (
                "Удалите неиспользуемые приложения и загруженные файлы, затем перезапустите "
                "приложение. Проблема ушла?",
                [("Да", "solved"), ("Нет", "cache")],
                False,
                False,
            ),
            "cache": (
                "Откройте Настройки → Приложения → проблемное приложение → «Очистить кэш» и "
                "запустите его снова. Работает?",
                [("Да", "solved"), ("Нет", "escalate")],
                False,
                False,
            ),
            "solved": (SOLVED, [], False, False),
            "escalate": (ESCALATE, [], False, True),
        },
    },
    {
        "category": "navigation",
        "title": "Навигация не строит маршрут или не показывает карту",
        "content": (
            "Навигации нужны мобильный интернет (карты и пробки) и сигнал спутников "
            "(местоположение). В подземном паркинге сигнала спутников нет."
        ),
        "nodes": {
            "root": (
                "Карта отображается на экране?",
                [("Да, карта есть", "position"), ("Нет, пустой экран или ошибка", "internet")],
                True,
                False,
            ),
            "internet": (
                "Работает ли мобильный интернет: есть значок сети, открываются другие "
                "онлайн-сервисы?",
                [("Да, интернет есть", "cache"), ("Нет интернета", "escalate")],
                False,
                False,
            ),
            "cache": (
                "Очистите кэш приложения навигации (Настройки → Приложения) и перезапустите "
                "его. Карта появилась?",
                [("Да", "solved"), ("Нет", "escalate")],
                False,
                False,
            ),
            "position": (
                "Местоположение авто на карте определяется верно?",
                [("Да", "route"), ("Нет или «Поиск сигнала»", "sky")],
                False,
                False,
            ),
            "sky": (
                "Выедьте на открытое место (не паркинг и не плотная застройка) и подождите "
                "5 минут. Местоположение определилось?",
                [("Да", "solved"), ("Нет", "escalate")],
                False,
                False,
            ),
            "route": (
                "Маршрут не строится до конкретного адреса? Выберите точку назначения "
                "вручную на карте. Маршрут построился?",
                [("Да", "solved"), ("Нет", "escalate")],
                False,
                False,
            ),
            "solved": (SOLVED, [], False, False),
            "escalate": (ESCALATE, [], False, True),
        },
    },
    {
        "category": "audio",
        "title": "Нет звука или не работает Bluetooth-аудио",
        "content": (
            "Сначала определите, пропал звук полностью или только при воспроизведении с "
            "телефона по Bluetooth: причины и шаги разные."
        ),
        "nodes": {
            "root": (
                "Звука нет совсем или только с телефона по Bluetooth?",
                [("Звука нет совсем", "volume"), ("Только по Bluetooth", "repair")],
                True,
                False,
            ),
            "volume": (
                "Проверьте громкость и что звук не выключен (значок динамика), переключите "
                "источник — радио или USB. Звук появился?",
                [("Да", "solved"), ("Нет", "reboot")],
                False,
                False,
            ),
            "reboot": (
                "Перезагрузите мультимедиа: заглушите авто, закройте двери и подождите "
                "5 минут. Звук появился?",
                [("Да", "solved"), ("Нет", "escalate")],
                False,
                False,
            ),
            "repair": (
                "Удалите авто из списка Bluetooth-устройств телефона, а телефон — из списка "
                "устройств мультимедиа, затем подключите заново. Звук идёт?",
                [("Да", "solved"), ("Нет", "other_phone")],
                False,
                False,
            ),
            "other_phone": (
                "Подключите другой телефон по Bluetooth. С ним звук работает?",
                [("Да, с другим работает", "phone_side"), ("Нет, тоже не работает", "escalate")],
                False,
                False,
            ),
            "phone_side": (
                "Причина — в вашем телефоне: обновите его систему и перезагрузите. Если не "
                "поможет, обратитесь к производителю телефона.",
                [],
                False,
                False,
            ),
            "solved": (SOLVED, [], False, False),
            "escalate": (ESCALATE, [], False, True),
        },
    },
    {
        "category": "sim",
        "title": "Нет мобильной связи или интернета (SIM/eSIM)",
        "content": (
            "Онлайн-сервисы мультимедиа (карты, музыка, обновления) работают через SIM или "
            "eSIM автомобиля. Проверьте сигнал сети и баланс у оператора."
        ),
        "nodes": {
            "root": (
                "Что видно в строке состояния?",
                [("Нет значка сети", "place"), ("Сеть есть, интернет не работает", "balance")],
                True,
                False,
            ),
            "place": (
                "Переместитесь в зону уверенного приёма (не подземный паркинг) и подождите "
                "несколько минут. Сеть появилась?",
                [("Да", "solved"), ("Нет", "reboot")],
                False,
                False,
            ),
            "reboot": (
                "Перезагрузите мультимедиа: заглушите авто, закройте двери и подождите "
                "5 минут. Сеть появилась?",
                [("Да", "solved"), ("Нет", "escalate")],
                False,
                False,
            ),
            "balance": (
                "Проверьте баланс и пакет трафика у оператора SIM/eSIM. Всё в порядке?",
                [("Да", "data"), ("Нет, баланс или трафик закончились", "top_up")],
                False,
                False,
            ),
            "top_up": (
                "Пополните баланс или подключите пакет трафика — интернет заработает после "
                "зачисления.",
                [],
                False,
                False,
            ),
            "data": (
                "Проверьте, что передача данных включена, а точка доступа (APN) — от вашего "
                "оператора. Интернет заработал?",
                [("Да", "solved"), ("Нет", "escalate")],
                False,
                False,
            ),
            "solved": (SOLVED, [], False, False),
            "escalate": (ESCALATE, [], False, True),
        },
    },
    {
        "category": "maintenance",
        "title": "Напоминание о ТО или индикатор сервиса",
        "content": (
            "Приложение напоминает о замене агрегатов по регламенту ТО и пробегу авто. "
            "Индикатор на приборной панели сбрасывают в сервисе после ТО."
        ),
        "nodes": {
            "root": (
                "Где вы видите напоминание?",
                [("В приложении", "mileage"), ("На приборной панели авто", "after_service")],
                True,
                False,
            ),
            "mileage": (
                "Пробег в карточке авто совпадает с одометром?",
                [("Нет, в приложении меньше", "update_mileage"), ("Совпадает", "replaced")],
                False,
                False,
            ),
            "update_mileage": (
                "Обновите пробег в карточке авто — статусы агрегатов пересчитаются.",
                [],
                False,
                False,
            ),
            "replaced": (
                "Агрегат из напоминания уже заменён?",
                [("Да, уже заменили", "escalate"), ("Нет", "plan")],
                False,
                False,
            ),
            "after_service": (
                "Индикатор загорелся сразу после ТО?",
                [("Да", "escalate"), ("Нет", "plan")],
                False,
                False,
            ),
            "plan": (
                "Это плановое напоминание: приближается замена по регламенту. Запланируйте "
                "визит в сервис.",
                [],
                False,
                False,
            ),
            "escalate": (
                "Создайте обращение — инженер проверит историю ТО, внесёт замену и сбросит "
                "напоминание.",
                [],
                False,
                True,
            ),
        },
    },
]

TITLES = [s["title"] for s in SCENARIOS]


def _lit(value: str) -> str:
    """Строковый литерал SQL: миграция рендерится и offline (scripts/export_ddl.py)."""
    return "'" + value.replace("'", "''") + "'"


def _scenario_sql(scenario: dict[str, Any]) -> str:
    """Блок DO: статья, узлы, переходы по id узлов и снимок версии 1 из записанных строк."""
    nodes: dict[str, Node] = scenario["nodes"]
    declare = "".join(f"n_{key} bigint; " for key in nodes)
    lines = [
        "INSERT INTO knowledge_article (article_type, category, title, content, is_published) "
        f"VALUES ('troubleshooting', {_lit(scenario['category'])}, {_lit(scenario['title'])}, "
        f"{_lit(scenario['content'])}, true) RETURNING id INTO a;"
    ]
    for key, (question, _, root, escalation) in nodes.items():
        lines.append(
            "INSERT INTO decision_tree_node (article_id, question_text, is_root, is_escalation) "
            f"VALUES (a, {_lit(question)}, {str(root).lower()}, {str(escalation).lower()}) "
            f"RETURNING id INTO n_{key};"
        )
    for key, (_, options, _, _) in nodes.items():
        if options:
            items = ", ".join(
                f"jsonb_build_object('label', {_lit(label)}, 'next_node_id', n_{target})"
                for label, target in options
            )
            lines.append(
                f"UPDATE decision_tree_node SET options = jsonb_build_array({items}) "
                f"WHERE id = n_{key};"
            )
    lines.append(
        "INSERT INTO knowledge_article_revision (article_id, version, title, content, category, "
        "decision_tree) SELECT a, 1, k.title, k.content, k.category, "
        "(SELECT jsonb_agg(jsonb_build_object('id', n.id, 'question_text', n.question_text, "
        "'options', n.options, 'is_root', n.is_root, 'is_escalation', n.is_escalation) "
        "ORDER BY n.id) FROM decision_tree_node n WHERE n.article_id = a) "
        "FROM knowledge_article k WHERE k.id = a;"
    )
    body = "\n    ".join(lines)
    return f"DO $$\nDECLARE a bigint; {declare}\nBEGIN\n    {body}\nEND $$;"


def upgrade() -> None:
    for scenario in SCENARIOS:
        op.execute(_scenario_sql(scenario))


def downgrade() -> None:
    """Удаляет только статьи этой миграции и только если на них не ссылаются тикеты.

    Статья миграции — версия 1 с заголовком сценария и временем публикации самой ранней такой
    версии: все сценарии записаны одной транзакцией (одно now()), а статья администратора с тем
    же заголовком (например, копия) опубликована позже. Переименованный сценарий находится по
    заголовку версии 1. Узлы и версии удаляются каскадом.
    """
    titles = ", ".join(_lit(t) for t in TITLES)
    op.execute(
        f"""
        DO $$
        DECLARE seeds bigint[];
        BEGIN
            SELECT array_agg(r.article_id) INTO seeds
            FROM knowledge_article_revision r
            WHERE r.version = 1 AND r.title IN ({titles})
              AND r.created_at = (
                  SELECT min(created_at) FROM knowledge_article_revision
                  WHERE version = 1 AND title IN ({titles})
              );
            -- Тикеты потеряли бы «пометку» эскалации (FK SET NULL) — данные не удаляются молча.
            IF EXISTS (SELECT 1 FROM ticket WHERE source_article_id = ANY(seeds)) THEN
                RAISE EXCEPTION 'На сценарии 0011 ссылаются тикеты — откат остановлен';
            END IF;
            DELETE FROM knowledge_article WHERE id = ANY(seeds);
        END $$;
        """
    )
