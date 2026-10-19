"""H14/2H-2D/3H: compare a 2-actor immutable review with a fresh S3 audit.

The original operator invokes the fresh audit with THEIR OWN credentials.
No impersonation of the independent reviewer and NO cleanup authorization.
The evidence read and the fresh audit use separate read-only SQL transactions.
"""
from __future__ import annotations

import os
from types import SimpleNamespace
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session

from app.api.v1.dbi_scientific_raster_cleanup_evidence import (
    MAX_EVIDENCE_BYTES, _StoredEvidence, _address as _evidence_address,
    _bytes as _evidence_bytes, _private_s3_store,
)
from app.api.v1.dbi_scientific_raster_cleanup_peer_review import (
    MAX_REVIEW_BYTES, _StoredIndependentReview, _canonical, _read_json,
    _review_address,
)
from app.api.v1.dbi_scientific_raster_cleanup_review_chain import (
    ReviewChainVerificationRequest,
)
from app.api.v1.dbi_scientific_raster_cleanup_dry_run import (
    ScientificCleanupPlanReceipt, preview_scientific_raster_cleanup,
)
from app.api.v1.dbi_scientific_raster_postapproval_audit import (
    _locked_approved_campaign,
)
from app.api.v1.dbi_scientific_raster_reservations import (
    RasterIndex, RasterRole, _role_index,
)
from app.api.v1.dbi_scientific_raster_session_preparations import (
    ScientificSessionPreparationPayload,
)
from app.dbi.authorization import DBIAccessContext
from app.dbi.dependencies import get_dbi_access_context, get_dbi_session
from app.dbi.storage_contracts import (
    DBIStorageConflict, DBIStorageError, DBIStorageNotFound,
)

router = APIRouter(prefix="/dbi", tags=["dbi-scientific-reviewed-live-audit"])
SessionDep = Annotated[Session, Depends(get_dbi_session)]
AccessDep = Annotated[DBIAccessContext, Depends(get_dbi_access_context)]


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ReviewedLiveAuditRequest(_Strict):
    schema_version: Literal["dbi-h14-reviewed-live-audit-request.v1"]
    review_chain: ReviewChainVerificationRequest
    inspection: ScientificSessionPreparationPayload


class ReviewedLiveAuditReceipt(_Strict):
    schema_version: Literal["dbi-h14-reviewed-live-audit-receipt.v1"]
    campaign_id: UUID
    campaign_status: Literal["APPROVED", "PUBLISHED"]
    role: RasterRole
    index: RasterIndex | None
    baseline_evidence_sha256: str
    current_evidence_sha256: str
    baseline_reconciliation_status: str
    current_reconciliation_status: str
    baseline_incomplete_upload_count: int
    current_incomplete_upload_count: int
    baseline_unexpected_upload_count: int
    current_unexpected_upload_count: int
    historical_chain_verified: Literal[True]
    distinct_reviewers_verified: Literal[True]
    live_s3_inventory_rechecked: Literal[True]
    snapshot_matches_live: bool
    evidence_drift_detected: bool
    separate_nonatomic_read_transactions: Literal[True]
    manual_review_required: Literal[True]
    evidence_signed: Literal[False]
    cleanup_authorized: Literal[False]
    cleanup_executed: Literal[False]
    ready_for_upload: Literal[False]
    grants_issued: Literal[False]
    file_received: Literal[False]
    content_verified: Literal[False]
    published: Literal[False]


def _enabled() -> None:
    flags = (
        "DBI_SCIENTIFIC_REVIEWED_LIVE_RECHECK_ENABLED",
        "DBI_SCIENTIFIC_CLEANUP_CHAIN_VERIFY_ENABLED",
        "DBI_SCIENTIFIC_CLEANUP_PEER_REVIEW_ENABLED",
        "DBI_SCIENTIFIC_CLEANUP_EVIDENCE_ENABLED",
        "DBI_SCIENTIFIC_RASTER_CLEANUP_PLAN_ENABLED",
        "DBI_SCIENTIFIC_RASTER_POSTAPPROVAL_AUDIT_ENABLED",
    )
    if (
        any(os.environ.get(flag) != "1" for flag in flags)
        or os.environ.get("DBI_ENVIRONMENT", "").strip().lower()
        not in {"test", "development", "local"}
    ):
        raise HTTPException(404, detail="Auditoría de cambios históricos no disponible.")


def _read_verified_archive(
    *, request: Request, context: DBIAccessContext, organization_ref: str,
    farm_id: UUID, plot_id: UUID, campaign_id: UUID,
    role: RasterRole, index: RasterIndex | None,
    payload: ReviewChainVerificationRequest,
    inspection: ScientificSessionPreparationPayload,
    campaign_status: str,
) -> _StoredEvidence:
    if (
        payload.original_actor_ref != context.principal_ref
        or payload.original_actor_ref == payload.reviewer_actor_ref
    ):
        raise HTTPException(409, detail="Solo el autor original puede solicitar auditoría viva.")
    store = _private_s3_store(request)
    original_address = _evidence_address(
        context, organization_ref, farm_id, plot_id, campaign_id,
        role, index, payload.evidence_sha256,
    )
    original_record, original_raw = _read_json(
        store, original_address, max_bytes=MAX_EVIDENCE_BYTES,
    )
    original = _StoredEvidence.model_validate_json(original_raw)
    if (
        _evidence_bytes(original) != original_raw
        or original_record.metadata.sha256 != payload.original_object_sha256
        or original.tenant_ref != context.tenant_ref
        or original.organization_ref != organization_ref
        or original.farm_id != farm_id or original.plot_id != plot_id
        or original.campaign_id != campaign_id
        or original.actor_ref != context.principal_ref
        or original.role != role or original.index != index
        or original.evidence_sha256 != payload.evidence_sha256
        or original.campaign_status != campaign_status
        or original.manifest_sha256 != inspection.manifest_sha256
        or original.reservation_sha256 != inspection.reservation_sha256
        or not original.review_observation_only
        or any((
            original.cleanup_authorized, original.cleanup_executed,
            original.signed, original.file_received,
            original.content_verified, original.published,
        ))
    ):
        raise DBIStorageConflict("Observación histórica no corresponde al expediente.")

    reviewer_context = SimpleNamespace(
        tenant_ref=context.tenant_ref,
        principal_ref=payload.reviewer_actor_ref,
    )
    review_address = _review_address(
        reviewer_context, organization_ref, farm_id, plot_id, campaign_id,
        role, index, original_address.object_id, payload.original_object_sha256,
    )
    review_record, review_raw = _read_json(
        store, review_address, max_bytes=MAX_REVIEW_BYTES,
    )
    review = _StoredIndependentReview.model_validate_json(review_raw)
    if (
        _canonical(review) != review_raw
        or review_record.metadata.sha256 != payload.review_object_sha256
        or review.tenant_ref != context.tenant_ref
        or review.organization_ref != organization_ref
        or review.farm_id != farm_id or review.plot_id != plot_id
        or review.campaign_id != campaign_id
        or review.role != role or review.index != index
        or review.original_actor_ref != context.principal_ref
        or review.reviewer_actor_ref != payload.reviewer_actor_ref
        or review.original_object_id != original_address.object_id
        or review.original_object_sha256 != payload.original_object_sha256
        or review.evidence_sha256 != payload.evidence_sha256
        or review.campaign_status != campaign_status
        or review.acknowledgement != "reviewed_snapshot_not_cleanup_authorization"
        or not review.independent_actor or not review.snapshot_only
        or any((
            review.evidence_signed, review.cleanup_authorized,
            review.cleanup_executed, review.grants_issued,
            review.file_received, review.content_verified, review.published,
        ))
    ):
        raise DBIStorageConflict("La revisión histórica independiente no coincide.")
    return original


@router.post(
    "/organizations/{organization_ref}/farms/{farm_id}/plots/{plot_id}"
    "/campaigns/{campaign_id}/scientific-intake/private-raster-reviewed-live-audit"
    "/{role}/{index}",
    response_model=ReviewedLiveAuditReceipt,
)
def recheck_reviewed_raster_observation(
    organization_ref: str, farm_id: UUID, plot_id: UUID, campaign_id: UUID,
    role: RasterRole, index: str, payload: ReviewedLiveAuditRequest,
    request: Request, response: Response, session: SessionDep, context: AccessDep,
) -> ReviewedLiveAuditReceipt:
    _enabled()
    response.headers["Cache-Control"] = "no-store"
    mapped = None if index == "_" else index
    try:
        status = _locked_approved_campaign(
            session, context, organization_ref, farm_id, plot_id, campaign_id,
        )
        _role_index(role, mapped)
        baseline = _read_verified_archive(
            request=request, context=context,
            organization_ref=organization_ref, farm_id=farm_id, plot_id=plot_id,
            campaign_id=campaign_id, role=role, index=mapped,
            payload=payload.review_chain, inspection=payload.inspection,
            campaign_status=status,
        )
    except HTTPException:
        raise
    except DBIStorageNotFound as error:
        raise HTTPException(404, detail="Falta evidencia privada o revisión.") from error
    except DBIStorageConflict as error:
        raise HTTPException(409, detail="Evidencia histórica o revisión divergente.") from error
    except (DBIStorageError, ValueError, TypeError, KeyError) as error:
        raise HTTPException(503, detail="No se pudo leer el expediente privado.") from error
    finally:
        session.rollback()  # First read-only Campaign lock is released.

    # Authenticated original operator rechecks the S3 inventory with their OWN
    # identity and private idempotency secret. No reviewer impersonation.
    # preview() acquires a SECOND Campaign lock and releases it on audit rollback.
    # These two reads are deliberately NOT asserted to be an atomic snapshot.
    live = preview_scientific_raster_cleanup(
        organization_ref, farm_id, plot_id, campaign_id,
        role, index, payload.inspection,
        request, response, session, context,
    )
    if (
        not isinstance(live, ScientificCleanupPlanReceipt)
        or live.campaign_id != campaign_id
        or live.campaign_status != status
        or live.role != role or live.index != mapped
        or any((
            live.cleanup_authorized, live.cleanup_executed,
            live.evidence_signed, live.evidence_persisted,
            live.ready_for_upload, live.grants_issued, live.parts_received,
            live.file_received, live.content_verified,
            live.institutional_approved, live.published,
        ))
    ):
        raise HTTPException(409, detail="La reevaluación S3 no coincide con Campaign.")

    matches = all((
        baseline.evidence_sha256 == live.evidence_sha256,
        baseline.reconciliation_status == live.reconciliation_status,
        baseline.proposed_action == live.proposed_action,
        baseline.incomplete_upload_count == live.incomplete_upload_count,
        baseline.unexpected_upload_count == live.unexpected_upload_count,
        baseline.recorded_upload_candidate == live.recorded_upload_candidate,
        baseline.manual_review_required == live.manual_review_required,
    ))
    return ReviewedLiveAuditReceipt(
        schema_version="dbi-h14-reviewed-live-audit-receipt.v1",
        campaign_id=campaign_id, campaign_status=live.campaign_status,
        role=role, index=mapped,
        baseline_evidence_sha256=baseline.evidence_sha256,
        current_evidence_sha256=live.evidence_sha256,
        baseline_reconciliation_status=baseline.reconciliation_status,
        current_reconciliation_status=live.reconciliation_status,
        baseline_incomplete_upload_count=baseline.incomplete_upload_count,
        current_incomplete_upload_count=live.incomplete_upload_count,
        baseline_unexpected_upload_count=baseline.unexpected_upload_count,
        current_unexpected_upload_count=live.unexpected_upload_count,
        historical_chain_verified=True, distinct_reviewers_verified=True,
        live_s3_inventory_rechecked=True,
        snapshot_matches_live=matches, evidence_drift_detected=not matches,
        separate_nonatomic_read_transactions=True, manual_review_required=True,
        evidence_signed=False, cleanup_authorized=False, cleanup_executed=False,
        ready_for_upload=False, grants_issued=False, file_received=False,
        content_verified=False, published=False,
    )
