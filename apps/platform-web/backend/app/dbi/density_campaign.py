"""Adaptador DBI entre el job local de Density y Campaign.

Este módulo vive fuera del motor científico. Solo registra identidad, alcance y
lifecycle alrededor de una ejecución ya preparada por el puente estable.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Callable
from uuid import UUID, uuid4

from sqlalchemy.orm import Session

from app.dbi.campaigns.contracts import (
    DBICampaignAnalysisType,
    DBICampaignCreate,
    DBICampaignStatus,
)
from app.dbi.campaigns.service import DBICampaignService

CAPTURED_AT_SOURCE_ASSET_CREATED_FALLBACK = (
    "orthophoto_asset_created_at_fallback_not_flight_capture_time"
)


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def link_density_job_to_campaign(
    session: Session,
    *,
    tenant_ref: str,
    organization_ref: str,
    farm_id: UUID,
    plot_id: UUID,
    source_job_id: UUID,
    orthophoto_asset_id: UUID,
    orthophoto_sha256: str,
    orthophoto_asset_created_at: datetime,
    target_density: float,
) -> dict[str, Any]:
    """Crea Campaign, enlaza el job y la deja PROCESSING antes del launch.

    El modelo de activos todavía no almacena la fecha real de captura del vuelo.
    Para no romper el flujo existente se usa ``asset.created_at`` como fallback
    explícito y se conserva su procedencia en job.json. No debe interpretarse
    como fecha de vuelo.
    """

    campaign_id = uuid4()
    captured_at = _utc(orthophoto_asset_created_at)
    service = DBICampaignService(session)
    service.create_campaign(
        tenant_ref=tenant_ref,
        organization_ref=organization_ref,
        farm_id=farm_id,
        plot_id=plot_id,
        request=DBICampaignCreate(
            campaign_id=campaign_id,
            analysis_type=DBICampaignAnalysisType.DENSITY,
            captured_at=captured_at,
        ),
    )
    service.link_source_job(
        campaign_id=campaign_id,
        tenant_ref=tenant_ref,
        organization_ref=organization_ref,
        farm_id=farm_id,
        plot_id=plot_id,
        source_job_id=source_job_id,
    )
    service.transition_campaign(
        campaign_id=campaign_id,
        tenant_ref=tenant_ref,
        organization_ref=organization_ref,
        farm_id=farm_id,
        plot_id=plot_id,
        target_status=DBICampaignStatus.PROCESSING,
    )
    return {
        "campaign_id": str(campaign_id),
        "tenant_ref": tenant_ref,
        "organization_ref": organization_ref,
        "target_density": float(target_density),
        "orthophoto_sha256": orthophoto_sha256,
        "campaign_captured_at": captured_at.isoformat(),
        "campaign_captured_at_source": CAPTURED_AT_SOURCE_ASSET_CREATED_FALLBACK,
        "campaign_sync_error": None,
        "orthophoto_asset_id": str(orthophoto_asset_id),
    }


def mark_density_campaign_analyzed(
    session_factory: Callable[[], Session],
    job: dict[str, Any],
    *,
    occurred_at: datetime | None = None,
) -> bool:
    """Marca ANALYZED al terminar Density; jobs históricos quedan intactos."""

    campaign_raw = str(job.get("campaign_id") or "").strip()
    if not campaign_raw:
        return False

    required = {
        "tenant_ref": str(job.get("tenant_ref") or "").strip(),
        "organization_ref": str(job.get("organization_ref") or "").strip(),
        "farm_id": str(job.get("farm_id") or "").strip(),
        "plot_id": str(job.get("plot_id") or "").strip(),
    }
    missing = [key for key, value in required.items() if not value]
    if missing:
        raise ValueError(
            "Job Density vinculado a Campaign sin alcance completo: "
            + ", ".join(sorted(missing))
        )

    session = session_factory()
    try:
        DBICampaignService(session).transition_campaign(
            campaign_id=UUID(campaign_raw),
            tenant_ref=required["tenant_ref"],
            organization_ref=required["organization_ref"],
            farm_id=UUID(required["farm_id"]),
            plot_id=UUID(required["plot_id"]),
            target_status=DBICampaignStatus.ANALYZED,
            occurred_at=_utc(occurred_at) if occurred_at is not None else None,
        )
        session.commit()
        return True
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
