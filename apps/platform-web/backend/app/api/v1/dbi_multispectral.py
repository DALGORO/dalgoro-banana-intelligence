"""Lectura HTTP autorizada de evidencia MULTI derivada; sin cálculo ni mutación."""
from __future__ import annotations

from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, ValidationError
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
    payload: DBIMultispectralExtractionCandidate


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

    row = DBIMultispectralExtractionRepository(session).get_scoped(
        extraction_id=extraction_id,
        tenant_ref=context.tenant_ref,
        organization_ref=organization_ref,
        farm_id=farm_id,
        plot_id=plot_id,
    )
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=_NOT_FOUND)

    return _checked_multispectral_row(row, context, organization_ref, farm_id, plot_id)


def _checked_multispectral_row(
    row: object,
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
        if not fields_match or row.created_at is None:
            raise ValueError("integrity")
    except (ValidationError, ValueError, TypeError, AttributeError) as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=_CONFLICT) from exc

    return DBIMultispectralExtractionRead(
        extraction_id=row.id, created_at=row.created_at, payload=payload,
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

    rows = DBIMultispectralExtractionRepository(session).list_scoped(
        tenant_ref=context.tenant_ref,
        organization_ref=organization_ref,
        farm_id=farm_id,
        plot_id=plot_id,
    )
    return [
        _checked_multispectral_row(row, context, organization_ref, farm_id, plot_id)
        for row in rows
    ]
