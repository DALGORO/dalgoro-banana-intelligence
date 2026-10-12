"""Padrón institucional DALGORO append-only auditado, SIN cuentas iniciales.

Revision ID: dbi_0028_institutional_staff
Revises: dbi_0027_inspect_dual_sign

No abre endpoints ni otorga escritura al rol API: alta/revocación únicamente
por el custodio institucional fuera de la aplicación y bajo revisión.
"""
from __future__ import annotations

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "dbi_0028_institutional_staff"
down_revision: str | None = "dbi_0027_inspect_dual_sign"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "dbi_inspect_staff_roles",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("principal_id", sa.Uuid(), nullable=False),
        sa.Column("role", sa.String(length=16), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False,
                  server_default="active"),
        # UNIQUE global (no por tenant): varios técnicos NULL, un admin 1.
        sa.Column(
            "active_administrator_slot", sa.Integer(),
            sa.Computed(
                "CASE WHEN role = 'administrator' AND status = 'active' "
                "THEN 1 ELSE NULL END",
                persisted=True,
            ),
            nullable=True,
        ),
        sa.Column("accredited_by_ref", sa.String(length=128), nullable=False),
        sa.Column("accredited_at", sa.DateTime(timezone=True),
                  server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.Column("revoked_by_ref", sa.String(length=128)),
        sa.Column("revoked_at", sa.DateTime(timezone=True)),
        sa.Column("revocation_reason", sa.String(length=512)),
        sa.PrimaryKeyConstraint("id", name="pk_dbi_inspect_staff_roles"),
        sa.ForeignKeyConstraint(
            ["principal_id"], ["dbi_principals.id"],
            name="fk_dbi_inspect_staff_principal", ondelete="RESTRICT",
        ),
        sa.UniqueConstraint(
            "principal_id", "role", name="uq_dbi_inspect_staff_principal_role",
        ),
        sa.UniqueConstraint(
            "active_administrator_slot", name="uq_dbi_inspect_one_active_admin",
        ),
        sa.CheckConstraint(
            "role IN ('technician', 'administrator')",
            name="ck_dbi_inspect_staff_role",
        ),
        sa.CheckConstraint(
            "status IN ('active', 'revoked')",
            name="ck_dbi_inspect_staff_status",
        ),
        sa.CheckConstraint(
            "(status = 'active' AND revoked_by_ref IS NULL AND revoked_at IS NULL "
            "AND revocation_reason IS NULL) OR "
            "(status = 'revoked' AND revoked_by_ref IS NOT NULL "
            "AND revoked_at IS NOT NULL AND revoked_at >= accredited_at "
            "AND revocation_reason IS NOT NULL)",
            name="ck_dbi_inspect_staff_revocation",
        ),
        sa.CheckConstraint(
            "length(accredited_by_ref) BETWEEN 1 AND 128 "
            "AND btrim(accredited_by_ref) = accredited_by_ref "
            "AND accredited_by_ref NOT LIKE '%*%' "
            "AND (revoked_by_ref IS NULL OR "
            "(length(revoked_by_ref) BETWEEN 1 AND 128 "
            "AND btrim(revoked_by_ref) = revoked_by_ref "
            "AND revoked_by_ref NOT LIKE '%*%')) "
            "AND (revocation_reason IS NULL OR "
            "(length(revocation_reason) BETWEEN 1 AND 512 "
            "AND btrim(revocation_reason) = revocation_reason))",
            name="ck_dbi_inspect_staff_canonical_audit",
        ),
    )
    op.create_index(
        "ix_dbi_inspect_staff_roles_principal",
        "dbi_inspect_staff_roles", ["principal_id"],
    )

    op.create_table(
        "dbi_inspect_staff_audit_events",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("role_id", sa.Uuid(), nullable=False),
        sa.Column("event_kind", sa.String(length=16), nullable=False),
        sa.Column("actor_ref", sa.String(length=128), nullable=False),
        sa.Column("recorded_at", sa.DateTime(timezone=True),
                  server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_dbi_inspect_staff_audit_events"),
        sa.ForeignKeyConstraint(
            ["role_id"], ["dbi_inspect_staff_roles.id"],
            name="fk_dbi_inspect_staff_audit_role", ondelete="RESTRICT",
        ),
        sa.UniqueConstraint(
            "role_id", "event_kind", name="uq_dbi_inspect_staff_audit_step",
        ),
        sa.CheckConstraint(
            "event_kind IN ('accredited', 'revoked')",
            name="ck_dbi_inspect_staff_audit_kind",
        ),
    )
    op.create_index(
        "ix_dbi_inspect_staff_audit_role",
        "dbi_inspect_staff_audit_events", ["role_id"],
    )

    # No insertar usuarios reales ni otorgar INSERT/UPDATE/DELETE a la API.
    # El trigger registra automáticamente cada alta/revocación en una tabla
    # separada, rechaza reactivación, mutación de identidad y borrado.
    op.execute(sa.text("""
        CREATE FUNCTION dbi.dbi_inspect_staff_transition_audit()
        RETURNS trigger LANGUAGE plpgsql AS $body$
        BEGIN
            IF TG_OP = 'DELETE' THEN
                RAISE EXCEPTION 'Los cargos DALGORO no se pueden borrar';
            END IF;

            IF TG_OP = 'INSERT' THEN
                IF NEW.status <> 'active' THEN
                    RAISE EXCEPTION 'Toda acreditación inicia activa';
                END IF;
                INSERT INTO dbi.dbi_inspect_staff_audit_events
                    (id, role_id, event_kind, actor_ref, recorded_at)
                VALUES
                    (gen_random_uuid(), NEW.id, 'accredited',
                     NEW.accredited_by_ref, CURRENT_TIMESTAMP);
            ELSIF TG_OP = 'UPDATE' THEN
                IF OLD.status <> 'active' OR NEW.status <> 'revoked'
                    OR NEW.id IS DISTINCT FROM OLD.id
                    OR NEW.principal_id IS DISTINCT FROM OLD.principal_id
                    OR NEW.role IS DISTINCT FROM OLD.role
                    OR NEW.accredited_by_ref IS DISTINCT FROM OLD.accredited_by_ref
                    OR NEW.accredited_at IS DISTINCT FROM OLD.accredited_at
                    OR NEW.revoked_by_ref IS NULL
                    OR NEW.revoked_at IS NULL
                    OR NEW.revocation_reason IS NULL
                THEN
                    RAISE EXCEPTION 'Sólo se admite revocación auditada';
                END IF;
                INSERT INTO dbi.dbi_inspect_staff_audit_events
                    (id, role_id, event_kind, actor_ref, recorded_at)
                VALUES
                    (gen_random_uuid(), NEW.id, 'revoked',
                     NEW.revoked_by_ref, CURRENT_TIMESTAMP);
            END IF;
            RETURN NEW;
        END;
        $body$
    """))
    op.execute(sa.text("""
        CREATE TRIGGER dbi_inspect_staff_audit_transition
        AFTER INSERT OR UPDATE OR DELETE ON dbi_inspect_staff_roles
        FOR EACH ROW EXECUTE FUNCTION dbi.dbi_inspect_staff_transition_audit()
    """))

    op.execute(sa.text("""
        CREATE FUNCTION dbi.dbi_inspect_staff_audit_immutable()
        RETURNS trigger LANGUAGE plpgsql AS $body$
        BEGIN
            RAISE EXCEPTION 'Libro de acreditaciones DALGORO es inmutable';
        END;
        $body$
    """))
    op.execute(sa.text("""
        CREATE TRIGGER dbi_inspect_staff_audit_immutable
        BEFORE UPDATE OR DELETE ON dbi_inspect_staff_audit_events
        FOR EACH ROW EXECUTE FUNCTION dbi.dbi_inspect_staff_audit_immutable()
    """))


def downgrade() -> None:
    # Sólo para entornos desechables o rollback expresamente autorizado.
    op.execute(sa.text(
        "DROP TRIGGER IF EXISTS dbi_inspect_staff_audit_immutable "
        "ON dbi_inspect_staff_audit_events"
    ))
    op.execute(sa.text(
        "DROP FUNCTION IF EXISTS dbi.dbi_inspect_staff_audit_immutable()"
    ))
    op.execute(sa.text(
        "DROP TRIGGER IF EXISTS dbi_inspect_staff_audit_transition "
        "ON dbi_inspect_staff_roles"
    ))
    op.execute(sa.text(
        "DROP FUNCTION IF EXISTS dbi.dbi_inspect_staff_transition_audit()"
    ))
    op.drop_table("dbi_inspect_staff_audit_events")
    op.drop_table("dbi_inspect_staff_roles")
