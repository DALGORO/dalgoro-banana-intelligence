"""Servicio transaccional del ciclo de vida de campañas técnicas DBI."""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy.orm import Session

from app.dbi.campaigns.contracts import (
    DBICampaignAnalysisType,
    DBICampaignConflict,
    DBICampaignCreate,
    DBICampaignSnapshot,
    DBICampaignStatus,
    DBICampaignUnavailable,
    require_campaign_transition,
)
from app.dbi.campaigns.reader import campaign_snapshot
from app.dbi.campaigns.repository import DBICampaignRepository


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class DBICampaignService:
    """Crea y avanza campañas sin apropiarse del commit/rollback HTTP."""

    def __init__(self, session: Session) -> None:
        self._repository = DBICampaignRepository(session)

    def create_campaign(
        self,
        *,
        tenant_ref: str,
        organization_ref: str,
        farm_id: UUID,
        plot_id: UUID,
        request: DBICampaignCreate,
    ) -> tuple[DBICampaignSnapshot, bool]:
        if request.analysis_type is not DBICampaignAnalysisType.DENSITY:
            raise DBICampaignUnavailable(
                "El contrato multispectral está reservado; su ciencia aún no está habilitada."
            )
        if not self._repository.scope_exists(
            organization_ref=organization_ref,
            farm_id=farm_id,
            plot_id=plot_id,
        ):
            raise DBICampaignUnavailable("El ámbito de campaña no está disponible.")
        row, created = self._repository.persist_campaign(
            tenant_ref=tenant_ref,
            organization_ref=organization_ref,
            farm_id=farm_id,
            plot_id=plot_id,
            request=request,
        )
        return campaign_snapshot(row), created

    def link_source_job(
        self,
        *,
        campaign_id: UUID,
        tenant_ref: str,
        organization_ref: str,
        farm_id: UUID,
        plot_id: UUID,
        source_job_id: UUID,
    ) -> DBICampaignSnapshot:
        """Vincula el job científico fuente sin permitir reuso divergente."""

        row = self._repository.get_campaign_for_update(
            campaign_id=campaign_id,
            tenant_ref=tenant_ref,
            organization_ref=organization_ref,
            farm_id=farm_id,
            plot_id=plot_id,
        )
        if row is None:
            raise DBICampaignUnavailable("Campaña DBI no disponible.")
        if row.source_job_id is not None and row.source_job_id != source_job_id:
            raise DBICampaignConflict(
                "La campaña ya está vinculada a un job científico diferente."
            )
        if row.source_job_id is None:
            row.source_job_id = source_job_id
            row.updated_at = utc_now()
            self._repository.flush()
        return campaign_snapshot(row)

    def transition_campaign(
        self,
        *,
        campaign_id: UUID,
        tenant_ref: str,
        organization_ref: str,
        farm_id: UUID,
        plot_id: UUID,
        target_status: DBICampaignStatus,
        occurred_at: datetime | None = None,
    ) -> DBICampaignSnapshot:
        row = self._repository.get_campaign_for_update(
            campaign_id=campaign_id,
            tenant_ref=tenant_ref,
            organization_ref=organization_ref,
            farm_id=farm_id,
            plot_id=plot_id,
        )
        if row is None:
            raise DBICampaignUnavailable("Campaña DBI no disponible.")

        current = DBICampaignStatus(row.status)
        require_campaign_transition(current, target_status)
        if target_status == current:
            return campaign_snapshot(row)

        when = (occurred_at or utc_now()).astimezone(timezone.utc)
        row.status = target_status.value
        row.updated_at = when

        if target_status is DBICampaignStatus.ANALYZED:
            row.processed_at = when
        elif (
            target_status is DBICampaignStatus.SAMPLING_READY
            and current is DBICampaignStatus.TECHNICAL_REVIEW
        ):
            row.reviewed_at = when
        elif target_status is DBICampaignStatus.FIELD_WORK:
            row.field_started_at = when
        elif target_status is DBICampaignStatus.FIELD_COMPLETED:
            row.field_completed_at = when
        elif target_status is DBICampaignStatus.APPROVED:
            row.approved_at = when
        elif target_status is DBICampaignStatus.PUBLISHED:
            row.published_at = when

        self._repository.flush()
        return campaign_snapshot(row)
