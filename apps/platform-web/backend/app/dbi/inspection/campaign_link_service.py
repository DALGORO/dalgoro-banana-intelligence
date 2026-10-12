"""Asociación explícita y scoped entre una versión INSPECT y una Campaign MULTI.

No publica datos, no genera firmas ni infiere coincidencias por fecha/GPS.
No ejecuta commit/rollback: el llamador posee la transacción.
"""
from __future__ import annotations

from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.dbi.authorization import (
    DBIAccessContext, DBIAuthorizationPolicy, DBIPermission,
)
from app.dbi.inspection.repository import DBIInspectionConflict
from app.dbi.models.agriculture import Campaign
from app.dbi.models.inspection import (
    DBIFieldObservationRecord, DBIFieldObservationVersionRecord,
)
from app.dbi.models.inspection_campaign import DBIInspectionCampaignLinkRecord


class DBIInspectionCampaignLinkUnavailable(LookupError):
    """Identidad de Campaign u observación no disponible en el scope."""


class DBIInspectionCampaignLinkService:
    """Propone vínculos trazables, aún NO verificados para publicación/ML."""

    def __init__(self, session: Session) -> None:
        if not isinstance(session, Session):
            raise DBIInspectionConflict("session debe ser Session.")
        self._session = session

    @staticmethod
    def _require_write(
        context: DBIAccessContext, *,
        tenant_ref: str, organization_ref: str, farm_id: UUID, plot_id: UUID,
    ) -> None:
        DBIAuthorizationPolicy.require_plot(
            context,
            tenant_ref=tenant_ref,
            organization_ref=organization_ref,
            farm_id=farm_id,
            plot_id=plot_id,
            permission=DBIPermission.WRITE,
        )

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
    ) -> tuple[DBIInspectionCampaignLinkRecord, bool]:
        """Registra vínculo propuesto solo para versión VIGENTE.

        La observación se bloquea FOR UPDATE: el flujo de correcciones usa
        el mismo candado y no puede introducir una nueva versión a mitad
        de la comprobación. La clave UNIQUE en PG protege de duplicados.
        """
        self._require_write(
            context, tenant_ref=tenant_ref, organization_ref=organization_ref,
            farm_id=farm_id, plot_id=plot_id,
        )

        campaign = self._session.execute(
            select(Campaign)
            .where(
                Campaign.id == campaign_id,
                Campaign.tenant_ref == tenant_ref,
                Campaign.organization_ref == organization_ref,
                Campaign.farm_id == farm_id,
                Campaign.plot_id == plot_id,
                Campaign.analysis_type == "multispectral",
                Campaign.captured_at.is_not(None),
            )
        ).scalar_one_or_none()
        if campaign is None:
            raise DBIInspectionCampaignLinkUnavailable()

        observation = self._session.execute(
            select(DBIFieldObservationRecord)
            .where(
                DBIFieldObservationRecord.id == observation_id,
                DBIFieldObservationRecord.tenant_ref == tenant_ref,
                DBIFieldObservationRecord.organization_ref == organization_ref,
                DBIFieldObservationRecord.farm_id == farm_id,
                DBIFieldObservationRecord.plot_id == plot_id,
            )
            .with_for_update()
        ).scalar_one_or_none()
        if observation is None:
            raise DBIInspectionCampaignLinkUnavailable()

        latest = self._session.execute(
            select(DBIFieldObservationVersionRecord)
            .where(
                DBIFieldObservationVersionRecord.observation_id == observation.id,
            )
            .order_by(DBIFieldObservationVersionRecord.version.desc())
            .limit(1)
        ).scalar_one_or_none()
        if (
            latest is None
            or latest.id != observation_version_id
            or latest.evidence_kind != "observed"
        ):
            raise DBIInspectionConflict(
                "La versión INSPECT debe ser la última observada y del mismo lote."
            )

        linked = self._session.execute(
            select(DBIInspectionCampaignLinkRecord)
            .where(
                DBIInspectionCampaignLinkRecord.observation_version_id
                == observation_version_id,
            )
            .with_for_update()
        ).scalar_one_or_none()
        if linked is not None:
            if (
                linked.tenant_ref != tenant_ref
                or linked.organization_ref != organization_ref
                or linked.farm_id != farm_id
                or linked.plot_id != plot_id
                or linked.campaign_id != campaign.id
                or linked.observation_id != observation.id
                or linked.observation_version_id != latest.id
            ):
                raise DBIInspectionConflict(
                    "Esta versión INSPECT ya tiene otra asociación Campaign."
                )
            return linked, False

        record = DBIInspectionCampaignLinkRecord(
            id=uuid4(),
            tenant_ref=tenant_ref,
            organization_ref=organization_ref,
            farm_id=farm_id,
            plot_id=plot_id,
            campaign_id=campaign.id,
            campaign_analysis_type="multispectral",
            observation_id=observation.id,
            observation_version_id=latest.id,
            linked_by_ref=context.principal_ref,
        )
        self._session.add(record)
        self._session.flush()
        return record, True
