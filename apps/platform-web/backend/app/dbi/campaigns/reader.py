"""Lectura segura de campañas técnicas DBI."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy.orm import Session

from app.dbi.campaigns.contracts import (
    DBICampaignAnalysisType,
    DBICampaignSnapshot,
    DBICampaignStatus,
    DBICampaignUnavailable,
)
from app.dbi.campaigns.repository import DBICampaignRepository
from app.dbi.models import Campaign


def campaign_snapshot(row: Campaign) -> DBICampaignSnapshot:
    """Convierte una fila técnica persistida al contrato no sensible."""

    if (
        row.tenant_ref is None
        or row.organization_ref is None
        or row.plot_id is None
        or row.analysis_type is None
        or row.captured_at is None
    ):
        raise DBICampaignUnavailable("La campaña no pertenece al dominio técnico v2.")
    return DBICampaignSnapshot(
        campaign_id=row.id,
        tenant_ref=row.tenant_ref,
        organization_ref=row.organization_ref,
        farm_id=row.farm_id,
        plot_id=row.plot_id,
        analysis_type=DBICampaignAnalysisType(row.analysis_type),
        captured_at=row.captured_at,
        processed_at=row.processed_at,
        status=DBICampaignStatus(row.status),
        created_at=row.created_at,
        updated_at=row.updated_at,
        reviewed_at=row.reviewed_at,
        field_started_at=row.field_started_at,
        field_completed_at=row.field_completed_at,
        approved_at=row.approved_at,
        published_at=row.published_at,
        current_revision_id=row.current_revision_id,
        source_job_id=row.source_job_id,
    )


class DBICampaignReader:
    """Recupera una campaña solamente dentro de su scope completo."""

    def __init__(self, session: Session) -> None:
        self._repository = DBICampaignRepository(session)

    def read_campaign(
        self,
        *,
        campaign_id: UUID,
        tenant_ref: str,
        organization_ref: str,
        farm_id: UUID,
        plot_id: UUID,
    ) -> DBICampaignSnapshot:
        row = self._repository.get_campaign(
            campaign_id=campaign_id,
            tenant_ref=tenant_ref,
            organization_ref=organization_ref,
            farm_id=farm_id,
            plot_id=plot_id,
        )
        if row is None:
            raise DBICampaignUnavailable("Campaña DBI no disponible.")
        return campaign_snapshot(row)
