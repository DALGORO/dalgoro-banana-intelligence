"""Adopción visible y controlada de trabajos locales históricos de Density."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import UUID

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from app.dbi.campaigns.artifacts import (
    DBICampaignArtifactReader,
    DBICampaignArtifactRegistration,
    DBICampaignArtifactService,
    DBICampaignArtifactSourceKind,
    DBICampaignArtifactType,
)
from app.dbi.campaigns.contracts import DBICampaignConflict, DBICampaignUnavailable
from app.dbi.campaigns.repository import DBICampaignRepository
from app.dbi.density_campaign import CAPTURED_AT_SOURCE_ASSET_CREATED_FALLBACK
from app.dbi.density_legacy_campaign import (
    LEGACY_CAMPAIGN_ORIGIN,
    LEGACY_PROCESSED_AT_SOURCE,
    adopt_historical_density_job_to_campaign,
    legacy_density_campaign_id,
)

from .dbi_density_local import (
    CurrentUser,
    DBISession,
    LegacySession,
    authorize_job,
    job_campaign_id,
    job_dir,
    job_file,
    scoped_inputs,
    update_job,
)
from .dbi_pilot import _local_store, _organization_ref, _require_local_pilot, _tenant_ref


router = APIRouter(prefix="/dbi/pilot", tags=["dbi-density-legacy-campaign"])


class DensityCampaignAdoptionResponse(BaseModel):
    job_id: UUID
    eligible: bool
    adopted: bool
    campaign_id: UUID | None = None
    campaign_status: str | None = None
    campaign_origin: str | None = None
    catalog_artifact_count: int = 0
    catalog_artifact_types: list[str] = []
    message: str


def _uuid_field(job: dict[str, Any], name: str) -> UUID:
    raw = str(job.get(name) or "").strip()
    try:
        return UUID(raw)
    except ValueError as error:
        raise HTTPException(
            status_code=409,
            detail=f"El trabajo histórico no conserva un {name} válido.",
        ) from error


def _legacy_target_density(job_id: UUID) -> float | None:
    path = job_dir(job_id) / "request.json"
    if not path.is_file():
        return None
    try:
        raw = json.loads(path.read_text(encoding="utf-8-sig"))
        value = float(raw.get("target_density"))
    except (OSError, ValueError, TypeError, AttributeError):
        return None
    return value if value > 0 else None


def _legacy_processed_at(job_id: UUID, job: dict[str, Any]) -> tuple[datetime, str]:
    """Obtiene evidencia temporal sin presentarla como timestamp científico exacto."""

    run_raw = str(job.get("run_directory") or "").strip()
    if run_raw:
        state_path = Path(run_raw).expanduser() / "estado_pipeline.json"
        if state_path.is_file():
            return (
                datetime.fromtimestamp(state_path.stat().st_mtime, tz=timezone.utc),
                "pipeline_state_mtime_fallback_not_declared_completion_time",
            )

    persisted = job_file(job_id)
    if persisted.is_file():
        return (
            datetime.fromtimestamp(persisted.stat().st_mtime, tz=timezone.utc),
            LEGACY_PROCESSED_AT_SOURCE,
        )
    return datetime.now(timezone.utc), "legacy_adoption_time_fallback_not_pipeline_completion_time"


def _status(
    *,
    company_id: int,
    job_id: UUID,
    job: dict[str, Any],
    dbi_session: DBISession,
) -> DensityCampaignAdoptionResponse:
    campaign_id = job_campaign_id(job)
    if campaign_id is None:
        eligible = str(job.get("status") or "") == "completed"
        return DensityCampaignAdoptionResponse(
            job_id=job_id,
            eligible=eligible,
            adopted=False,
            message=(
                "Trabajo histórico listo para adopción sin recalcular las 17 etapas."
                if eligible
                else "La adopción requiere un trabajo histórico completado."
            ),
        )

    farm_id = _uuid_field(job, "farm_id")
    plot_id = _uuid_field(job, "plot_id")
    tenant_ref = _tenant_ref()
    organization_ref = _organization_ref(company_id)
    campaign = DBICampaignRepository(dbi_session).get_campaign(
        campaign_id=campaign_id,
        tenant_ref=tenant_ref,
        organization_ref=organization_ref,
        farm_id=farm_id,
        plot_id=plot_id,
    )
    if campaign is None:
        raise HTTPException(
            status_code=409,
            detail="El job referencia una Campaign que no está disponible en su ámbito DBI.",
        )
    artifacts = DBICampaignArtifactReader(dbi_session).list_artifacts(
        campaign_id=campaign_id,
        tenant_ref=tenant_ref,
        organization_ref=organization_ref,
        farm_id=farm_id,
        plot_id=plot_id,
    )
    origin = str(job.get("campaign_origin") or "native")
    return DensityCampaignAdoptionResponse(
        job_id=job_id,
        eligible=False,
        adopted=origin == LEGACY_CAMPAIGN_ORIGIN,
        campaign_id=campaign_id,
        campaign_status=campaign.status,
        campaign_origin=origin,
        catalog_artifact_count=len(artifacts),
        catalog_artifact_types=[artifact.artifact_type.value for artifact in artifacts],
        message=(
            "Trabajo histórico adoptado en Campaign con trazabilidad verificable."
            if origin == LEGACY_CAMPAIGN_ORIGIN
            else "Este análisis ya nació vinculado a Campaign."
        ),
    )


@router.get(
    "/companies/{company_id}/density/jobs/{job_id}/campaign-adoption",
    response_model=DensityCampaignAdoptionResponse,
)
def get_density_campaign_adoption(
    company_id: int,
    job_id: UUID,
    legacy_session: LegacySession,
    dbi_session: DBISession,
    user: CurrentUser,
) -> DensityCampaignAdoptionResponse:
    _require_local_pilot()
    job = authorize_job(company_id, legacy_session, user, job_id)
    return _status(
        company_id=company_id,
        job_id=job_id,
        job=job,
        dbi_session=dbi_session,
    )


@router.post(
    "/companies/{company_id}/density/jobs/{job_id}/campaign-adoption",
    response_model=DensityCampaignAdoptionResponse,
)
def adopt_density_campaign(
    request: Request,
    company_id: int,
    job_id: UUID,
    legacy_session: LegacySession,
    dbi_session: DBISession,
    user: CurrentUser,
) -> DensityCampaignAdoptionResponse:
    _require_local_pilot()
    job = authorize_job(company_id, legacy_session, user, job_id)

    if job_campaign_id(job) is not None:
        return _status(
            company_id=company_id,
            job_id=job_id,
            job=job,
            dbi_session=dbi_session,
        )
    if str(job.get("status") or "") != "completed":
        raise HTTPException(
            status_code=409,
            detail="La adopción Campaign requiere un análisis histórico completado.",
        )

    farm_id = _uuid_field(job, "farm_id")
    plot_id = _uuid_field(job, "plot_id")
    orthophoto_asset_id = _uuid_field(job, "orthophoto_asset_id")
    _farm, _plot, asset, _orthophoto = scoped_inputs(
        dbi_session,
        company_id,
        farm_id,
        plot_id,
        orthophoto_asset_id,
        _local_store(request),
    )
    processed_at, processed_at_source = _legacy_processed_at(job_id, job)
    tenant_ref = _tenant_ref()
    organization_ref = _organization_ref(company_id)

    try:
        campaign, created = adopt_historical_density_job_to_campaign(
            dbi_session,
            tenant_ref=tenant_ref,
            organization_ref=organization_ref,
            farm_id=farm_id,
            plot_id=plot_id,
            source_job_id=job_id,
            captured_at=asset.created_at,
            processed_at=processed_at,
        )
        DBICampaignArtifactService(dbi_session).register_artifact(
            campaign_id=campaign.campaign_id,
            tenant_ref=tenant_ref,
            organization_ref=organization_ref,
            farm_id=farm_id,
            plot_id=plot_id,
            request=DBICampaignArtifactRegistration(
                artifact_type=DBICampaignArtifactType.ORTHOPHOTO_SOURCE,
                source_kind=DBICampaignArtifactSourceKind.INPUT_ASSET,
                source_ref=asset.id,
                sha256=asset.sha256,
                version=1,
            ),
        )
        dbi_session.commit()
    except DBICampaignUnavailable as error:
        dbi_session.rollback()
        raise HTTPException(status_code=404, detail=str(error)) from error
    except DBICampaignConflict as error:
        dbi_session.rollback()
        raise HTTPException(status_code=409, detail=str(error)) from error
    except Exception:
        dbi_session.rollback()
        raise

    artifacts = DBICampaignArtifactReader(dbi_session).list_artifacts(
        campaign_id=campaign.campaign_id,
        tenant_ref=tenant_ref,
        organization_ref=organization_ref,
        farm_id=farm_id,
        plot_id=plot_id,
    )
    target_density = _legacy_target_density(job_id)
    try:
        job = update_job(
            job_id,
            campaign_id=str(campaign.campaign_id),
            tenant_ref=tenant_ref,
            organization_ref=organization_ref,
            target_density=target_density,
            orthophoto_sha256=asset.sha256,
            campaign_captured_at=campaign.captured_at.isoformat(),
            campaign_captured_at_source=CAPTURED_AT_SOURCE_ASSET_CREATED_FALLBACK,
            campaign_processed_at=(campaign.processed_at.isoformat() if campaign.processed_at else None),
            campaign_processed_at_source=processed_at_source,
            campaign_origin=LEGACY_CAMPAIGN_ORIGIN,
            campaign_adopted_at=datetime.now(timezone.utc).isoformat(),
            campaign_catalog_artifact_count=len(artifacts),
            campaign_sync_error=None,
        )
    except OSError as error:
        raise HTTPException(
            status_code=500,
            detail=(
                "La Campaign histórica quedó persistida, pero no se pudo sincronizar job.json. "
                "Vuelva a ejecutar la adopción; el reintento es idempotente."
            ),
        ) from error

    result = _status(
        company_id=company_id,
        job_id=job_id,
        job=job,
        dbi_session=dbi_session,
    )
    if created:
        result.message = "Trabajo histórico adoptado sin recalcular Density; Campaign y ortofoto fuente quedaron trazables."
    return result
