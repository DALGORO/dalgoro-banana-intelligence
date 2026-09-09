"""Adopción explícita de trabajos locales históricos de Density en Campaign DBI.

Este adaptador no ejecuta ni modifica el motor científico. Su única responsabilidad
es crear una identidad Campaign determinista para un job histórico ya finalizado,
vincular el job y llevar la Campaign hasta ANALYZED usando timestamps de
compatibilidad declarados explícitamente.
"""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID, uuid5

from sqlalchemy.orm import Session

from app.dbi.campaigns.contracts import (
    DBICampaignAnalysisType,
    DBICampaignCreate,
    DBICampaignSnapshot,
    DBICampaignStatus,
)
from app.dbi.campaigns.service import DBICampaignService


LEGACY_DENSITY_CAMPAIGN_NAMESPACE = UUID("59977a94-926a-4df0-bff9-fd73bb3dd451")
LEGACY_CAMPAIGN_ORIGIN = "legacy_import"
LEGACY_PROCESSED_AT_SOURCE = "legacy_job_updated_at_fallback_not_pipeline_completion_time"


def _utc(value: datetime, *, field_name: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} debe incluir zona horaria.")
    return value.astimezone(timezone.utc)


def legacy_density_campaign_id(source_job_id: UUID) -> UUID:
    """Deriva una Campaign estable para que los reintentos no creen duplicados."""

    return uuid5(
        LEGACY_DENSITY_CAMPAIGN_NAMESPACE,
        f"density-legacy-job:{source_job_id}",
    )


def adopt_historical_density_job_to_campaign(
    session: Session,
    *,
    tenant_ref: str,
    organization_ref: str,
    farm_id: UUID,
    plot_id: UUID,
    source_job_id: UUID,
    captured_at: datetime,
    processed_at: datetime,
) -> tuple[DBICampaignSnapshot, bool]:
    """Adopta un job terminado sin recalcular Density ni alterar sus resultados.

    ``captured_at`` y ``processed_at`` son valores de compatibilidad aportados por
    la capa local. El llamador debe conservar el origen/fallback de esos valores
    en la trazabilidad del job; esta función no los presenta como fechas de vuelo.
    """

    campaign_id = legacy_density_campaign_id(source_job_id)
    service = DBICampaignService(session)
    snapshot, created = service.create_campaign(
        tenant_ref=tenant_ref,
        organization_ref=organization_ref,
        farm_id=farm_id,
        plot_id=plot_id,
        request=DBICampaignCreate(
            campaign_id=campaign_id,
            analysis_type=DBICampaignAnalysisType.DENSITY,
            captured_at=_utc(captured_at, field_name="captured_at"),
        ),
    )
    snapshot = service.link_source_job(
        campaign_id=campaign_id,
        tenant_ref=tenant_ref,
        organization_ref=organization_ref,
        farm_id=farm_id,
        plot_id=plot_id,
        source_job_id=source_job_id,
    )

    if snapshot.status is DBICampaignStatus.DRAFT:
        snapshot = service.transition_campaign(
            campaign_id=campaign_id,
            tenant_ref=tenant_ref,
            organization_ref=organization_ref,
            farm_id=farm_id,
            plot_id=plot_id,
            target_status=DBICampaignStatus.PROCESSING,
            occurred_at=_utc(captured_at, field_name="captured_at"),
        )
    if snapshot.status is DBICampaignStatus.PROCESSING:
        snapshot = service.transition_campaign(
            campaign_id=campaign_id,
            tenant_ref=tenant_ref,
            organization_ref=organization_ref,
            farm_id=farm_id,
            plot_id=plot_id,
            target_status=DBICampaignStatus.ANALYZED,
            occurred_at=_utc(processed_at, field_name="processed_at"),
        )

    return snapshot, created
