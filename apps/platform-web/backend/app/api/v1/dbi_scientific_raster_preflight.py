"""H14/2H/1: plan técnico SOLO LECTURA para 1 RGB + 6 COG científicos.

Calcula rutas, cuotas y partes a partir del manifiesto inmutable H14/2F.
NO crea sesiones, NO otorga URLs/grants, NO recibe TIFF ni verifica sus bytes.
"""
from __future__ import annotations

import os
from typing import Annotated, Literal
from uuid import NAMESPACE_URL, UUID, uuid5

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session

from app.api.v1.dbi_scientific_manifest_private import (
    _address as _manifest_address, _authorize, _read as _read_manifest,
    _store as _private_store,
)
from app.dbi.asset_multipart_contracts import (
    DBIMultipartChecksumAlgorithm, DBIMultipartChecksumType,
    DBIMultipartRoutingDecision,
)
from app.dbi.asset_multipart_policy import (
    DBI_MULTIPART_DEFAULT_LIMITS, DBIMultipartPolicy, DBIMultipartPolicyError,
)
from app.dbi.authorization import DBIAccessContext
from app.dbi.dependencies import get_dbi_access_context, get_dbi_session
from app.dbi.scientific_intake_scope import INDEXES
from app.dbi.storage_contracts import (
    DBIStorageError, DBIStorageNotFound, DBIStoragePurpose,
)
from app.dbi.storage_policy import DBIStoragePolicy

router = APIRouter(prefix="/dbi", tags=["dbi-scientific-raster-preflight"])
SessionDep = Annotated[Session, Depends(get_dbi_session)]
AccessDep = Annotated[DBIAccessContext, Depends(get_dbi_access_context)]
RASTER_INDEX_ORDER = ("ndvi", "ndre", "gndvi", "evi2", "ci_red_edge", "ci_green")
assert frozenset(RASTER_INDEX_ORDER) == INDEXES


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class PrivateRasterMultipartPlanItem(_Strict):
    role: Literal["rgb", "scientific_cog"]
    index: Literal["ndvi", "ndre", "gndvi", "evi2", "ci_red_edge", "ci_green"] | None
    relative_path: str
    planned_object_id: UUID
    declared_size_bytes: int
    declared_sha256: str
    content_type: Literal["image/tiff"]
    routing: DBIMultipartRoutingDecision
    part_size_bytes: int | None
    part_count: int
    max_grants_per_window: int
    max_client_concurrency: int
    transport_checksum_algorithm: DBIMultipartChecksumAlgorithm
    transport_checksum_type: DBIMultipartChecksumType
    transport_sha256_is_full_object_sha256: Literal[False]
    content_sha256_verified: Literal[False]
    upload_initiated: Literal[False]
    reason_code: str | None


class PrivateRasterMultipartPreflightResponse(_Strict):
    schema_version: Literal["dbi-h14-private-raster-preflight.v1"]
    campaign_id: UUID
    manifest_object_id: UUID
    manifest_sha256: str
    raster_count: Literal[7]
    total_declared_raster_bytes: int
    raster_plans: list[PrivateRasterMultipartPlanItem]
    ready_for_upload: Literal[False]
    sessions_created: Literal[False]
    grants_issued: Literal[False]
    raster_bytes_received: Literal[False]
    raster_content_verified: Literal[False]
    scientific_validated: Literal[False]
    institutional_approved: Literal[False]
    published: Literal[False]


def _hidden() -> HTTPException:
    return HTTPException(404, detail="Preparación raster científica no disponible.")


def _enabled() -> None:
    if (
        os.environ.get("DBI_SCIENTIFIC_RASTER_PREFLIGHT_ENABLED") != "1"
        or os.environ.get("DBI_ENVIRONMENT", "").strip().lower()
        not in {"test", "development", "local"}
    ):
        raise _hidden()


def _raster_address(
    context: DBIAccessContext, organization_ref: str,
    farm_id: UUID, plot_id: UUID, campaign_id: UUID,
    role: str, index: str | None,
):
    if not ((role == "rgb" and index is None) or
            (role == "scientific_cog" and index in INDEXES)):
        raise ValueError("Rol raster científico no disponible.")
    # Una clave de futuro objeto por scope + Campaign + rol + índice.
    # No acepta rutas, claves ni buckets del cliente.
    object_id = uuid5(
        NAMESPACE_URL,
        "dalgoro-dbi:h14:private-original-raster:v1:"
        + "|".join((
            context.tenant_ref, organization_ref, str(farm_id),
            str(plot_id), str(campaign_id), role, index or "-",
        )),
    )
    return DBIStoragePolicy.build_address(
        tenant_ref=context.tenant_ref,
        purpose=DBIStoragePurpose.ANALYSIS_INPUT,
        object_id=object_id,
    )


@router.get(
    "/organizations/{organization_ref}/farms/{farm_id}/plots/{plot_id}"
    "/campaigns/{campaign_id}/scientific-intake/private-raster-multipart-preflight",
    response_model=PrivateRasterMultipartPreflightResponse,
)
def get_private_raster_multipart_preflight(
    organization_ref: str, farm_id: UUID, plot_id: UUID, campaign_id: UUID,
    request: Request, response: Response, session: SessionDep, context: AccessDep,
) -> PrivateRasterMultipartPreflightResponse:
    """MANAGE + Campaign vigente + manifiesto verificado: solo plan, ningún PUT."""
    _enabled()
    _authorize(
        session, context, organization_ref=organization_ref,
        farm_id=farm_id, plot_id=plot_id, campaign_id=campaign_id,
    )
    try:
        manifest, record = _read_manifest(
            _private_store(request),
            _manifest_address(context, organization_ref, farm_id, plot_id, campaign_id),
        )
        scope = manifest.submission.draft.scope
        if (
            scope.tenant_ref != context.tenant_ref
            or scope.organization_ref != organization_ref
            or scope.farm_id != farm_id or scope.plot_id != plot_id
            or scope.campaign_id != campaign_id
        ):
            raise _hidden()
        files = {(file.role, file.index): file for file in manifest.submission.draft.files}
        hashes = {
            (item.role, item.index): item.declared_sha256
            for item in manifest.submission.declared_hashes
        }
        keys = [("rgb", None)] + [
            ("scientific_cog", index) for index in RASTER_INDEX_ORDER
        ]
        plans = []
        total_bytes = 0
        for role, index in keys:
            file = files[(role, index)]
            declared_hash = hashes[(role, index)]
            address = _raster_address(
                context, organization_ref, farm_id, plot_id, campaign_id,
                role, index,
            )
            # No certificar un SHA declarado: usarlo exclusivamente para
            # definir la FUTURA identidad de contenido del objeto.
            DBIStoragePolicy.build_metadata(
                address=address, content_type="image/tiff",
                size_bytes=file.size_bytes, sha256_hex=declared_hash,
            )
            transfer = DBIMultipartPolicy.build_upload_plan(
                size_bytes=file.size_bytes,
                limits=DBI_MULTIPART_DEFAULT_LIMITS,
                checksum_algorithm=DBIMultipartChecksumAlgorithm.SHA256,
                checksum_type=DBIMultipartChecksumType.COMPOSITE,
            )
            plans.append(PrivateRasterMultipartPlanItem(
                role=role, index=index, relative_path=file.relative_path,
                planned_object_id=address.object_id,
                declared_size_bytes=file.size_bytes,
                declared_sha256=declared_hash, content_type="image/tiff",
                routing=transfer.decision,
                part_size_bytes=transfer.part_size_bytes,
                part_count=transfer.part_count,
                max_grants_per_window=transfer.max_grants_per_window,
                max_client_concurrency=transfer.max_client_concurrency,
                transport_checksum_algorithm=transfer.checksum_algorithm,
                transport_checksum_type=transfer.checksum_type,
                transport_sha256_is_full_object_sha256=False,
                content_sha256_verified=False,
                upload_initiated=False, reason_code=(
                    transfer.reason_code.value if transfer.reason_code else None
                ),
            ))
            total_bytes += file.size_bytes
    except DBIStorageNotFound as error:
        # No existe un plan autorizable sin manifiesto previamente recibido.
        raise _hidden() from error
    except (DBIStorageError, DBIMultipartPolicyError, ValueError, KeyError, TypeError) as error:
        raise HTTPException(
            503, detail="El manifiesto o la política multipart no son consistentes.",
        ) from error

    response.headers["Cache-Control"] = "no-store"
    return PrivateRasterMultipartPreflightResponse(
        schema_version="dbi-h14-private-raster-preflight.v1",
        campaign_id=campaign_id, manifest_object_id=record.metadata.address.object_id,
        manifest_sha256=record.metadata.sha256, raster_count=7,
        total_declared_raster_bytes=total_bytes, raster_plans=plans,
        ready_for_upload=False, sessions_created=False, grants_issued=False,
        raster_bytes_received=False, raster_content_verified=False,
        scientific_validated=False, institutional_approved=False, published=False,
    )
