"""Asociación interna y explícita de INSPECT con Campaign MULTI.

No crea rutas HTTP ni publica versiones. No hace commit ni rollback:
la sesión del llamador determina la transacción y revierte ante fallos.
"""
from __future__ import annotations

from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.dbi.authorization import (
    DBIAccessContext,
    DBIAuthorizationPolicy,
    DBIPermission,
)
from app.dbi.models.agriculture import Campaign
from app.dbi.models.inspection import (
    DBIFieldObservationRecord,
    DBIFieldObservationVersionRecord,
)
from app.dbi.models.inspection_campaign import DBIInspectionCampaignLinkRecord


class DBIInspectionCampaignLinkConflict(ValueError):
    """Una asociación nueva no es segura, vigente o inequívoca."""


class DBIInspectionCampaignLinkService:
    """Vincula 1 versión observada con 1 Campaign; no afirma calidad científica."""

    def __init__(self, session: Session) -> None:
        if not isinstance(session, Session):
            raise TypeError("La vinculación INSPECT requiere Session.")
        self._session = session

    def link_current_version(
        self,
        context: DBIAccessContext,
        *,
        organization_ref: str,
        farm_id: UUID,
        plot_id: UUID,
        campaign_id: UUID,
        observation_id: UUID,
        observation_version_id: UUID,
    ) -> DBIInspectionCampaignLinkRecord:
        """WRITE+READ scoped, versión actual y Campaign MULTI exacta.

        Las validaciones clínicas, tiempo campo-vuelo, GPS, COPA_UP,
        identidad de técnico DALGORO y aprobación no están certificadas
        por esta función. No es un endpoint público ni un gate cliente.
        """
        for permission in (DBIPermission.READ, DBIPermission.WRITE):
            DBIAuthorizationPolicy.require_plot(
                context,
                tenant_ref=context.tenant_ref,
                organization_ref=organization_ref,
                farm_id=farm_id,
                plot_id=plot_id,
                permission=permission,
            )
        if not all(
            isinstance(value, UUID)
            for value in (farm_id, plot_id, campaign_id, observation_id, observation_version_id)
        ):
            raise DBIInspectionCampaignLinkConflict("Identidades UUID incompletas.")

        campaign = self._session.execute(
            select(Campaign).where(
                Campaign.id == campaign_id,
                Campaign.tenant_ref == context.tenant_ref,
                Campaign.organization_ref == organization_ref,
                Campaign.farm_id == farm_id,
                Campaign.plot_id == plot_id,
                Campaign.analysis_type == "multispectral",
                Campaign.captured_at.is_not(None),
            )
        ).scalar_one_or_none()
        if campaign is None or campaign.status not in {
            "SAMPLING_READY", "FIELD_WORK", "FIELD_COMPLETED",
            "APPROVED", "PUBLISHED",
        }:
            raise DBIInspectionCampaignLinkConflict(
                "La Campaign MULTI scoped no está habilitada para inspección."
            )

        # Serializar por identidad de INSPECT: su corrección usa el mismo
        # lock. Evita vincular una versión mientras otro técnico la corrige.
        observation = self._session.execute(
            select(DBIFieldObservationRecord)
            .where(
                DBIFieldObservationRecord.id == observation_id,
                DBIFieldObservationRecord.tenant_ref == context.tenant_ref,
                DBIFieldObservationRecord.organization_ref == organization_ref,
                DBIFieldObservationRecord.farm_id == farm_id,
                DBIFieldObservationRecord.plot_id == plot_id,
            )
            .with_for_update()
        ).scalar_one_or_none()
        if observation is None:
            raise DBIInspectionCampaignLinkConflict(
                "INSPECT no pertenece al ámbito autorizado."
            )

        latest = self._session.execute(
            select(DBIFieldObservationVersionRecord)
            .where(DBIFieldObservationVersionRecord.observation_id == observation_id)
            .order_by(DBIFieldObservationVersionRecord.version.desc())
            .limit(1)
        ).scalar_one_or_none()
        if (
            latest is None
            or latest.id != observation_version_id
            or latest.evidence_kind != "observed"
        ):
            raise DBIInspectionCampaignLinkConflict(
                "Solo se vincula la versión INSPECT observada y vigente."
            )

        existing = self._session.execute(
            select(DBIInspectionCampaignLinkRecord).where(
                DBIInspectionCampaignLinkRecord.observation_id == observation_id,
                DBIInspectionCampaignLinkRecord.tenant_ref == context.tenant_ref,
                DBIInspectionCampaignLinkRecord.organization_ref == organization_ref,
                DBIInspectionCampaignLinkRecord.farm_id == farm_id,
                DBIInspectionCampaignLinkRecord.plot_id == plot_id,
            )
        ).scalars().all()
        for previous in existing:
            if previous.campaign_id != campaign_id:
                raise DBIInspectionCampaignLinkConflict(
                    "No se reasigna una observación a otra Campaign automáticamente."
                )
            if previous.observation_version_id == observation_version_id:
                return previous  # Reintento idempotente exacto, sin segunda fila.

        link = DBIInspectionCampaignLinkRecord(
            id=uuid4(),
            tenant_ref=context.tenant_ref,
            organization_ref=organization_ref,
            farm_id=farm_id,
            plot_id=plot_id,
            campaign_id=campaign_id,
            campaign_analysis_type="multispectral",
            observation_id=observation_id,
            observation_version_id=observation_version_id,
            linked_by_ref=context.principal_ref,
        )
        self._session.add(link)
        self._session.flush()
        return link
