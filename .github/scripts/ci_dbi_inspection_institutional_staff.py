"""Prueba REAL de cargos DALGORO en PostGIS desechable GitHub CI.

Admin global único, múltiples técnicos, auditoría automática, revocación,
consulta vía rol SELECT-only y cero cuentas precargadas en migración 28.
Nunca permitir ejecución contra staging/producción.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path
from uuid import UUID

import psycopg
from psycopg import sql
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import NullPool

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "apps" / "platform-web" / "backend"))

from app.dbi.inspection.institutional_staff_directory import (  # noqa: E402
    DBIInspectionInstitutionalStaffDirectory,
)
from app.dbi.inspection.staff_workflow import DBIInspectionStaffRole  # noqa: E402
from app.dbi.models.inspection_staff import (  # noqa: E402
    DBIInspectionInstitutionalStaffRoleRecord,
)

HOST = "127.0.0.1"
DB = "dbi_test"
ROLE = "dbi_ci_staff_reader"
ADMIN = UUID("01000000-0000-4000-8000-000000000229")
TECH2 = UUID("02000000-0000-4000-8000-000000000229")
FUTURE_ADMIN = UUID("03000000-0000-4000-8000-000000000229")
ADMIN_ROLE = UUID("04000000-0000-4000-8000-000000000229")
TECH_ROLE = UUID("05000000-0000-4000-8000-000000000229")
TECH2_ROLE = UUID("06000000-0000-4000-8000-000000000229")
FUTURE_ADMIN_ROLE = UUID("07000000-0000-4000-8000-000000000229")


def _guard() -> None:
    if (
        os.environ.get("GITHUB_ACTIONS") != "true"
        or os.environ.get("DBI_ENVIRONMENT") != "test"
        or os.environ.get("DBI_STAFF_RUN_INTEGRATION") != "1"
        or os.environ.get("DBI_DATABASE_URL")
        != f"postgresql+psycopg://{ROLE}@{HOST}:5432/{DB}"
    ):
        raise RuntimeError("Prohibido fuera de CI PostGIS efímero.")


def _admin():
    return psycopg.connect(
        host=HOST, dbname=DB, user="postgres",
        autocommit=True, connect_timeout=10,
    )


def _add_principal(cur, who: UUID):
    cur.execute(
        "INSERT INTO dbi.dbi_principals (id, legacy_identity_ref, status) "
        "VALUES (%s, %s, 'active')",
        (who, "ci-staff-" + str(who)),
    )


def _add_role(cur, role_id: UUID, principal: UUID, role: str):
    cur.execute(
        "INSERT INTO dbi.dbi_inspect_staff_roles "
        "(id, principal_id, role, status, accredited_by_ref) "
        "VALUES (%s, %s, %s, 'active', 'ci-institutional-issuer')",
        (role_id, principal, role),
    )


def _assert_denied(fn, errors):
    try:
        fn()
    except errors:
        return
    raise AssertionError("La base debía rechazar esta operación.")


def main() -> None:
    _guard()
    with _admin() as conn, conn.cursor() as cur:
        for principal in (ADMIN, TECH2, FUTURE_ADMIN):
            _add_principal(cur, principal)
        # No hay cuentas creadas automáticamente por la migración.
        cur.execute("SELECT count(*) FROM dbi.dbi_inspect_staff_roles")
        assert cur.fetchone()[0] == 0

        _add_role(cur, ADMIN_ROLE, ADMIN, "administrator")
        _add_role(cur, TECH_ROLE, ADMIN, "technician")
        _add_role(cur, TECH2_ROLE, TECH2, "technician")
        cur.execute(
            "SELECT event_kind, count(*) "
            "FROM dbi.dbi_inspect_staff_audit_events GROUP BY event_kind"
        )
        assert dict(cur.fetchall()) == {"accredited": 3}

        # Un segundo administrador global falla aunque tenga diferente tenant.
        _assert_denied(
            lambda: _add_role(cur, FUTURE_ADMIN_ROLE, FUTURE_ADMIN, "administrator"),
            (psycopg.errors.UniqueViolation,),
        )
        # psycopg autocommit=true: el comando fallido no invalida la conexión.
        cur.execute(
            "SELECT count(*) FROM dbi.dbi_inspect_staff_roles "
            "WHERE role = 'administrator' AND status = 'active'"
        )
        assert cur.fetchone()[0] == 1

        cur.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", (ROLE,))
        if cur.fetchone() is None:
            cur.execute(
                sql.SQL("CREATE ROLE {} LOGIN NOSUPERUSER NOCREATEDB "
                        "NOCREATEROLE NOREPLICATION NOBYPASSRLS")
                .format(sql.Identifier(ROLE))
            )
        cur.execute(
            sql.SQL("GRANT CONNECT ON DATABASE {} TO {}")
            .format(sql.Identifier(DB), sql.Identifier(ROLE))
        )
        cur.execute(
            sql.SQL("GRANT USAGE ON SCHEMA dbi TO {}").format(sql.Identifier(ROLE))
        )
        for table in ("dbi_inspect_staff_roles", "dbi_inspect_staff_audit_events"):
            cur.execute(
                sql.SQL("GRANT SELECT ON dbi.{} TO {}")
                .format(sql.Identifier(table), sql.Identifier(ROLE))
            )
            cur.execute(
                "SELECT has_table_privilege(%s, %s, 'SELECT'), "
                "has_table_privilege(%s, %s, 'INSERT'), "
                "has_table_privilege(%s, %s, 'UPDATE'), "
                "has_table_privilege(%s, %s, 'DELETE')",
                (ROLE, "dbi." + table, ROLE, "dbi." + table,
                 ROLE, "dbi." + table, ROLE, "dbi." + table),
            )
            assert cur.fetchone() == (True, False, False, False), table
        cur.execute(
            sql.SQL("ALTER ROLE {} SET search_path = dbi, public")
            .format(sql.Identifier(ROLE))
        )

    engine = create_engine(
        os.environ["DBI_DATABASE_URL"], poolclass=NullPool,
        future=True,
    )
    try:
        with Session(engine) as session:
            directory = DBIInspectionInstitutionalStaffDirectory(session)
            assert tuple(directory.list_active_administrators()) == (ADMIN,)
            person = directory.list_assignments(
                principal_id=ADMIN, tenant_ref="tenant-staff",
                organization_ref="org-staff",
            )
            assert {a.role for a in person} == {
                DBIInspectionStaffRole.ADMINISTRATOR,
                DBIInspectionStaffRole.TECHNICIAN,
            }
            assert all(a.principal_id == ADMIN for a in person)
            assert len(directory.list_assignments(
                principal_id=TECH2, tenant_ref="tenant-staff",
                organization_ref="org-staff",
            )) == 1
            assert not directory.list_assignments(
                principal_id=FUTURE_ADMIN, tenant_ref="tenant-staff",
                organization_ref="org-staff",
            )
            assert session.scalar(
                select(DBIInspectionInstitutionalStaffRoleRecord.id).where(
                    DBIInspectionInstitutionalStaffRoleRecord.principal_id == ADMIN,
                    DBIInspectionInstitutionalStaffRoleRecord.role == "administrator",
                )
            ) == ADMIN_ROLE

        # Revocación auditable: nunca DELETE, jamás reactivación.
        with _admin() as conn, conn.cursor() as cur:
            cur.execute(
                "UPDATE dbi.dbi_inspect_staff_roles "
                "SET status='revoked', revoked_by_ref='ci-institutional-issuer', "
                "revoked_at=CURRENT_TIMESTAMP, revocation_reason='ci-revocation' "
                "WHERE id=%s",
                (TECH2_ROLE,),
            )
            cur.execute(
                "SELECT event_kind, actor_ref "
                "FROM dbi.dbi_inspect_staff_audit_events "
                "WHERE role_id=%s ORDER BY recorded_at",
                (TECH2_ROLE,),
            )
            assert cur.fetchall() == [
                ("accredited", "ci-institutional-issuer"),
                ("revoked", "ci-institutional-issuer"),
            ]
            _assert_denied(
                lambda: cur.execute(
                    "UPDATE dbi.dbi_inspect_staff_roles SET status='active', "
                    "revoked_at=NULL, revoked_by_ref=NULL, revocation_reason=NULL "
                    "WHERE id=%s", (TECH2_ROLE,),
                ),
                (psycopg.errors.RaiseException,),
            )
            _assert_denied(
                lambda: cur.execute(
                    "DELETE FROM dbi.dbi_inspect_staff_roles WHERE id=%s",
                    (TECH2_ROLE,),
                ),
                (psycopg.errors.RaiseException, psycopg.errors.ForeignKeyViolation),
            )

        with Session(engine) as session:
            directory = DBIInspectionInstitutionalStaffDirectory(session)
            assert not directory.list_assignments(
                principal_id=TECH2, tenant_ref="tenant-staff",
                organization_ref="org-staff",
            )
            assert directory.list_active_administrators() == (ADMIN,)

        # Un relevo administrador es posible DESPUÉS de revocar al anterior.
        with _admin() as conn, conn.cursor() as cur:
            cur.execute(
                "UPDATE dbi.dbi_inspect_staff_roles "
                "SET status='revoked', revoked_by_ref='ci-institutional-issuer', "
                "revoked_at=CURRENT_TIMESTAMP, revocation_reason='ci-handover' "
                "WHERE id=%s", (ADMIN_ROLE,),
            )
        with Session(engine) as session:
            directory = DBIInspectionInstitutionalStaffDirectory(session)
            assert not directory.list_active_administrators()
            # El cargo técnico personal permanece si el admin se revoca.
            assert [a.role for a in directory.list_assignments(
                principal_id=ADMIN, tenant_ref="tenant-staff",
                organization_ref="org-staff",
            )] == [DBIInspectionStaffRole.TECHNICIAN]
        with _admin() as conn, conn.cursor() as cur:
            _add_role(cur, FUTURE_ADMIN_ROLE, FUTURE_ADMIN, "administrator")
        with Session(engine) as session:
            directory = DBIInspectionInstitutionalStaffDirectory(session)
            assert directory.list_active_administrators() == (FUTURE_ADMIN,)
    finally:
        engine.dispose()
    print("OK: padrón DALGORO real: 1 admin global, varios técnicos, auditoría, revocación, lectura SELECT-only.")


if __name__ == "__main__":
    main()
