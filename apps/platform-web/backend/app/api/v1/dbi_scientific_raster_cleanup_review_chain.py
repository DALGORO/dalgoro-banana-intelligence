"""H14/2H-2D/3G: verify two-actor private evidence chain, READ ONLY.

This is a *snapshot* chain verification, never a fresh inventory or
institutional authorization. No S3 abort, grants or SQL writes.
"""
from __future__ import annotations

import os
from types import SimpleNamespace
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict, field_validator
from sqlalchemy.orm import Session

from app.api.v1.dbi_scientific_raster_cleanup_evidence import (
    MAX_EVIDENCE_BYTES, _StoredEvidence, _address as _evidence_address,
    _bytes as _evidence_bytes, _private_s3_store,
)
from app.api.v1.dbi_scientific_raster_cleanup_peer_review import (
    MAX_REVIEW_BYTES, _StoredIndependentReview,
    _canonical, _read_json, _review_address,
)
from app.api.v1.dbi_scientific_raster_postapproval_audit import (
    _locked_approved_campaign,
)
from app.api.v1.dbi_scientific_raster_reservations import (
    RasterIndex, RasterRole, _role_index,
)
from app.dbi.authorization import DBIAccessContext
from app.dbi.dependencies import get_dbi_access_context, get_dbi_session
from app.dbi.storage_contracts import (
    DBIStorageConflict, DBIStorageError, DBIStorageNotFound,
)
from app.dbi.storage_policy import validate_sha256

router = APIRouter(prefix="/dbi", tags=["dbi-scientific-cleanup-review-chain"])
SessionDep = Annotated[Session, Depends(get_dbi_session)]
AccessDep = Annotated[DBIAccessContext, Depends(get_dbi_access_context)]


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ReviewChainVerificationRequest(_Strict):
    schema_version: Literal["dbi-h14-observation-review-chain-request.v1"]
    original_actor_ref: str
    reviewer_actor_ref: str
    evidence_sha256: str
    original_object_sha256: str
    review_object_sha256: str

    @field_validator("original_actor_ref", "reviewer_actor_ref")
    @classmethod
    def canonical_actor(cls, value: str) -> str:
        if (
            not isinstance(value, str) or not 1 <= len(value) <= 128
            or value != value.strip()
            or any(ord(c) < 32 or ord(c) == 127 for c in value)
        ):
            raise ValueError("Actor no canónico.")
        return value

    @field_validator("evidence_sha256", "original_object_sha256", "review_object_sha256")
    @classmethod
    def canonical_digest(cls, value: str) -> str:
        try:
            return validate_sha256(value)
        except DBIStorageConflict as error:
            raise ValueError("SHA-256 no canónico.") from error


class ReviewChainVerificationReceipt(_Strict):
    schema_version: Literal["dbi-h14-observation-review-chain-receipt.v1"]
    campaign_id: UUID
    campaign_status: Literal["APPROVED", "PUBLISHED"]
    role: RasterRole
    index: RasterIndex | None
    original_object_sha256: str
    review_object_sha256: str
    evidence_sha256: str
    distinct_actors_verified: Literal[True]
    immutable_objects_verified: Literal[True]
    campaign_snapshot_matches: Literal[True]
    snapshot_chain_verified: Literal[True]
    live_s3_inventory_rechecked: Literal[False]
    cleanup_authorized: Literal[False]
    cleanup_executed: Literal[False]
    evidence_signed: Literal[False]
    grants_issued: Literal[False]
    file_received: Literal[False]
    content_verified: Literal[False]
    published: Literal[False]


def _enabled() -> None:
    required = (
        "DBI_SCIENTIFIC_CLEANUP_CHAIN_VERIFY_ENABLED",
        "DBI_SCIENTIFIC_CLEANUP_PEER_REVIEW_ENABLED",
        "DBI_SCIENTIFIC_CLEANUP_EVIDENCE_ENABLED",
        "DBI_SCIENTIFIC_RASTER_CLEANUP_PLAN_ENABLED",
        "DBI_SCIENTIFIC_RASTER_POSTAPPROVAL_AUDIT_ENABLED",
    )
    if (
        any(os.environ.get(flag) != "1" for flag in required)
        or os.environ.get("DBI_ENVIRONMENT", "").strip().lower()
        not in {"test", "development", "local"}
    ):
        raise HTTPException(404, detail="Verificación documental privada no disponible.")


@router.post(
    "/organizations/{organization_ref}/farms/{farm_id}/plots/{plot_id}"
    "/campaigns/{campaign_id}/scientific-intake/private-raster-cleanup-review-chain"
    "/{role}/{index}",
    response_model=ReviewChainVerificationReceipt,
)
def verify_cleanup_review_chain(
    organization_ref: str, farm_id: UUID, plot_id: UUID, campaign_id: UUID,
    role: RasterRole, index: str, payload: ReviewChainVerificationRequest,
    request: Request, response: Response, session: SessionDep, context: AccessDep,
) -> ReviewChainVerificationReceipt:
    _enabled()
    response.headers["Cache-Control"] = "no-store"
    mapped_index = None if index == "_" else index
    try:
        status = _locked_approved_campaign(
            session, context, organization_ref, farm_id, plot_id, campaign_id,
        )
        _role_index(role, mapped_index)
        # No impersonation of the original author. Only the actual reviewing
        # principal can verify their own immutable acknowledgement.
        if (
            context.principal_ref != payload.reviewer_actor_ref
            or payload.original_actor_ref == payload.reviewer_actor_ref
        ):
            raise HTTPException(409, detail="Se exige revisión por actor distinto.")

        store = _private_s3_store(request)
        original_context = SimpleNamespace(
            tenant_ref=context.tenant_ref,
            principal_ref=payload.original_actor_ref,
        )
        original_address = _evidence_address(
            original_context, organization_ref, farm_id, plot_id, campaign_id,
            role, mapped_index, payload.evidence_sha256,
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
            or original.actor_ref != payload.original_actor_ref
            or original.role != role or original.index != mapped_index
            or original.evidence_sha256 != payload.evidence_sha256
            or original.campaign_status != status
            or not original.review_observation_only
            or any((
                original.cleanup_authorized, original.cleanup_executed,
                original.signed, original.file_received,
                original.content_verified, original.published,
            ))
        ):
            raise DBIStorageConflict("Observación original no coincide.")

        review_address = _review_address(
            context, organization_ref, farm_id, plot_id, campaign_id,
            role, mapped_index, original_address.object_id,
            payload.original_object_sha256,
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
            or review.role != role or review.index != mapped_index
            or review.original_actor_ref != payload.original_actor_ref
            or review.reviewer_actor_ref != context.principal_ref
            or review.original_object_id != original_address.object_id
            or review.original_object_sha256 != payload.original_object_sha256
            or review.evidence_sha256 != payload.evidence_sha256
            or review.campaign_status != status
            or review.acknowledgement != "reviewed_snapshot_not_cleanup_authorization"
            or not review.independent_actor or not review.snapshot_only
            or any((
                review.evidence_signed, review.cleanup_authorized,
                review.cleanup_executed, review.grants_issued,
                review.file_received, review.content_verified, review.published,
            ))
        ):
            raise DBIStorageConflict("Revisión de segunda persona no coincide.")
    except HTTPException:
        raise
    except DBIStorageNotFound as error:
        raise HTTPException(404, detail="Expediente o revisión privada inexistente.") from error
    except DBIStorageConflict as error:
        raise HTTPException(409, detail="Cadena de revisión privada divergente.") from error
    except (DBIStorageError, ValueError, TypeError, KeyError) as error:
        raise HTTPException(503, detail="No se pudo verificar cadena privada.") from error
    finally:
        # Release Campaign lock without writing SQL.
        session.rollback()

    return ReviewChainVerificationReceipt(
        schema_version="dbi-h14-observation-review-chain-receipt.v1",
        campaign_id=campaign_id, campaign_status=status,
        role=role, index=mapped_index,
        original_object_sha256=payload.original_object_sha256,
        review_object_sha256=payload.review_object_sha256,
        evidence_sha256=payload.evidence_sha256,
        distinct_actors_verified=True, immutable_objects_verified=True,
        campaign_snapshot_matches=True, snapshot_chain_verified=True,
        live_s3_inventory_rechecked=False,
        cleanup_authorized=False, cleanup_executed=False, evidence_signed=False,
        grants_issued=False, file_received=False, content_verified=False, published=False,
    )
