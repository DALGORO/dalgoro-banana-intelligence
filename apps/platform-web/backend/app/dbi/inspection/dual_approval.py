"""Contrato PURO INSPECT: firma única administrador-técnico o dos actores.

No se conecta a API ni base de datos en este hito: primero se prueba la política
fail-closed antes de diseñar la migración y los endpoints de aprobación.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime
from uuid import UUID

from app.dbi.authorization import (
    DBIAccessContext,
    DBIAuthorizationPolicy,
    DBIPermission,
)


class DBIInspectionApprovalConflict(ValueError):
    """La transición o identidad de la evidencia no es válida."""


def _canonical_actor(value: str) -> bool:
    return (
        isinstance(value, str)
        and 0 < len(value) <= 128
        and value == value.strip()
        and "*" not in value
        and all(ord(char) >= 32 and ord(char) != 127 for char in value)
    )


def _aware(value: datetime) -> bool:
    return isinstance(value, datetime) and value.tzinfo is not None and value.utcoffset() is not None


@dataclass(frozen=True, slots=True)
class DBIInspectionApprovalState:
    """Aprobaciones trazables sobre UNA versión y UNA Campaign exactas."""

    tenant_ref: str
    organization_ref: str
    farm_id: UUID
    plot_id: UUID
    campaign_id: UUID
    observation_id: UUID
    observation_version_id: UUID
    technical_by: str | None = None
    technical_at: datetime | None = None
    administrative_by: str | None = None
    administrative_at: datetime | None = None

    def __post_init__(self) -> None:
        if not _canonical_actor(self.tenant_ref) or not _canonical_actor(self.organization_ref):
            raise DBIInspectionApprovalConflict("Tenant y organización deben ser canónicos.")
        if not all(
            isinstance(value, UUID)
            for value in (
                self.farm_id, self.plot_id, self.campaign_id,
                self.observation_id, self.observation_version_id,
            )
        ):
            raise DBIInspectionApprovalConflict("Se requieren identidades UUID explícitas.")
        if (self.technical_by is None) != (self.technical_at is None):
            raise DBIInspectionApprovalConflict("Validación técnica incompleta.")
        if (self.administrative_by is None) != (self.administrative_at is None):
            raise DBIInspectionApprovalConflict("Autorización administrativa incompleta.")
        if self.technical_by is not None:
            if not _canonical_actor(self.technical_by) or not _aware(self.technical_at):
                raise DBIInspectionApprovalConflict("Firma técnica inválida.")
        if self.administrative_by is not None:
            if (
                self.technical_by is None
                or not _canonical_actor(self.administrative_by)
                or not _aware(self.administrative_at)
                or self.administrative_at < self.technical_at
            ):
                raise DBIInspectionApprovalConflict("Las aprobaciones deben ser ordenadas y válidas.")

    @property
    def stage(self) -> str:
        if self.administrative_by is not None:
            return (
                "self_approved"
                if self.administrative_by == self.technical_by
                else "dual_approved"
            )
        if self.technical_by is not None:
            return "technical_validated"
        return "pending"

    def _require_scoped(self, context: DBIAccessContext, permission: DBIPermission) -> None:
        DBIAuthorizationPolicy.require_plot(
            context,
            tenant_ref=self.tenant_ref,
            organization_ref=self.organization_ref,
            farm_id=self.farm_id,
            plot_id=self.plot_id,
            permission=permission,
        )

    def _require_latest(self, current_version_id: UUID) -> None:
        if current_version_id != self.observation_version_id:
            raise DBIInspectionApprovalConflict("Solo se autoriza la versión INSPECT vigente.")

    def validate_technical(
        self, context: DBIAccessContext, *, at: datetime, current_version_id: UUID
    ) -> "DBIInspectionApprovalState":
        """Requiere WRITE scoped, antes de la firma administrativa."""
        self._require_scoped(context, DBIPermission.WRITE)
        self._require_latest(current_version_id)
        if self.stage != "pending" or not _aware(at):
            raise DBIInspectionApprovalConflict("Validación técnica repetida o fecha inválida.")
        return replace(self, technical_by=context.principal_ref, technical_at=at)

    def approve_administrative(
        self,
        context: DBIAccessContext,
        *,
        at: datetime,
        current_version_id: UUID,
        campaign_link_verified: bool,
    ) -> "DBIInspectionApprovalState":
        """Exige APPROVE_AGRONOMIC + MANAGE scoped y otro principal.

        campaign_link_verified debe provenir de validación confiable del servidor,
        NUNCA de un campo booleano suministrado por el cliente.
        """
        self._require_scoped(context, DBIPermission.APPROVE_AGRONOMIC)
        self._require_scoped(context, DBIPermission.MANAGE)
        self._require_latest(current_version_id)
        if (
            self.stage != "technical_validated"
            or context.principal_ref == self.technical_by
            or not _aware(at)
            or at < self.technical_at
            or campaign_link_verified is not True
        ):
            raise DBIInspectionApprovalConflict(
                "Falta validación técnica independiente, Campaign verificada o fecha válida."
            )
        return replace(self, administrative_by=context.principal_ref, administrative_at=at)

    def approve_self_administrative(
        self,
        context: DBIAccessContext,
        *,
        at: datetime,
        current_version_id: UUID,
        campaign_link_verified: bool,
    ) -> "DBIInspectionApprovalState":
        """Una acción del administrador TAMBIÉN acreditado como técnico.

        Solo llamar tras validar ambos cargos desde un directorio institucional
        confiable del servidor. No aceptar esta decisión desde un payload HTTP.
        Si no hubo paso técnico, se crea simultáneamente en la misma transacción.
        """
        for permission in (
            DBIPermission.WRITE,
            DBIPermission.APPROVE_AGRONOMIC,
            DBIPermission.MANAGE,
        ):
            self._require_scoped(context, permission)
        self._require_latest(current_version_id)
        if (
            not _aware(at)
            or campaign_link_verified is not True
            or self.stage not in {"pending", "technical_validated"}
            or (
                self.stage == "technical_validated"
                and self.technical_by != context.principal_ref
            )
            or (
                self.technical_at is not None
                and at < self.technical_at
            )
        ):
            raise DBIInspectionApprovalConflict(
                "Aprobación propia sin acreditación o evidencia vigente."
            )
        return replace(
            self,
            technical_by=context.principal_ref,
            technical_at=self.technical_at or at,
            administrative_by=context.principal_ref,
            administrative_at=at,
        )

    def eligible_for_client_read(
        self,
        *,
        current_version_id: UUID,
        campaign_id: UUID,
        campaign_link_verified: bool,
    ) -> bool:
        """Fail-closed: esta evidencia NO es un guard API hasta integrarse."""
        return (
            self.stage in {"dual_approved", "self_approved"}
            and current_version_id == self.observation_version_id
            and campaign_id == self.campaign_id
            and campaign_link_verified is True
        )
