"""H14/2H-2D/3F: constancia de segundo revisor, privada y NO autorizante.

Verifica la observación JSON inmutable (no el estado actual de S3).
Nunca firma, concede permisos ni ejecuta abortos.
"""
from __future__ import annotations

from hashlib import sha256
from io import BytesIO
import json
import os
from types import SimpleNamespace
from typing import Annotated, Literal
from uuid import NAMESPACE_URL, UUID, uuid5

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict, field_validator
from sqlalchemy.orm import Session

from app.api.v1.dbi_scientific_raster_cleanup_evidence import (
    MAX_EVIDENCE_BYTES, _StoredEvidence, _address as _evidence_address,
    _bytes as _evidence_bytes, _private_s3_store,
)
from app.api.v1.dbi_scientific_raster_postapproval_audit import _locked_approved_campaign
from app.api.v1.dbi_scientific_raster_reservations import (
    RasterIndex, RasterRole, _role_index,
)
from app.dbi.authorization import DBIAccessContext
from app.dbi.dependencies import get_dbi_access_context, get_dbi_session
from app.dbi.storage_contracts import (
    DBIStorageConflict, DBIStorageError, DBIStorageNotFound,
    DBIStoragePurpose, DBIStorageWriteRequest,
)
from app.dbi.storage_policy import DBIStoragePolicy, validate_sha256

router = APIRouter(prefix="/dbi", tags=["dbi-scientific-independent-evidence-review"])
SessionDep = Annotated[Session, Depends(get_dbi_session)]
AccessDep = Annotated[DBIAccessContext, Depends(get_dbi_access_context)]
MAX_REVIEW_BYTES = 8 * 1024


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class IndependentReviewSubmission(_Strict):
    schema_version: Literal["dbi-h14-independent-observation-review-request.v1"]
    original_actor_ref: str
    evidence_sha256: str
    original_object_sha256: str
    acknowledgement: Literal["reviewed_snapshot_not_cleanup_authorization"]

    @field_validator("original_actor_ref")
    @classmethod
    def valid_actor(cls, value: str) -> str:
        if (
            not 1 <= len(value) <= 128 or value != value.strip()
            or any(ord(ch) < 32 or ord(ch) == 127 for ch in value)
        ):
            raise ValueError("Referencia de operador original inválida.")
        return value

    @field_validator("evidence_sha256", "original_object_sha256")
    @classmethod
    def valid_sha(cls, value: str) -> str:
        try:
            return validate_sha256(value)
        except DBIStorageConflict as exc:
            raise ValueError("SHA-256 canónico requerido.") from exc


class _StoredIndependentReview(_Strict):
    schema_version: Literal["dbi-h14-independent-observation-review-stored.v1"]
    tenant_ref: str
    organization_ref: str
    farm_id: UUID
    plot_id: UUID
    campaign_id: UUID
    role: RasterRole
    index: RasterIndex | None
    original_actor_ref: str
    reviewer_actor_ref: str
    original_object_id: UUID
    original_object_sha256: str
    evidence_sha256: str
    campaign_status: Literal["APPROVED", "PUBLISHED"]
    acknowledgement: Literal["reviewed_snapshot_not_cleanup_authorization"]
    independent_actor: Literal[True]
    snapshot_only: Literal[True]
    evidence_signed: Literal[False]
    cleanup_authorized: Literal[False]
    cleanup_executed: Literal[False]
    grants_issued: Literal[False]
    file_received: Literal[False]
    content_verified: Literal[False]
    published: Literal[False]


class IndependentReviewReceipt(_Strict):
    schema_version: Literal["dbi-h14-independent-observation-review-receipt.v1"]
    review_object_id: UUID
    review_object_sha256: str
    original_object_sha256: str
    evidence_sha256: str
    recorded_at: str
    created: bool
    independent_actor: Literal[True]
    review_recorded: Literal[True]
    snapshot_only: Literal[True]
    evidence_signed: Literal[False]
    cleanup_authorized: Literal[False]
    cleanup_executed: Literal[False]
    grants_issued: Literal[False]
    file_received: Literal[False]
    content_verified: Literal[False]
    published: Literal[False]


def _enabled() -> None:
    required = (
        "DBI_SCIENTIFIC_CLEANUP_PEER_REVIEW_ENABLED",
        "DBI_SCIENTIFIC_CLEANUP_EVIDENCE_ENABLED",
        "DBI_SCIENTIFIC_RASTER_CLEANUP_PLAN_ENABLED",
        "DBI_SCIENTIFIC_RASTER_POSTAPPROVAL_AUDIT_ENABLED",
    )
    if any(os.environ.get(flag) != "1" for flag in required) or (
        os.environ.get("DBI_ENVIRONMENT", "").strip().lower()
        not in {"test", "development", "local"}
    ):
        raise HTTPException(404, detail="Revisión independiente no disponible.")


def _read_json(store, address, *, max_bytes: int):
    record = store.stat(address)
    meta = record.metadata
    if (
        meta.address != address or meta.content_type != "application/json"
        or not 0 < meta.size_bytes <= max_bytes
    ):
        raise DBIStorageConflict("Metadatos de archivo privado divergentes.")
    with store.open_read(address) as stream:
        raw = stream.read(max_bytes + 1)
        extra = stream.read(1)
    if (
        not isinstance(raw, bytes) or extra not in (b"", None)
        or len(raw) != meta.size_bytes
        or sha256(raw).hexdigest() != meta.sha256
    ):
        raise DBIStorageConflict("Contenido privado no verificable.")
    return record, raw


def _canonical(saved: BaseModel) -> bytes:
    return json.dumps(
        saved.model_dump(mode="json"), ensure_ascii=False,
        sort_keys=True, separators=(",", ":"),
    ).encode("utf-8")


def _review_address(context, organization_ref, farm_id, plot_id, campaign_id,
                    role, index, original_object_id, original_object_sha256):
    identity = "|".join((
        context.tenant_ref, organization_ref, str(farm_id), str(plot_id),
        str(campaign_id), role, index or "-", context.principal_ref,
        str(original_object_id), original_object_sha256,
    ))
    return DBIStoragePolicy.build_address(
        tenant_ref=context.tenant_ref,
        purpose=DBIStoragePurpose.ANALYSIS_INPUT,
        object_id=uuid5(NAMESPACE_URL, "dalgoro-dbi:h14:independent-review:v1:" + identity),
    )


@router.put(
    "/organizations/{organization_ref}/farms/{farm_id}/plots/{plot_id}"
    "/campaigns/{campaign_id}/scientific-intake/private-raster-cleanup-peer-review"
    "/{role}/{index}",
    response_model=IndependentReviewReceipt,
)
def record_independent_review(
    organization_ref: str, farm_id: UUID, plot_id: UUID, campaign_id: UUID,
    role: RasterRole, index: str, payload: IndependentReviewSubmission,
    request: Request, response: Response, session: SessionDep, context: AccessDep,
) -> IndependentReviewReceipt:
    _enabled()
    response.headers["Cache-Control"] = "no-store"
    mapped_index = None if index == "_" else index
    try:
        status = _locked_approved_campaign(
            session, context, organization_ref, farm_id, plot_id, campaign_id,
        )
        _role_index(role, mapped_index)
        if context.principal_ref == payload.original_actor_ref:
            raise HTTPException(409, detail="Se requiere un segundo operador distinto.")

        store = _private_s3_store(request)  # Only real private S3; CI injects fake.
        original_context = SimpleNamespace(
            tenant_ref=context.tenant_ref, principal_ref=payload.original_actor_ref,
        )
        original_address = _evidence_address(
            original_context, organization_ref, farm_id, plot_id,
            campaign_id, role, mapped_index, payload.evidence_sha256,
        )
        original_record, original_bytes = _read_json(
            store, original_address, max_bytes=MAX_EVIDENCE_BYTES,
        )
        original = _StoredEvidence.model_validate_json(original_bytes)
        if (
            original_bytes != _evidence_bytes(original)
            or original_record.metadata.sha256 != payload.original_object_sha256
            or original.tenant_ref != context.tenant_ref
            or original.organization_ref != organization_ref
            or original.farm_id != farm_id or original.plot_id != plot_id
            or original.campaign_id != campaign_id
            or original.role != role or original.index != mapped_index
            or original.actor_ref != payload.original_actor_ref
            or original.evidence_sha256 != payload.evidence_sha256
            or original.campaign_status != status
            or not original.review_observation_only
            or any((original.cleanup_authorized, original.cleanup_executed,
                    original.signed, original.file_received,
                    original.content_verified, original.published))
        ):
            raise DBIStorageConflict("Observación original divergente o desactualizada.")

        saved = _StoredIndependentReview(
            schema_version="dbi-h14-independent-observation-review-stored.v1",
            tenant_ref=context.tenant_ref, organization_ref=organization_ref,
            farm_id=farm_id, plot_id=plot_id, campaign_id=campaign_id,
            role=role, index=mapped_index,
            original_actor_ref=payload.original_actor_ref,
            reviewer_actor_ref=context.principal_ref,
            original_object_id=original_record.metadata.address.object_id,
            original_object_sha256=original_record.metadata.sha256,
            evidence_sha256=payload.evidence_sha256,
            campaign_status=status,
            acknowledgement=payload.acknowledgement,
            independent_actor=True, snapshot_only=True,
            evidence_signed=False, cleanup_authorized=False,
            cleanup_executed=False, grants_issued=False, file_received=False,
            content_verified=False, published=False,
        )
        raw = _canonical(saved)
        if len(raw) > MAX_REVIEW_BYTES:
            raise HTTPException(413, detail="Constancia supera cuota privada.")
        address = _review_address(
            context, organization_ref, farm_id, plot_id, campaign_id,
            role, mapped_index, original_address.object_id,
            original_record.metadata.sha256,
        )
        metadata = DBIStoragePolicy.build_metadata(
            address=address, content_type="application/json",
            size_bytes=len(raw), sha256_hex=sha256(raw).hexdigest(),
        )
        written = store.put(DBIStorageWriteRequest(metadata=metadata), BytesIO(raw))
        verified, readback = _read_json(store, address, max_bytes=MAX_REVIEW_BYTES)
        parsed = _StoredIndependentReview.model_validate_json(readback)
        if readback != raw or _canonical(parsed) != raw:
            raise DBIStorageConflict("Constancia privada no coincide con la escrita.")
    except HTTPException:
        raise
    except DBIStorageNotFound as exc:
        raise HTTPException(404, detail="Observación original no disponible.") from exc
    except DBIStorageConflict as exc:
        raise HTTPException(409, detail="Evidencia de revisión contradictoria.") from exc
    except (DBIStorageError, ValueError, TypeError, KeyError) as exc:
        raise HTTPException(503, detail="Revisión privada no verificable.") from exc
    finally:
        # Always release Campaign row lock; this endpoint never commits SQL.
        session.rollback()

    response.status_code = 201 if written.created else 200
    return IndependentReviewReceipt(
        schema_version="dbi-h14-independent-observation-review-receipt.v1",
        review_object_id=verified.metadata.address.object_id,
        review_object_sha256=verified.metadata.sha256,
        original_object_sha256=original_record.metadata.sha256,
        evidence_sha256=payload.evidence_sha256,
        recorded_at=verified.created_at.isoformat(), created=written.created,
        independent_actor=True, review_recorded=True, snapshot_only=True,
        evidence_signed=False, cleanup_authorized=False,
        cleanup_executed=False, grants_issued=False,
        file_received=False, content_verified=False, published=False,
    )
