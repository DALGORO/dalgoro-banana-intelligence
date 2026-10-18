"""H14/2F: manifiesto científico privado, inmutable y declarativo de 13 piezas.

NO carga archivos, no comprueba sus hashes declarados, no valida ciencia ni publica.
La única huella verificada por el servidor es la del JSON del propio manifiesto.
"""
from __future__ import annotations

import json
import os
from hashlib import sha256
from io import BytesIO
from typing import Annotated, Literal
from uuid import NAMESPACE_URL, UUID, uuid5

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from sqlalchemy.orm import Session

from app.dbi.authorization import (
    DBIAccessContext, DBIAccessDenied, DBIAuthorizationPolicy, DBIPermission,
)
from app.dbi.campaigns.contracts import (
    DBICampaignAnalysisType, DBICampaignUnavailable,
)
from app.dbi.campaigns.reader import DBICampaignReader
from app.dbi.dependencies import get_dbi_access_context, get_dbi_session
from app.dbi.scientific_intake_scope import (
    PRE_INTAKE_STATUSES, ROLES, ScientificDraftScopeRequest,
)
from app.dbi.storage_contracts import (
    DBIStorageConflict, DBIStorageError, DBIStorageNotFound,
    DBIStorageObjectRecord, DBIStoragePurpose, DBIStorageWriteRequest,
)
from app.dbi.storage_policy import DBIStoragePolicy, validate_sha256
from app.dbi.storage_s3 import DBIS3ObjectStore

router = APIRouter(prefix="/dbi", tags=["dbi-scientific-manifest-private"])
SessionDep = Annotated[Session, Depends(get_dbi_session)]
AccessDep = Annotated[DBIAccessContext, Depends(get_dbi_access_context)]
BASEPATH = (
    "/organizations/{organization_ref}/farms/{farm_id}/plots/{plot_id}"
    "/campaigns/{campaign_id}/scientific-intake/private-manifest"
)
MAX_QML_BYTES = 2 * 1024 * 1024
MAX_RASTER_BYTES = 10 * 1024 * 1024 * 1024
MAX_BUNDLE_BYTES = 60 * 1024 * 1024 * 1024
MAX_MANIFEST_BYTES = 32 * 1024


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class DeclaredScientificDigest(_Strict):
    role: Literal["rgb", "scientific_cog", "qml_style"]
    index: Literal["ndvi", "ndre", "gndvi", "evi2", "ci_red_edge", "ci_green"] | None
    declared_sha256: str

    @field_validator("declared_sha256")
    @classmethod
    def canonical_hash(cls, value: str) -> str:
        try:
            return validate_sha256(value)
        except DBIStorageConflict as error:
            raise ValueError("SHA-256 declarado debe ser canónico en minúsculas.") from error


class PrivateScientificManifestSubmission(_Strict):
    schema_version: Literal["dbi-h14-private-manifest-submission.v1"]
    source: Literal["local_two_folders_unverified"]
    draft: ScientificDraftScopeRequest
    declared_hashes: list[DeclaredScientificDigest] = Field(min_length=13, max_length=13)

    @model_validator(mode="after")
    def verify_exact_roles_and_quotas(self) -> "PrivateScientificManifestSubmission":
        seen = {(digest.role, digest.index) for digest in self.declared_hashes}
        if len(seen) != 13 or seen != ROLES:
            raise ValueError("Se requieren 13 hashes declarados sin roles duplicados.")
        total = 0
        for file in self.draft.files:
            limit = MAX_QML_BYTES if file.role == "qml_style" else MAX_RASTER_BYTES
            if file.size_bytes > limit:
                raise ValueError("Tamaño declarado excede cuota individual científica.")
            total += file.size_bytes
        if total > MAX_BUNDLE_BYTES:
            raise ValueError("Tamaño declarado excede cuota total científica.")
        return self


class _StoredManifest(_Strict):
    schema_version: Literal["dbi-h14-private-stored-manifest.v1"]
    submitted_by: str = Field(min_length=1, max_length=128)
    submission: PrivateScientificManifestSubmission
    file_bytes_received: Literal[False]
    file_hashes_verified: Literal[False]
    scientific_validated: Literal[False]
    institutional_approved: Literal[False]
    published: Literal[False]


class PrivateScientificManifestReceipt(_Strict):
    schema_version: Literal["dbi-h14-private-manifest-receipt.v1"]
    campaign_id: UUID
    object_id: UUID
    manifest_sha256: str
    manifest_size_bytes: int
    created_at: str
    created: bool
    submitted_by: str
    file_count: Literal[13]
    total_declared_bytes: int
    submission: PrivateScientificManifestSubmission
    manifest_received_privately: Literal[True]
    file_bytes_received: Literal[False]
    file_hashes_verified: Literal[False]
    scientific_validated: Literal[False]
    institutional_approved: Literal[False]
    published: Literal[False]


def _hidden() -> HTTPException:
    return HTTPException(404, detail="Manifiesto científico no disponible.")


def _enabled() -> None:
    # Doble control: la función permanece cerrada aunque se importe el router.
    if (
        os.environ.get("DBI_SCIENTIFIC_MANIFEST_ENABLED") != "1"
        or os.environ.get("DBI_ENVIRONMENT", "").strip().lower()
        not in {"test", "development", "local"}
    ):
        raise _hidden()


def _authorize(
    session: Session, context: DBIAccessContext, *,
    organization_ref: str, farm_id: UUID, plot_id: UUID, campaign_id: UUID,
) -> None:
    try:
        DBIAuthorizationPolicy.require_plot(
            context, tenant_ref=context.tenant_ref, organization_ref=organization_ref,
            farm_id=farm_id, plot_id=plot_id, permission=DBIPermission.MANAGE,
        )
        campaign = DBICampaignReader(session).read_campaign(
            campaign_id=campaign_id, tenant_ref=context.tenant_ref,
            organization_ref=organization_ref, farm_id=farm_id, plot_id=plot_id,
        )
        if (
            campaign.campaign_id != campaign_id
            or campaign.tenant_ref != context.tenant_ref
            or campaign.organization_ref != organization_ref
            or campaign.farm_id != farm_id or campaign.plot_id != plot_id
            or campaign.analysis_type != DBICampaignAnalysisType.MULTISPECTRAL
            or campaign.status not in PRE_INTAKE_STATUSES
            or campaign.approved_at is not None or campaign.published_at is not None
        ):
            raise _hidden()
    except (DBIAccessDenied, DBICampaignUnavailable) as error:
        raise _hidden() from error


def _address(
    context: DBIAccessContext, organization_ref: str,
    farm_id: UUID, plot_id: UUID, campaign_id: UUID,
):
    # Identidad estable por ámbito+Campaign; ningún nombre del cliente en la clave.
    material = "|".join((
        context.tenant_ref, organization_ref, str(farm_id), str(plot_id),
        str(campaign_id),
    ))
    object_id = uuid5(NAMESPACE_URL, "dalgoro:dbi:h14:13-manifest:v1:" + material)
    return DBIStoragePolicy.build_address(
        tenant_ref=context.tenant_ref,
        purpose=DBIStoragePurpose.ANALYSIS_INPUT, object_id=object_id,
    )


def _store(request: Request) -> DBIS3ObjectStore:
    provider = getattr(request.app.state, "dbi_object_store", None)
    if not isinstance(provider, DBIS3ObjectStore) or any(
        not callable(getattr(provider, name, None))
        for name in ("put", "stat", "open_read")
    ):
        raise HTTPException(503, detail="Almacenamiento S3 privado no configurado.")
    return provider


def _canonical_bytes(
    submission: PrivateScientificManifestSubmission, principal_ref: str,
) -> bytes:
    data = submission.model_dump(mode="json")
    data["draft"]["files"].sort(key=lambda item: (item["role"], item["index"] or ""))
    data["declared_hashes"].sort(key=lambda item: (item["role"], item["index"] or ""))
    stored = _StoredManifest(
        schema_version="dbi-h14-private-stored-manifest.v1",
        submitted_by=principal_ref,
        submission=PrivateScientificManifestSubmission.model_validate(data),
        file_bytes_received=False, file_hashes_verified=False,
        scientific_validated=False, institutional_approved=False, published=False,
    )
    return json.dumps(
        stored.model_dump(mode="json"), sort_keys=True,
        separators=(",", ":"), ensure_ascii=False,
    ).encode("utf-8")


def _read(store: DBIS3ObjectStore, address) -> tuple[_StoredManifest, DBIStorageObjectRecord]:
    record = store.stat(address)
    if record.metadata.content_type != "application/json" or record.metadata.size_bytes > MAX_MANIFEST_BYTES:
        raise DBIStorageConflict("El objeto no cumple la política de manifiesto.")
    with store.open_read(address) as stream:
        contents = stream.read(MAX_MANIFEST_BYTES + 1)
    if len(contents) != record.metadata.size_bytes or sha256(contents).hexdigest() != record.metadata.sha256:
        raise DBIStorageConflict("Integridad del manifiesto inválida.")
    parsed = _StoredManifest.model_validate_json(contents)
    if contents != _canonical_bytes(parsed.submission, parsed.submitted_by):
        raise DBIStorageConflict("El manifiesto almacenado no es canónico.")
    return parsed, record


def _receipt(
    *, stored: _StoredManifest, record: DBIStorageObjectRecord, created: bool,
) -> PrivateScientificManifestReceipt:
    return PrivateScientificManifestReceipt(
        schema_version="dbi-h14-private-manifest-receipt.v1",
        campaign_id=stored.submission.draft.scope.campaign_id,
        object_id=record.metadata.address.object_id,
        manifest_sha256=record.metadata.sha256,
        manifest_size_bytes=record.metadata.size_bytes,
        created_at=record.created_at.isoformat(),
        created=created, submitted_by=stored.submitted_by,
        file_count=13,
        total_declared_bytes=sum(x.size_bytes for x in stored.submission.draft.files),
        submission=stored.submission,
        manifest_received_privately=True,
        file_bytes_received=False, file_hashes_verified=False,
        scientific_validated=False, institutional_approved=False, published=False,
    )


@router.put(BASEPATH, response_model=PrivateScientificManifestReceipt)
def put_private_scientific_manifest(
    organization_ref: str, farm_id: UUID, plot_id: UUID,
    campaign_id: UUID, payload: PrivateScientificManifestSubmission,
    request: Request, response: Response, session: SessionDep, context: AccessDep,
) -> PrivateScientificManifestReceipt:
    _enabled()
    _authorize(
        session, context, organization_ref=organization_ref,
        farm_id=farm_id, plot_id=plot_id, campaign_id=campaign_id,
    )
    scope = payload.draft.scope
    if (
        scope.tenant_ref != context.tenant_ref
        or scope.organization_ref != organization_ref
        or scope.farm_id != farm_id or scope.plot_id != plot_id
        or scope.campaign_id != campaign_id
    ):
        raise _hidden()
    contents = _canonical_bytes(payload, context.principal_ref)
    if len(contents) > MAX_MANIFEST_BYTES:
        raise HTTPException(413, detail="El manifiesto supera la cuota de 32 KiB.")
    store = _store(request)
    address = _address(context, organization_ref, farm_id, plot_id, campaign_id)
    metadata = DBIStoragePolicy.build_metadata(
        address=address, content_type="application/json",
        size_bytes=len(contents), sha256_hex=sha256(contents).hexdigest(),
    )
    try:
        result = store.put(DBIStorageWriteRequest(metadata=metadata), BytesIO(contents))
    except DBIStorageConflict as error:
        raise HTTPException(409, detail="Ya existe un manifiesto distinto; no se sobrescribe.") from error
    except DBIStorageError as error:
        raise HTTPException(503, detail="Almacenamiento privado no disponible.") from error
    response.headers["Cache-Control"] = "no-store"
    response.status_code = 201 if result.created else 200
    stored = _StoredManifest.model_validate_json(contents)
    return _receipt(stored=stored, record=result.record, created=result.created)


@router.get(BASEPATH, response_model=PrivateScientificManifestReceipt)
def get_private_scientific_manifest(
    organization_ref: str, farm_id: UUID, plot_id: UUID,
    campaign_id: UUID, request: Request, response: Response,
    session: SessionDep, context: AccessDep,
) -> PrivateScientificManifestReceipt:
    _enabled()
    _authorize(
        session, context, organization_ref=organization_ref,
        farm_id=farm_id, plot_id=plot_id, campaign_id=campaign_id,
    )
    try:
        stored, record = _read(
            _store(request), _address(context, organization_ref, farm_id, plot_id, campaign_id),
        )
        scope = stored.submission.draft.scope
        if (
            scope.tenant_ref != context.tenant_ref
            or scope.organization_ref != organization_ref
            or scope.farm_id != farm_id or scope.plot_id != plot_id
            or scope.campaign_id != campaign_id
        ):
            raise _hidden()
    except DBIStorageNotFound as error:
        raise _hidden() from error
    except (DBIStorageError, ValueError) as error:
        raise HTTPException(503, detail="Manifiesto privado inconsistente o inaccesible.") from error
    response.headers["Cache-Control"] = "no-store"
    return _receipt(stored=stored, record=record, created=False)
