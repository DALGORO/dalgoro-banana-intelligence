"""Preparación de lectura cliente INSPECT: sólo evidencia validada y autorizada institucionalmente.

NO hay endpoint FastAPI ni publicación habilitada. El controlador futuro deberá
resolver READ scoped del servidor y exponer exclusivamente el DTO mínimo.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.dbi.authorization import (
    DBIAccessContext, DBIAuthorizationPolicy, DBIPermission,
)
from app.dbi.inspection.campaign_approval_service import (
    DBIInspectionCampaignApprovalService,
)
from app.dbi.inspection.contracts import DBIFieldObservationPayload
from app.dbi.inspection.dual_approval import DBIInspectionApprovalConflict
from app.dbi.inspection.repository import sha256_text
from app.dbi.models.agriculture import Campaign
from app.dbi.models.inspection import DBIFieldObservationVersionRecord
from app.dbi.models.inspection_campaign import DBIInspectionCampaignLinkRecord


class DBIInspectionPublishedUnavailable(LookupError):
    """La evidencia no es publicable o no pertenece a la selección autorizada."""


@dataclass(frozen=True, slots=True)
class DBIApprovedInspectionSummary:
    """Proyección mínima: no expone nombre del técnico, fotos, GPS ni notas."""

    campaign_id: UUID
    observation_id: UUID
    version_id: UUID
    observed_at: datetime
    sampling_point_id: UUID | None
    up_id: UUID | None
    foure_state: str
    foure_value: int | None
    yls_state: str
    yls_value: int | None
    functional_leaves_state: str
    functional_leaves_value: int | None


class DBIInspectionPublishedReadService:
    """Evaluación fail-closed del vínculo Campaign–INSPECT por identidad exacta.

    No hace commit ni consultas externas. Debe utilizarse desde una futura ruta
    aprobada, NO como autorización para usar GET de versiones privadas legacy.
    """

    def __init__(self, session: Session) -> None:
        if not isinstance(session, Session):
            raise TypeError("La lectura INSPECT requiere una Session explícita.")
        self._session = session

    def get_approved(
        self,
        context: DBIAccessContext,
        *,
        organization_ref: str,
        farm_id: UUID,
        plot_id: UUID,
        campaign_id: UUID,
        observation_id: UUID,
    ) -> DBIApprovedInspectionSummary:
        # Una cuenta READ no puede enumerar ámbitos ajenos.
        DBIAuthorizationPolicy.require_plot(
            context,
            tenant_ref=context.tenant_ref,
            organization_ref=organization_ref,
            farm_id=farm_id,
            plot_id=plot_id,
            permission=DBIPermission.READ,
        )

        campaign = self._session.execute(
            select(Campaign).where(
                Campaign.id == campaign_id,
                Campaign.tenant_ref == context.tenant_ref,
                Campaign.organization_ref == organization_ref,
                Campaign.farm_id == farm_id,
                Campaign.plot_id == plot_id,
                Campaign.analysis_type == "multispectral",
                Campaign.status == "PUBLISHED",
                Campaign.captured_at.is_not(None),
            )
        ).scalar_one_or_none()
        if campaign is None:
            raise DBIInspectionPublishedUnavailable()

        link = self._session.execute(
            select(DBIInspectionCampaignLinkRecord).where(
                DBIInspectionCampaignLinkRecord.campaign_id == campaign_id,
                DBIInspectionCampaignLinkRecord.observation_id == observation_id,
                DBIInspectionCampaignLinkRecord.tenant_ref == context.tenant_ref,
                DBIInspectionCampaignLinkRecord.organization_ref == organization_ref,
                DBIInspectionCampaignLinkRecord.farm_id == farm_id,
                DBIInspectionCampaignLinkRecord.plot_id == plot_id,
                DBIInspectionCampaignLinkRecord.campaign_analysis_type == "multispectral",
            )
        ).scalar_one_or_none()
        if link is None:
            raise DBIInspectionPublishedUnavailable()

        # Una nueva corrección vuelve ineligible la versión firmada anterior.
        latest = self._session.execute(
            select(DBIFieldObservationVersionRecord).where(
                DBIFieldObservationVersionRecord.observation_id == observation_id
            ).order_by(
                DBIFieldObservationVersionRecord.version.desc()
            ).limit(1)
        ).scalar_one_or_none()
        if (
            latest is None
            or latest.id != link.observation_version_id
            or latest.observation_id != observation_id
            or latest.evidence_kind != "observed"
        ):
            raise DBIInspectionPublishedUnavailable()

        approval = DBIInspectionCampaignApprovalService(self._session)
        try:
            state = approval._state(link)
        except DBIInspectionApprovalConflict as error:
            raise DBIInspectionPublishedUnavailable() from error
        if state.stage not in {"dual_approved", "self_approved"}:
            raise DBIInspectionPublishedUnavailable()
        if not state.eligible_for_client_read(
            current_version_id=latest.id,
            campaign_id=campaign_id,
            campaign_link_verified=approval._verified_scientific_chain(link),
        ):
            raise DBIInspectionPublishedUnavailable()

        # SHA + esquema + proyección: nunca devolver directamente payload_json.
        if sha256_text(latest.payload_json) != latest.payload_sha256:
            raise DBIInspectionPublishedUnavailable()
        try:
            payload = DBIFieldObservationPayload.model_validate_json(
                latest.payload_json
            )
        except (ValueError, TypeError) as error:
            raise DBIInspectionPublishedUnavailable() from error
        if (
            payload.tenant_ref != context.tenant_ref
            or payload.organization_ref != organization_ref
            or payload.farm_id != farm_id
            or payload.plot_id != plot_id
            or payload.evidence_kind != "observed"
            or payload.observed_at != latest.observed_at
            or payload.up_id != latest.up_id
            or payload.sampling_point_id != latest.sampling_point_id
        ):
            raise DBIInspectionPublishedUnavailable()

        return DBIApprovedInspectionSummary(
            campaign_id=campaign_id,
            observation_id=observation_id,
            version_id=latest.id,
            observed_at=payload.observed_at,
            sampling_point_id=payload.sampling_point_id,
            up_id=payload.up_id,
            foure_state=payload.core.foure.state,
            foure_value=payload.core.foure.value,
            yls_state=payload.core.yls.state,
            yls_value=payload.core.yls.value,
            functional_leaves_state=payload.core.functional_leaves.state,
            functional_leaves_value=payload.core.functional_leaves.value,
        )
