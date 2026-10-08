# Alembic

Схема БД меняется только новой ревизией; применённые ревизии не редактируются.

```bash
cd backend
poetry run alembic upgrade head          # DATABASE_URL из окружения
poetry run alembic downgrade -1
poetry run alembic revision --autogenerate -m "<slug>"   # затем ручное ревью
poetry run python scripts/export_ddl.py  # перегенерация docs/EV_ServiceDesk_Glava2_DDL.sql
```

Autogenerate не видит триггеры, функции, значения ENUM и текст CHECK — их проверяют
тесты `tests/db/`.
