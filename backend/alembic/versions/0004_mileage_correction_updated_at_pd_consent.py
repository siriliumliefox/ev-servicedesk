"""Техдолг главы 2 (#15): корректировка пробега, триггер updated_at, история согласий ПД.

- vehicle_mileage_correction: append-only журнал; уменьшение пробега только через него,
  только admin, с причиной и проверкой актуального пробега (ADR 0006);
- set_updated_at: updated_at обновляется при любом UPDATE, не только через ORM;
- pd_consent: история согласий и отзыв (99-З, ст. 5, 10) вместо колонок
  app_user.pd_consent_at / pd_policy_version; существующие согласия переносятся.
  Строку согласия нельзя удалить или переписать — допустим только отзыв (withdrawn_at).

Revision ID: 0004
Revises: 0003
Create Date: 2026-10-08
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Таблицы с updated_at (сверяется с ORM в tests/db/test_audit_and_pd.py).
UPDATED_AT_TABLES = (
    "aggregate_type",
    "app_user",
    "decision_tree_node",
    "knowledge_article",
    "maintenance_regulation",
    "pd_consent",
    "push_token",
    "ticket",
    "vehicle",
    "vehicle_aggregate_status",
    "vehicle_model",
)

VEHICLE_GUARD_V1 = """
CREATE OR REPLACE FUNCTION vehicle_guard() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    IF NEW.vin IS DISTINCT FROM OLD.vin
       OR NEW.user_id IS DISTINCT FROM OLD.user_id
       OR NEW.vehicle_model_id IS DISTINCT FROM OLD.vehicle_model_id THEN
        RAISE EXCEPTION 'vehicle vin, user_id and vehicle_model_id are immutable'
            USING ERRCODE = 'check_violation', CONSTRAINT = 'vehicle_identity_immutable';
    END IF;
    IF NEW.mileage < OLD.mileage THEN
        RAISE EXCEPTION 'vehicle mileage cannot decrease'
            USING ERRCODE = 'check_violation', CONSTRAINT = 'vehicle_mileage_monotonic';
    END IF;
    RETURN NEW;
END;
$$
"""

# Уменьшение разрешено, только если в ТОЙ ЖЕ транзакции записана корректировка
# с теми же old/new (created_at принудительно = now() — время начала транзакции).
VEHICLE_GUARD_V2 = """
CREATE OR REPLACE FUNCTION vehicle_guard() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    IF NEW.vin IS DISTINCT FROM OLD.vin
       OR NEW.user_id IS DISTINCT FROM OLD.user_id
       OR NEW.vehicle_model_id IS DISTINCT FROM OLD.vehicle_model_id THEN
        RAISE EXCEPTION 'vehicle vin, user_id and vehicle_model_id are immutable'
            USING ERRCODE = 'check_violation', CONSTRAINT = 'vehicle_identity_immutable';
    END IF;
    IF NEW.mileage < OLD.mileage AND NOT EXISTS (
        SELECT 1 FROM vehicle_mileage_correction c
        WHERE c.vehicle_id = NEW.id
          AND c.old_mileage = OLD.mileage
          AND c.new_mileage = NEW.mileage
          AND c.created_at = now()
    ) THEN
        RAISE EXCEPTION 'vehicle mileage cannot decrease without an admin correction'
            USING ERRCODE = 'check_violation', CONSTRAINT = 'vehicle_mileage_monotonic';
    END IF;
    RETURN NEW;
END;
$$
"""


def upgrade() -> None:
    op.create_table(
        "pd_consent",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("policy_version", sa.String(length=20), nullable=False),
        sa.Column(
            "given_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column("withdrawn_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "btrim(policy_version) <> ''", name=op.f("ck_pd_consent_policy_version_not_blank")
        ),
        sa.CheckConstraint(
            "withdrawn_at IS NULL OR withdrawn_at >= given_at",
            name=op.f("ck_pd_consent_withdrawn_after_given"),
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["app_user.id"],
            name=op.f("fk_pd_consent_user_id_app_user"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_pd_consent")),
    )
    op.create_index(op.f("ix_pd_consent_user_id"), "pd_consent", ["user_id"], unique=False)
    op.create_index(
        "uq_pd_consent_active",
        "pd_consent",
        ["user_id"],
        unique=True,
        postgresql_where=sa.text("withdrawn_at IS NULL"),
    )
    op.create_index(
        "ix_pd_consent_withdrawn_at",
        "pd_consent",
        ["withdrawn_at"],
        unique=False,
        postgresql_where=sa.text("withdrawn_at IS NOT NULL"),
    )
    # Перенос существующих согласий до удаления колонок.
    op.execute(
        "INSERT INTO pd_consent (user_id, policy_version, given_at) "
        "SELECT id, pd_policy_version, pd_consent_at FROM app_user WHERE pd_consent_at IS NOT NULL"
    )
    op.drop_constraint(op.f("ck_app_user_pd_consent_pair"), "app_user", type_="check")
    op.drop_column("app_user", "pd_policy_version")
    op.drop_column("app_user", "pd_consent_at")

    op.create_table(
        "vehicle_mileage_correction",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column("vehicle_id", sa.BigInteger(), nullable=False),
        sa.Column("corrected_by_user_id", sa.BigInteger(), nullable=False),
        sa.Column("old_mileage", sa.Integer(), nullable=False),
        sa.Column("new_mileage", sa.Integer(), nullable=False),
        sa.Column("reason", sa.String(length=500), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "new_mileage >= 0", name=op.f("ck_vehicle_mileage_correction_new_mileage_non_negative")
        ),
        sa.CheckConstraint(
            "new_mileage < old_mileage", name=op.f("ck_vehicle_mileage_correction_decrease_only")
        ),
        sa.CheckConstraint(
            "btrim(reason) <> ''", name=op.f("ck_vehicle_mileage_correction_reason_not_blank")
        ),
        sa.ForeignKeyConstraint(
            ["corrected_by_user_id"],
            ["app_user.id"],
            name=op.f("fk_vehicle_mileage_correction_corrected_by_user_id_app_user"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["vehicle_id"],
            ["vehicle.id"],
            name=op.f("fk_vehicle_mileage_correction_vehicle_id_vehicle"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_vehicle_mileage_correction")),
    )
    op.create_index(
        op.f("ix_vehicle_mileage_correction_vehicle_id"),
        "vehicle_mileage_correction",
        ["vehicle_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_vehicle_mileage_correction_corrected_by_user_id"),
        "vehicle_mileage_correction",
        ["corrected_by_user_id"],
        unique=False,
    )

    # --- updated_at на уровне БД ---
    op.execute(
        """
        CREATE FUNCTION set_updated_at() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            NEW.updated_at := now();
            RETURN NEW;
        END;
        $$
        """
    )
    for table in UPDATED_AT_TABLES:
        op.execute(
            f"CREATE TRIGGER trg_set_updated_at BEFORE UPDATE ON {table} "
            "FOR EACH ROW EXECUTE FUNCTION set_updated_at()"
        )

    # --- Корректировка пробега ---
    op.execute(VEHICLE_GUARD_V2)
    op.execute(
        """
        CREATE FUNCTION mileage_correction_before_insert() RETURNS trigger
        LANGUAGE plpgsql AS $$
        DECLARE
            actor_role user_role;
            current_mileage integer;
        BEGIN
            SELECT role INTO actor_role FROM app_user WHERE id = NEW.corrected_by_user_id;
            IF actor_role IS DISTINCT FROM 'admin' THEN
                RAISE EXCEPTION 'only admin can correct vehicle mileage'
                    USING ERRCODE = 'check_violation',
                          CONSTRAINT = 'mileage_correction_admin_only';
            END IF;
            SELECT mileage INTO current_mileage FROM vehicle WHERE id = NEW.vehicle_id FOR UPDATE;
            IF current_mileage IS DISTINCT FROM NEW.old_mileage THEN
                RAISE EXCEPTION 'old_mileage does not match current vehicle mileage'
                    USING ERRCODE = 'check_violation',
                          CONSTRAINT = 'mileage_correction_stale';
            END IF;
            NEW.created_at := now();
            RETURN NEW;
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE FUNCTION mileage_correction_after_insert() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            UPDATE vehicle SET mileage = NEW.new_mileage WHERE id = NEW.vehicle_id;
            RETURN NULL;
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE FUNCTION append_only_guard() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            RAISE EXCEPTION '% is append-only', TG_TABLE_NAME
                USING ERRCODE = 'check_violation', CONSTRAINT = TG_TABLE_NAME || '_append_only';
        END;
        $$
        """
    )
    op.execute(
        "CREATE TRIGGER trg_mileage_correction_before_insert BEFORE INSERT "
        "ON vehicle_mileage_correction FOR EACH ROW "
        "EXECUTE FUNCTION mileage_correction_before_insert()"
    )
    op.execute(
        "CREATE TRIGGER trg_mileage_correction_after_insert AFTER INSERT "
        "ON vehicle_mileage_correction FOR EACH ROW "
        "EXECUTE FUNCTION mileage_correction_after_insert()"
    )
    op.execute(
        "CREATE TRIGGER trg_append_only BEFORE UPDATE OR DELETE "
        "ON vehicle_mileage_correction FOR EACH ROW EXECUTE FUNCTION append_only_guard()"
    )

    # --- Согласие ПД: доказательство неизменно, допустим только однократный отзыв ---
    op.execute(
        """
        CREATE FUNCTION pd_consent_guard() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            IF TG_OP = 'DELETE'
               OR OLD.withdrawn_at IS NOT NULL
               OR NEW.withdrawn_at IS NULL
               OR NEW.user_id IS DISTINCT FROM OLD.user_id
               OR NEW.policy_version IS DISTINCT FROM OLD.policy_version
               OR NEW.given_at IS DISTINCT FROM OLD.given_at
               OR NEW.created_at IS DISTINCT FROM OLD.created_at THEN
                RAISE EXCEPTION 'pd_consent allows only a single withdrawal (withdrawn_at)'
                    USING ERRCODE = 'check_violation', CONSTRAINT = 'pd_consent_withdraw_only';
            END IF;
            RETURN NEW;
        END;
        $$
        """
    )
    op.execute(
        "CREATE TRIGGER trg_pd_consent_guard BEFORE UPDATE OR DELETE "
        "ON pd_consent FOR EACH ROW EXECUTE FUNCTION pd_consent_guard()"
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS trg_pd_consent_guard ON pd_consent")
    op.execute("DROP FUNCTION IF EXISTS pd_consent_guard()")
    op.execute("DROP TRIGGER IF EXISTS trg_append_only ON vehicle_mileage_correction")
    op.execute(
        "DROP TRIGGER IF EXISTS trg_mileage_correction_after_insert ON vehicle_mileage_correction"
    )
    op.execute(
        "DROP TRIGGER IF EXISTS trg_mileage_correction_before_insert ON vehicle_mileage_correction"
    )
    op.execute("DROP FUNCTION IF EXISTS append_only_guard()")
    op.execute("DROP FUNCTION IF EXISTS mileage_correction_after_insert()")
    op.execute("DROP FUNCTION IF EXISTS mileage_correction_before_insert()")
    op.execute(VEHICLE_GUARD_V1)
    for table in UPDATED_AT_TABLES:
        op.execute(f"DROP TRIGGER IF EXISTS trg_set_updated_at ON {table}")
    op.execute("DROP FUNCTION IF EXISTS set_updated_at()")

    op.drop_index(
        op.f("ix_vehicle_mileage_correction_corrected_by_user_id"),
        table_name="vehicle_mileage_correction",
    )
    op.drop_index(
        op.f("ix_vehicle_mileage_correction_vehicle_id"), table_name="vehicle_mileage_correction"
    )
    op.drop_table("vehicle_mileage_correction")

    op.add_column("app_user", sa.Column("pd_consent_at", sa.DateTime(timezone=True)))
    op.add_column("app_user", sa.Column("pd_policy_version", sa.String(length=20)))
    # В старую схему возвращается только действующее согласие (история теряется).
    op.execute(
        "UPDATE app_user u SET pd_consent_at = c.given_at, pd_policy_version = c.policy_version "
        "FROM pd_consent c WHERE c.user_id = u.id AND c.withdrawn_at IS NULL"
    )
    op.create_check_constraint(
        op.f("ck_app_user_pd_consent_pair"),
        "app_user",
        "(pd_consent_at IS NULL) = (pd_policy_version IS NULL)",
    )
    op.drop_index("ix_pd_consent_withdrawn_at", table_name="pd_consent")
    op.drop_index("uq_pd_consent_active", table_name="pd_consent")
    op.drop_index(op.f("ix_pd_consent_user_id"), table_name="pd_consent")
    op.drop_table("pd_consent")
