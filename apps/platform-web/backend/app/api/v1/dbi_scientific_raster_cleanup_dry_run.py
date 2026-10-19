"""H14/2H-2D/3D: vista privada de PLAN de limpieza; NUNCA la ejecuta."""
from __future__ import annotations

import os
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session

from app.api.v1.dbi_scientific_raster_postapproval_audit import (
    audit_postapproval_incomplete_raster_uploads,
)
from app.api.v1.dbi_scientific_raster_session_preparations import (
    ScientificSessionPreparationPayload,
)
from app.api.v1.dbi_scientific_raster_reservations import RasterRole, RasterIndex
from app.dbi.authorization import DBIAccessContext
from app.dbi.dependencies import get_dbi_access_context, get_dbi_session
from app.dbi.scientific_raster_cleanup_policy import (
    CleanupEvidenceScope, CleanupPlanEvidenceConflict, ProposedAction, build_cleanup_dry_run,
)

router = APIRouter(prefix="/dbi", tags=["dbi-scientific-cleanup-dry-run"])
SessionDep = Annotated[Session, Depends(get_dbi_session)]
AccessDep = Annotated[DBIAccessContext, Depends(get_dbi_access_context)]


class ScientificCleanupPlanReceipt(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    schema_version: Literal["dbi-h14-postapproval-cleanup-dry-run.v1"]
    campaign_id: UUID
    campaign_status: Literal["APPROVED", "PUBLISHED"]
    preparation_id: UUID
    asset_id: UUID
    role: RasterRole
    index: RasterIndex | None
    reconciliation_status: str
    proposed_action: ProposedAction
    evidence_sha256: str
    incomplete_upload_count: int
    unexpected_upload_count: int
    manual_review_required: bool
    recorded_upload_candidate: bool
    cleanup_authorized: Literal[False]
    cleanup_executed: Literal[False]
    evidence_signed: Literal[False]
    evidence_persisted: Literal[False]
    ready_for_upload: Literal[False]
    grants_issued: Literal[False]
    parts_received: Literal[False]
    file_received: Literal[False]
    content_verified: Literal[False]
    institutional_approved: Literal[False]
    published: Literal[False]


def _enabled() -> None:
    if (
        os.environ.get("DBI_SCIENTIFIC_RASTER_CLEANUP_PLAN_ENABLED") != "1"
        or os.environ.get("DBI_ENVIRONMENT", "").strip().lower()
        not in {"test", "development", "local"}
    ):
        raise HTTPException(404, detail="Plan administrativo de limpieza no disponible.")


@router.post(
    "/organizations/{organization_ref}/farms/{farm_id}/plots/{plot_id}"
    "/campaigns/{campaign_id}/scientific-intake/private-raster-cleanup-dry-run"
    "/{role}/{index}",
    response_model=ScientificCleanupPlanReceipt,
)
def preview_scientific_raster_cleanup(
    organization_ref: str, farm_id: UUID, plot_id: UUID, campaign_id: UUID,
    role: RasterRole, index: str, payload: ScientificSessionPreparationPayload,
    request: Request, response: Response, session: SessionDep, context: AccessDep,
) -> ScientificCleanupPlanReceipt:
    _enabled()
    response.headers["Cache-Control"] = "no-store"
    # Reuse already-tested postapproval MANAGE + Campaign FOR UPDATE + S3/SQL
    # reconciliation. That audit releases read-only locks using rollback.
    # The separate POSTAPPROVAL_AUDIT_ENABLED flag must also be set.
    audit = audit_postapproval_incomplete_raster_uploads(
        organization_ref, farm_id, plot_id, campaign_id, role, index,
        payload, request, response, session, context,
    )
    try:
        plan = build_cleanup_dry_run(
            audit,
            scope=CleanupEvidenceScope(
                tenant_ref=context.tenant_ref,
                organization_ref=organization_ref,
                farm_id=farm_id,
                plot_id=plot_id,
                campaign_id=campaign_id,
                actor_ref=context.principal_ref,
                manifest_sha256=payload.manifest_sha256,
                reservation_sha256=payload.reservation_sha256,
            ),
        )
    except CleanupPlanEvidenceConflict as error:
        raise HTTPException(409, detail="Diagnóstico de limpieza incoherente.") from error

    return ScientificCleanupPlanReceipt(
        schema_version="dbi-h14-postapproval-cleanup-dry-run.v1",
        campaign_id=audit.campaign_id,
        campaign_status=audit.campaign_status,
        preparation_id=audit.preparation_id,
        asset_id=audit.asset_id,
        role=audit.role, index=audit.index,
        reconciliation_status=audit.reconciliation_status,
        proposed_action=plan.action,
        evidence_sha256=plan.evidence_sha256,
        incomplete_upload_count=plan.incomplete_upload_count,
        unexpected_upload_count=plan.unexpected_upload_count,
        manual_review_required=plan.manual_review_required,
        recorded_upload_candidate=plan.candidate_exact_recorded_upload,
        cleanup_authorized=False, cleanup_executed=False,
        evidence_signed=False, evidence_persisted=False,
        ready_for_upload=False, grants_issued=False, parts_received=False,
        file_received=False, content_verified=False,
        institutional_approved=False, published=False,
    )
