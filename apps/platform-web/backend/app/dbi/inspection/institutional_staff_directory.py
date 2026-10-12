"""Adaptador de SOLO LECTURA del padrón institucional DALGORO.

La fuente es global, independiente de membresías y administradores de
clientes. Sin cargo activo o sin un único administrador, StaffWorkflow
niega la operación. No provisiona credenciales ni hace commit.
"""
from __future__ import annotations

from collections.abc import Sequence
from uuid import UUID

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.dbi.inspection.staff_workflow import (
    DBIInspectionStaffAssignment,
    DBIInspectionStaffRole,
)
from app.dbi.authorization import DBIAccessDenied
from app.dbi.models.inspection_staff import (
    DBIInspectionInstitutionalStaffRoleRecord,
)


STAFF_APPROVAL_LOCK_KEY = 451235456312  # must match Alembic rev 29


class DBIInspectionInstitutionalStaffDirectory:
    """Consultar autoridad institucional desde la misma Session DBI.

    Instanciar EXCLUSIVAMENTE en el servidor. El rol DBI runtime debe
    disponer sólo de SELECT; altas/revocaciones quedan fuera de la API.
    """

    def __init__(self, session: Session) -> None:
        if not isinstance(session, Session):
            raise TypeError("Se requiere sesión DBI para cargos institucionales.")
        self._session = session

    def acquire_approval_snapshot(self) -> None:
        """Acquire READ-only shared xact guard. Never use stale MVCC snapshots.

        A concurrent revocation/appointment takes the exclusive guard in the
        PostgreSQL BEFORE trigger. The app holds this guard until COMMIT or
        ROLLBACK with the subsequent INSPECT events in the same Session.
        Non-blocking acquisition denies instead of waiting indefinitely.
        """
        isolation = self._session.execute(
            text("SELECT current_setting('transaction_isolation')")
        ).scalar_one()
        if isolation != "read committed":
            raise DBIAccessDenied()
        acquired = self._session.execute(
            text("SELECT pg_try_advisory_xact_lock_shared(:key)"),
            {"key": STAFF_APPROVAL_LOCK_KEY},
        ).scalar_one()
        if acquired is not True:
            raise DBIAccessDenied()

    def list_active_administrators(self) -> Sequence[UUID]:
        # La UNIQUE persistida del marcador global evita dos administradores
        # aun ante altas simultáneas. Cero => StaffWorkflow fail closed.
        return tuple(self._session.execute(
            select(DBIInspectionInstitutionalStaffRoleRecord.principal_id).where(
                DBIInspectionInstitutionalStaffRoleRecord.role
                == DBIInspectionStaffRole.ADMINISTRATOR.value,
                DBIInspectionInstitutionalStaffRoleRecord.status == "active",
            )
        ).scalars().all())

    def list_assignments(
        self, *, principal_id: UUID, tenant_ref: str, organization_ref: str,
    ) -> Sequence[DBIInspectionStaffAssignment]:
        # Ambos cargos son GLOBALES DALGORO; scope DBI sigue validándose
        # por DBIAdminActorResolver y require_plot ANTES de leer aquí.
        if (
            not isinstance(principal_id, UUID)
            or not isinstance(tenant_ref, str)
            or not isinstance(organization_ref, str)
            or not tenant_ref.strip()
            or not organization_ref.strip()
        ):
            return ()
        rows = self._session.execute(
            select(DBIInspectionInstitutionalStaffRoleRecord).where(
                DBIInspectionInstitutionalStaffRoleRecord.principal_id == principal_id,
                DBIInspectionInstitutionalStaffRoleRecord.status == "active",
            )
        ).scalars().all()
        return tuple(
            DBIInspectionStaffAssignment(
                principal_id=row.principal_id,
                tenant_ref=tenant_ref,
                organization_ref=organization_ref,
                role=DBIInspectionStaffRole(row.role),
                status=row.status,
            )
            for row in rows
        )
