"""Атомарность claim тикета на уровне схемы: два инженера, два соединения, один победитель.

Данные коммитятся (иначе второе соединение их не увидит) и удаляются в finally.
"""

import threading

from sqlalchemy import Engine, text

from tests.db.factories import make_ticket, make_user, make_vehicle, scalar

CLAIM = text(
    "UPDATE ticket SET assigned_engineer_id = :e, status = 'in_progress' "
    "WHERE id = :t AND assigned_engineer_id IS NULL RETURNING id"
)


def test_concurrent_claim_has_single_winner(migrated_engine: Engine) -> None:
    with migrated_engine.begin() as c:
        first, second = make_user(c, "engineer"), make_user(c, "engineer")
        vehicle = make_vehicle(c)
        owner = scalar(c, "SELECT user_id FROM vehicle WHERE id = :v", v=vehicle)
        model = scalar(c, "SELECT vehicle_model_id FROM vehicle WHERE id = :v", v=vehicle)
        ticket = make_ticket(c, vehicle)

    results: dict[str, list] = {}
    try:
        c1 = migrated_engine.connect()
        tx1 = c1.begin()
        results["first"] = c1.execute(CLAIM, {"e": first, "t": ticket}).all()

        def claim_second() -> None:
            with migrated_engine.connect() as c2, c2.begin():
                results["second"] = c2.execute(CLAIM, {"e": second, "t": ticket}).all()

        worker = threading.Thread(target=claim_second)
        worker.start()
        worker.join(timeout=1.0)
        assert worker.is_alive(), "второй claim должен ждать row lock первого"
        tx1.commit()
        c1.close()
        worker.join(timeout=10)
        assert not worker.is_alive()

        assert results["first"] == [(ticket,)]
        assert results["second"] == []  # сервисный слой отдаст 409
        with migrated_engine.connect() as c:
            assert (
                scalar(c, "SELECT assigned_engineer_id FROM ticket WHERE id = :t", t=ticket)
                == first
            )
    finally:
        with migrated_engine.begin() as c:
            c.execute(text("DELETE FROM ticket WHERE id = :t"), {"t": ticket})
            c.execute(text("DELETE FROM vehicle WHERE id = :v"), {"v": vehicle})
            c.execute(text("DELETE FROM vehicle_model WHERE id = :m"), {"m": model})
            c.execute(
                text("DELETE FROM app_user WHERE id = ANY(:ids)"), {"ids": [first, second, owner]}
            )
