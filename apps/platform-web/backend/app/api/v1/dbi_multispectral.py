"""Lectura HTTP autorizada de evidencia MULTI derivada; sin cálculo ni mutación."""
from __future__ import annotations

from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, ValidationError
from sqlalchemy import select
from app.dbi.models.agriculture import Campaign
from sqlalchemy.orm import Session

from app.dbi.authorization import (
    DBIAccessContext, DBIAccessDenied, DBIAuthorizationPolicy, DBIPermission,
)
from app.dbi.dependencies import get_dbi_access_context, get_dbi_session
from app.dbi.multispectral.contracts import (
    DBIMultispectralExtractionCandidate, multispectral_extraction_id,
)
from app.dbi.multispectral.repository import (
    DBIMultispectralExtractionRepository, canonical_json, sha256_text,
)

router = APIRouter(prefix="/dbi", tags=["dbi-multispectral"])
SessionDependency = Annotated[Session, Depends(get_dbi_session)]
AccessDependency = Annotated[DBIAccessContext, Depends(get_dbi_access_context)]

_NOT_FOUND = "Extracción multiespectral DBI no disponible."
_CONFLICT = "La evidencia multiespectral DBI no supera las comprobaciones de integridad."


class DBIMultispectralExtractionRead(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    extraction_id: UUID
    created_at: datetime
    observed_at: datetime
    campaign_id: UUID | None
    captured_at: datetime | None
    campaign_linkage: str
    payload: DBIMultispectralExtractionCandidate


def _published_campaign_ids(
    session: Session, context: DBIAccessContext, *,
    organization_ref: str, farm_id: UUID, plot_id: UUID,
) -> frozenset[UUID]:
    """Sólo Campaign aprobada y publicada; nunca inferir vínculo por fecha."""
    return frozenset(session.execute(
        select(Campaign.id).where(
            Campaign.tenant_ref == context.tenant_ref,
            Campaign.organization_ref == organization_ref,
            Campaign.farm_id == farm_id, Campaign.plot_id == plot_id,
            Campaign.analysis_type == "multispectral",
            Campaign.status == "PUBLISHED",
            Campaign.approved_at.is_not(None),
            Campaign.published_at.is_not(None),
        )
    ).scalars().all())


@router.get(
    "/organizations/{organization_ref}/farms/{farm_id}/plots/{plot_id}"
    "/multispectral-extractions/{extraction_id}",
    response_model=DBIMultispectralExtractionRead,
)
def get_multispectral_extraction(
    organization_ref: str,
    farm_id: UUID,
    plot_id: UUID,
    extraction_id: UUID,
    session: SessionDependency,
    context: AccessDependency,
) -> DBIMultispectralExtractionRead:
    """Devuelve sólo estadísticas derivadas autorizadas, jamás banda o COG privado."""
    try:
        DBIAuthorizationPolicy.require_plot(
            context,
            tenant_ref=context.tenant_ref,
            organization_ref=organization_ref,
            farm_id=farm_id,
            plot_id=plot_id,
            permission=DBIPermission.READ,
        )
    except DBIAccessDenied as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=_NOT_FOUND) from exc

    repository = DBIMultispectralExtractionRepository(session)
    row = repository.get_scoped(
        extraction_id=extraction_id,
        tenant_ref=context.tenant_ref,
        organization_ref=organization_ref,
        farm_id=farm_id,
        plot_id=plot_id,
    )
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=_NOT_FOUND)

    observed_at = repository.observed_at_by_extraction_scoped(
        extraction_ids=[row.id],
        tenant_ref=context.tenant_ref,
        organization_ref=organization_ref,
        farm_id=farm_id,
        plot_id=plot_id,
    ).get(row.id)
    provenance = repository.campaign_provenance_by_extraction_scoped(
        extraction_ids=[row.id],
        tenant_ref=context.tenant_ref,
        organization_ref=organization_ref,
        farm_id=farm_id,
        plot_id=plot_id,
    ).get(row.id)
    if provenance is None or provenance[0] not in _published_campaign_ids(
        session, context,
        organization_ref=organization_ref, farm_id=farm_id, plot_id=plot_id,
    ):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=_NOT_FOUND)
    return _checked_multispectral_row(
        row, observed_at, provenance, context, organization_ref, farm_id, plot_id,
    )


def _checked_multispectral_row(
    row: object,
    observed_at: datetime | None,
    provenance: tuple[UUID, datetime] | None,
    context: DBIAccessContext,
    organization_ref: str,
    farm_id: UUID,
    plot_id: UUID,
) -> DBIMultispectralExtractionRead:
    """Falla cerrado ante diferencias entre payload versionado y registro persistido."""
    try:
        payload = DBIMultispectralExtractionCandidate.model_validate_json(row.payload_json)
        fields_match = (
            row.id == multispectral_extraction_id(payload)
            and row.tenant_ref == context.tenant_ref == payload.tenant_ref
            and row.organization_ref == organization_ref == payload.organization_ref
            and row.farm_id == farm_id == payload.farm_id
            and row.plot_id == plot_id == payload.plot_id
            and row.observation_version_id == payload.observation_version_id
            and row.source_raster_product_id == payload.source_raster_product_id
            and row.sampling_point_id == payload.sampling_point_id
            and row.up_id == payload.up_id
            and row.schema_version == payload.schema_version
            and row.support_mode == payload.support_mode
            and row.support_profile_version == payload.support_profile_version
            and row.support_limitation == payload.support_limitation
            and row.stack_fingerprint == payload.stack_fingerprint
            and row.selected_count == payload.selected_count
            and row.evidence_kind == payload.evidence_kind == "derived"
            and row.payload_json == canonical_json(payload.model_dump(mode="json"))
            and row.payload_sha256 == sha256_text(row.payload_json)
        )
        if provenance is not None:
            campaign_id, captured_at = provenance
            if (
                not isinstance(campaign_id, UUID)
                or not isinstance(captured_at, datetime)
                or captured_at.tzinfo is None
                or captured_at.utcoffset() is None
            ):
                raise ValueError("campaign provenance")
        else:
            campaign_id, captured_at = None, None
        if (not fields_match or row.created_at is None
                or observed_at is None or observed_at.tzinfo is None
                or observed_at.utcoffset() is None):
            raise ValueError("integrity")
    except (ValidationError, ValueError, TypeError, AttributeError) as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=_CONFLICT) from exc

    return DBIMultispectralExtractionRead(
        extraction_id=row.id, created_at=row.created_at,
        observed_at=observed_at,
        campaign_id=campaign_id,
        captured_at=captured_at,
        campaign_linkage="verified_job_chain" if campaign_id else "unverified",
        payload=payload,
    )


@router.get(
    "/organizations/{organization_ref}/farms/{farm_id}/plots/{plot_id}"
    "/multispectral-extractions",
    response_model=list[DBIMultispectralExtractionRead],
)
def list_multispectral_extractions(
    organization_ref: str,
    farm_id: UUID,
    plot_id: UUID,
    session: SessionDependency,
    context: AccessDependency,
) -> list[DBIMultispectralExtractionRead]:
    """Lista hasta 20 derivaciones recientes, sin revelar otras fincas ni datos corruptos."""
    try:
        DBIAuthorizationPolicy.require_plot(
            context,
            tenant_ref=context.tenant_ref,
            organization_ref=organization_ref,
            farm_id=farm_id,
            plot_id=plot_id,
            permission=DBIPermission.READ,
        )
    except DBIAccessDenied as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=_NOT_FOUND) from exc

    repository = DBIMultispectralExtractionRepository(session)
    rows = repository.list_scoped(
        tenant_ref=context.tenant_ref,
        organization_ref=organization_ref,
        farm_id=farm_id,
        plot_id=plot_id,
    )
    observation_times = repository.observed_at_by_extraction_scoped(
        extraction_ids=[row.id for row in rows],
        tenant_ref=context.tenant_ref,
        organization_ref=organization_ref,
        farm_id=farm_id,
        plot_id=plot_id,
    )
    provenance = repository.campaign_provenance_by_extraction_scoped(
        extraction_ids=[row.id for row in rows],
        tenant_ref=context.tenant_ref,
        organization_ref=organization_ref,
        farm_id=farm_id,
        plot_id=plot_id,
    )
    published = _published_campaign_ids(
        session, context,
        organization_ref=organization_ref, farm_id=farm_id, plot_id=plot_id,
    )
    return [
        _checked_multispectral_row(
            row, observation_times.get(row.id), provenance.get(row.id),
            context, organization_ref, farm_id, plot_id,
        )
        for row in rows
        if provenance.get(row.id) is not None
        and provenance[row.id][0] in published
    ]
