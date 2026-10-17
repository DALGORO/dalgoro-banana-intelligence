"""Autorización de publicación final DBI exclusivamente institucional DALGORO.

Los permisos de la membresía de un cliente no son acreditación de personal.
Comparte el guard transaccional de revocación de roles institucionales (rev 29).
El rol institucional y la membresía se comprueban en la misma transacción que
la transición APPROVED -> PUBLISHED.
"""
from __future__ import annotations

from uuid import UUID

from sqlalchemy.orm import Session

from app.dbi.admin_actor import DBIAdminActorRepository, DBIAdminActorResolver
from app.dbi.admin_policy import DBIAdminConflict
from app.dbi.authorization import (
    DBIAccessContext, DBIAccessDenied, DBIAuthorizationPolicy, DBIPermission,
)
from app.dbi.inspection.institutional_staff_directory import (
    DBIInspectionInstitutionalStaffDirectory,
)
from app.dbi.inspection.staff_workflow import DBIInspectionStaffRole


def require_institutional_campaign_publisher(
    session: Session, context: DBIAccessContext, *,
    organization_ref: str, farm_id: UUID, plot_id: UUID,
) -> None:
    """Fail closed. CALLER must commit/rollback in this same Session."""
    DBIAuthorizationPolicy.require_plot(
        context,
        tenant_ref=context.tenant_ref, organization_ref=organization_ref,
        farm_id=farm_id, plot_id=plot_id, permission=DBIPermission.MANAGE,
    )
    directory = DBIInspectionInstitutionalStaffDirectory(session)
    try:
        directory.acquire_approval_snapshot()
        principal_id = UUID(context.principal_ref)
        state = DBIAdminActorResolver(DBIAdminActorRepository(session)).resolve(
            context=context,
        )
        administrators = tuple(directory.list_active_administrators())
        assignments = tuple(directory.list_assignments(
            principal_id=principal_id,
            tenant_ref=context.tenant_ref,
            organization_ref=organization_ref,
        ))
        if (
            state.principal_id != principal_id
            or len(administrators) != 1
            or administrators[0] != principal_id
            or sum(
                role.principal_id == principal_id
                and role.role is DBIInspectionStaffRole.ADMINISTRATOR
                and role.status == "active"
                for role in assignments
            ) != 1
        ):
            raise DBIAccessDenied()
    except (DBIAdminConflict, TypeError, ValueError, AttributeError) as error:
        raise DBIAccessDenied() from error
