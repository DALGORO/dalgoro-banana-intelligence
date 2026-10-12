"""Frontera interna INSPECT: membresía DBI vigente + cargo DALGORO verificado.

Ninguna ruta HTTP utiliza este módulo aún. Una inscripción ordinaria DBI
(NO equivale a contrato laboral) nunca acredita cargo institucional.
La fuente externa de personal deberá ser aprovisionada y auditada por
separado antes de activar endpoints. Sin fuente, se deniega todo.
"""
from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol
from uuid import UUID

from sqlalchemy.orm import Session

from app.dbi.admin_actor import DBIAdminActorRepository, DBIAdminActorResolver
from app.dbi.admin_policy import DBIAdminConflict
from app.dbi.authorization import (
    DBIAccessContext, DBIAccessDenied, DBIAuthorizationPolicy, DBIPermission,
)
from app.dbi.inspection.campaign_approval_service import (
    DBIInspectionCampaignApprovalService,
)
from app.dbi.inspection.campaign_link_service import (
    DBIInspectionCampaignLinkService,
)


class DBIInspectionStaffRole(StrEnum):
    TECHNICIAN = "technician"
    ADMINISTRATOR = "administrator"


@dataclass(frozen=True, slots=True)
class DBIInspectionStaffAssignment:
    """Acreditación explícita desde un directorio institucional de DALGORO.

    No crear desde JWT, encabezados, formulario o permisos DBI generales.
    El adaptador futuro consultará registros restringidos y auditados.
    """

    principal_id: UUID
    tenant_ref: str
    organization_ref: str
    role: DBIInspectionStaffRole
    status: str


class DBIInspectionStaffDirectoryPort(Protocol):
    """Autoridad institucional independiente del permiso DBI del cliente."""

    def list_assignments(
        self, *, principal_id: UUID, tenant_ref: str, organization_ref: str,
    ) -> Sequence[DBIInspectionStaffAssignment]: ...


class DBIInspectionStaffWorkflow:
    """Única fachada prevista para futuras rutas de vínculo y firmas INSPECT.

    No hace commit; usa misma sesión DBI para releer identidad + operaciones.
    """

    def __init__(
        self,
        session: Session,
        *,
        staff_directory: DBIInspectionStaffDirectoryPort | None = None,
    ) -> None:
        if not isinstance(session, Session):
            raise TypeError("Se requiere una sesión DBI válida.")
        self._session = session
        self._staff_directory = staff_directory

    def _require_staff(
        self,
        context: DBIAccessContext,
        *,
        organization_ref: str,
        farm_id: UUID,
        plot_id: UUID,
        permission: DBIPermission,
        roles: frozenset[DBIInspectionStaffRole],
    ) -> None:
        if not isinstance(context, DBIAccessContext):
            raise DBIAccessDenied()
        # Antes de leer afiliación institucional, comprobar scope exacto.
        DBIAuthorizationPolicy.require_plot(
            context, tenant_ref=context.tenant_ref,
            organization_ref=organization_ref, farm_id=farm_id,
            plot_id=plot_id, permission=permission,
        )
        if self._staff_directory is None:
            raise DBIAccessDenied()

        try:
            principal_id = UUID(context.principal_ref)
            # Verifica desde DBI en esta transacción: principal/membresía
            # activos y TODOS los permisos/ámbitos idénticos al contexto.
            state = DBIAdminActorResolver(
                DBIAdminActorRepository(self._session)
            ).resolve(context=context)
            if state.principal_id != principal_id:
                raise DBIAccessDenied()
            assignments = tuple(self._staff_directory.list_assignments(
                principal_id=principal_id,
                tenant_ref=context.tenant_ref,
                organization_ref=organization_ref,
            ))
            # Exactamente una autorización: duplicados, roles simultáneos,
            # inactivos, tenant u organización cruzados fallan cerrados.
            if len(assignments) != 1:
                raise DBIAccessDenied()
            assignment = assignments[0]
            if (
                not isinstance(assignment, DBIInspectionStaffAssignment)
                or assignment.principal_id != principal_id
                or assignment.tenant_ref != context.tenant_ref
                or assignment.organization_ref != organization_ref
                or not isinstance(assignment.role, DBIInspectionStaffRole)
                or assignment.role not in roles
                or assignment.status != "active"
            ):
                raise DBIAccessDenied()
        except (DBIAdminConflict, TypeError, ValueError) as error:
            raise DBIAccessDenied() from error

    def propose_link(
        self,
        context: DBIAccessContext,
        *,
        tenant_ref: str,
        organization_ref: str,
        farm_id: UUID,
        plot_id: UUID,
        campaign_id: UUID,
        observation_id: UUID,
        observation_version_id: UUID,
    ):
        if not isinstance(context, DBIAccessContext) or tenant_ref != context.tenant_ref:
            raise DBIAccessDenied()
        self._require_staff(
            context, organization_ref=organization_ref,
            farm_id=farm_id, plot_id=plot_id, permission=DBIPermission.WRITE,
            roles=frozenset({
                DBIInspectionStaffRole.TECHNICIAN,
                DBIInspectionStaffRole.ADMINISTRATOR,
            }),
        )
        return DBIInspectionCampaignLinkService(self._session).propose_link(
            context, tenant_ref=tenant_ref, organization_ref=organization_ref,
            farm_id=farm_id, plot_id=plot_id,
            campaign_id=campaign_id, observation_id=observation_id,
            observation_version_id=observation_version_id,
        )

    def validate_technical(
        self,
        context: DBIAccessContext,
        *,
        organization_ref: str,
        farm_id: UUID,
        plot_id: UUID,
        link_id: UUID,
    ):
        self._require_staff(
            context, organization_ref=organization_ref,
            farm_id=farm_id, plot_id=plot_id, permission=DBIPermission.WRITE,
            roles=frozenset({DBIInspectionStaffRole.TECHNICIAN}),
        )
        return DBIInspectionCampaignApprovalService(
            self._session
        ).validate_technical(
            context, organization_ref=organization_ref,
            farm_id=farm_id, plot_id=plot_id, link_id=link_id,
        )

    def authorize_administrative(
        self,
        context: DBIAccessContext,
        *,
        organization_ref: str,
        farm_id: UUID,
        plot_id: UUID,
        link_id: UUID,
    ):
        # Se exigen AMBOS permisos, no sólo MANAGE.
        self._require_staff(
            context, organization_ref=organization_ref,
            farm_id=farm_id, plot_id=plot_id,
            permission=DBIPermission.APPROVE_AGRONOMIC,
            roles=frozenset({DBIInspectionStaffRole.ADMINISTRATOR}),
        )
        DBIAuthorizationPolicy.require_plot(
            context, tenant_ref=context.tenant_ref,
            organization_ref=organization_ref, farm_id=farm_id,
            plot_id=plot_id, permission=DBIPermission.MANAGE,
        )
        return DBIInspectionCampaignApprovalService(
            self._session
        ).authorize_administrative(
            context, organization_ref=organization_ref,
            farm_id=farm_id, plot_id=plot_id, link_id=link_id,
        )
