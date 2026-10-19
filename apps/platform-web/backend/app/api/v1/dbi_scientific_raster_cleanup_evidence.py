"""H14/2H-2D/3E: immutable private S3 evidence of a verified cleanup DRY RUN.

This persists an observation only. It grants no authority to clean or abort.
"""
from __future__ import annotations

from hashlib import sha256
from io import BytesIO
import json
import os
from typing import Annotated, Literal
from uuid import UUID, NAMESPACE_URL, uuid5

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict, field_validator
from sqlalchemy.orm import Session

from app.api.v1.dbi_scientific_manifest_private import _store as _private_s3_store
from app.api.v1.dbi_scientific_raster_cleanup_dry_run import (
    ScientificCleanupPlanReceipt, preview_scientific_raster_cleanup,
)
from app.api.v1.dbi_scientific_raster_session_preparations import (
    ScientificSessionPreparationPayload,
)
from app.api.v1.dbi_scientific_raster_reservations import RasterRole, RasterIndex
from app.dbi.authorization import DBIAccessContext
from app.dbi.dependencies import get_dbi_access_context, get_dbi_session
from app.dbi.storage_contracts import (
    DBIStorageConflict, DBIStorageError, DBIStorageWriteRequest,
)
from app.dbi.storage_policy import DBIStoragePolicy, validate_sha256
from app.dbi.storage_contracts import DBIStoragePurpose

router = APIRouter(prefix="/dbi", tags=["dbi-scientific-cleanup-evidence"])
SessionDep = Annotated[Session, Depends(get_dbi_session)]
AccessDep = Annotated[DBIAccessContext, Depends(get_dbi_access_context)]
MAX_EVIDENCE_BYTES = 8 * 1024


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class CleanupEvidenceSubmission(_Strict):
    schema_version: Literal["dbi-h14-cleanup-evidence-submission.v1"]
    inspection: ScientificSessionPreparationPayload
    expected_evidence_sha256: str

    @field_validator("expected_evidence_sha256")
    @classmethod
    def canonical_sha(cls, value: str) -> str:
        try:
            return validate_sha256(value)
        except DBIStorageConflict as exc:
            raise ValueError("SHA-256 no canónico.") from exc


class _StoredEvidence(_Strict):
    schema_version: Literal["dbi-h14-cleanup-observation-stored.v1"]
    tenant_ref: str
    organization_ref: str
    farm_id: UUID
    plot_id: UUID
    campaign_id: UUID
    actor_ref: str
    role: RasterRole
    index: RasterIndex | None
    manifest_sha256: str
    reservation_sha256: str
    evidence_sha256: str
    campaign_status: Literal["APPROVED", "PUBLISHED"]
    reconciliation_status: str
    proposed_action: str
    incomplete_upload_count: int
    unexpected_upload_count: int
    recorded_upload_candidate: bool
    manual_review_required: bool
    review_observation_only: Literal[True]
    cleanup_authorized: Literal[False]
    cleanup_executed: Literal[False]
    signed: Literal[False]
    file_received: Literal[False]
    content_verified: Literal[False]
    published: Literal[False]


class CleanupEvidenceReceipt(_Strict):
    schema_version: Literal["dbi-h14-cleanup-evidence-receipt.v1"]
    evidence_object_id: UUID
    evidence_object_sha256: str
    evidence_sha256: str
    recorded_at: str
    created: bool
    evidence_persisted: Literal[True]
    evidence_signed: Literal[False]
    cleanup_authorized: Literal[False]
    cleanup_executed: Literal[False]
    grants_issued: Literal[False]
    file_received: Literal[False]
    content_verified: Literal[False]
    published: Literal[False]


def _enabled() -> None:
    required = (
        "DBI_SCIENTIFIC_CLEANUP_EVIDENCE_ENABLED",
        "DBI_SCIENTIFIC_RASTER_CLEANUP_PLAN_ENABLED",
        "DBI_SCIENTIFIC_RASTER_POSTAPPROVAL_AUDIT_ENABLED",
    )
    if any(os.environ.get(k) != "1" for k in required) or (
        os.environ.get("DBI_ENVIRONMENT", "").strip().lower()
        not in {"test", "development", "local"}
    ):
        raise HTTPException(404, detail="Evidencia privada de revisión no disponible.")


def _address(ctx, org, farm, plot, campaign, role, index, digest):
    # An immutable observation per actor, campaign, role and evidenced state.
    material = "|".join((
        ctx.tenant_ref, org, str(farm), str(plot), str(campaign),
        role, index or "-", ctx.principal_ref, digest,
    ))
    object_id = uuid5(NAMESPACE_URL, "dalgoro-dbi:h14:cleanup-observation:v1:" + material)
    return DBIStoragePolicy.build_address(
        tenant_ref=ctx.tenant_ref, purpose=DBIStoragePurpose.ANALYSIS_INPUT,
        object_id=object_id,
    )


def _bytes(saved: _StoredEvidence) -> bytes:
    return json.dumps(
        saved.model_dump(mode="json"), ensure_ascii=False,
        sort_keys=True, separators=(",", ":"),
    ).encode("utf-8")


def _readback(store, address, expected):
    record = store.stat(address)
    meta = record.metadata
    if (
        meta.address != address or meta.content_type != "application/json"
        or not 0 < meta.size_bytes <= MAX_EVIDENCE_BYTES
    ):
        raise DBIStorageConflict("Registro privado no canónico.")
    with store.open_read(address) as stream:
        raw = stream.read(MAX_EVIDENCE_BYTES + 1)
        extra = stream.read(1)
    if (
        not isinstance(raw, bytes) or extra not in (b"", None)
        or len(raw) != meta.size_bytes
        or sha256(raw).hexdigest() != meta.sha256
        or raw != expected
    ):
        raise DBIStorageConflict("La observación privada divergió.")
    parsed = _StoredEvidence.model_validate_json(raw)
    if _bytes(parsed) != raw:
        raise DBIStorageConflict("JSON privado no canónico.")
    return record


@router.put(
    "/organizations/{organization_ref}/farms/{farm_id}/plots/{plot_id}"
    "/campaigns/{campaign_id}/scientific-intake/private-raster-cleanup-observations"
    "/{role}/{index}",
    response_model=CleanupEvidenceReceipt,
)
def record_cleanup_observation(
    organization_ref: str, farm_id: UUID, plot_id: UUID, campaign_id: UUID,
    role: RasterRole, index: str, payload: CleanupEvidenceSubmission,
    request: Request, response: Response, session: SessionDep, context: AccessDep,
) -> CleanupEvidenceReceipt:
    _enabled()
    response.headers["Cache-Control"] = "no-store"
    # Re-evaluate authoritative audit; client supplies only expected digest,
    # not the action, S3 inventory or cleanup permission.
    plan = preview_scientific_raster_cleanup(
        organization_ref, farm_id, plot_id, campaign_id, role, index,
        payload.inspection, request, response, session, context,
    )
    if not isinstance(plan, ScientificCleanupPlanReceipt) or (
        plan.campaign_id != campaign_id
        or plan.role != role
        or plan.index != (None if index == "_" else index)
        or plan.evidence_sha256 != payload.expected_evidence_sha256
        or any((
            plan.cleanup_authorized, plan.cleanup_executed,
            plan.evidence_signed, plan.evidence_persisted,
            plan.grants_issued, plan.file_received, plan.content_verified,
            plan.institutional_approved, plan.published,
        ))
    ):
        raise HTTPException(409, detail="Diagnóstico privado cambió o es contradictorio.")
    saved = _StoredEvidence(
        schema_version="dbi-h14-cleanup-observation-stored.v1",
        tenant_ref=context.tenant_ref, organization_ref=organization_ref,
        farm_id=farm_id, plot_id=plot_id, campaign_id=campaign_id,
        actor_ref=context.principal_ref, role=role, index=plan.index,
        manifest_sha256=payload.inspection.manifest_sha256,
        reservation_sha256=payload.inspection.reservation_sha256,
        evidence_sha256=plan.evidence_sha256,
        campaign_status=plan.campaign_status,
        reconciliation_status=plan.reconciliation_status,
        proposed_action=plan.proposed_action,
        incomplete_upload_count=plan.incomplete_upload_count,
        unexpected_upload_count=plan.unexpected_upload_count,
        recorded_upload_candidate=plan.recorded_upload_candidate,
        manual_review_required=plan.manual_review_required,
        review_observation_only=True, cleanup_authorized=False,
        cleanup_executed=False, signed=False,
        file_received=False, content_verified=False, published=False,
    )
    raw = _bytes(saved)
    if len(raw) > MAX_EVIDENCE_BYTES:
        raise HTTPException(413, detail="Observación supera cuota privada.")
    address = _address(
        context, organization_ref, farm_id, plot_id, campaign_id,
        role, plan.index, plan.evidence_sha256,
    )
    metadata = DBIStoragePolicy.build_metadata(
        address=address, content_type="application/json",
        size_bytes=len(raw), sha256_hex=sha256(raw).hexdigest(),
    )
    try:
        store = _private_s3_store(request)  # DBIS3ObjectStore required, no fallback
        written = store.put(DBIStorageWriteRequest(metadata=metadata), BytesIO(raw))
        record = _readback(store, address, raw)
    except DBIStorageConflict as exc:
        raise HTTPException(409, detail="Observación existente divergente.") from exc
    except (DBIStorageError, ValueError, TypeError) as exc:
        raise HTTPException(503, detail="Evidencia S3 privada no verificable.") from exc
    response.status_code = 201 if written.created else 200
    return CleanupEvidenceReceipt(
        schema_version="dbi-h14-cleanup-evidence-receipt.v1",
        evidence_object_id=record.metadata.address.object_id,
        evidence_object_sha256=record.metadata.sha256,
        evidence_sha256=plan.evidence_sha256,
        recorded_at=record.created_at.isoformat(), created=written.created,
        evidence_persisted=True, evidence_signed=False,
        cleanup_authorized=False, cleanup_executed=False,
        grants_issued=False, file_received=False,
        content_verified=False, published=False,
    )
