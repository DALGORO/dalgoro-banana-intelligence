"""H14/2G: conciliación privada SOLO LECTURA de seis QML y manifiesto 13 piezas.

No concede autenticidad de origen, aprobación institucional o publicación.
La identidad de objeto QML replica el contrato inmutable H14/2E (PR #257).
"""
from __future__ import annotations

import os
from hashlib import sha256
from typing import Annotated, Literal
from uuid import NAMESPACE_URL, UUID, uuid5

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session

from app.api.v1.dbi_scientific_manifest_private import (
    MAX_QML_BYTES, _address as manifest_address, _authorize,
    _read as read_manifest,
)
from app.dbi.authorization import DBIAccessContext
from app.dbi.dependencies import get_dbi_access_context, get_dbi_session
from app.dbi.scientific_intake_scope import INDEXES
from app.dbi.storage_contracts import (
    DBIStorageConflict, DBIStorageError, DBIStorageNotFound, DBIStoragePurpose,
)
from app.dbi.storage_policy import DBIStoragePolicy
from app.dbi.storage_s3 import DBIS3ObjectStore

router = APIRouter(prefix="/dbi", tags=["dbi-scientific-qml-reconciliation"])
SessionDep = Annotated[Session, Depends(get_dbi_session)]
AccessDep = Annotated[DBIAccessContext, Depends(get_dbi_access_context)]
QML_INDEX_ORDER = ("ndvi", "ndre", "gndvi", "evi2", "ci_red_edge", "ci_green")
assert frozenset(QML_INDEX_ORDER) == INDEXES


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class QMLReconciliationItem(_Strict):
    index: Literal["ndvi", "ndre", "gndvi", "evi2", "ci_red_edge", "ci_green"]
    relative_path: str
    expected_size_bytes: int
    declared_sha256: str
    observed_size_bytes: int | None
    verified_sha256: str | None
    state: Literal["missing", "size_mismatch", "sha256_mismatch", "matched"]


class PrivateQMLReconciliationReport(_Strict):
    schema_version: Literal["dbi-h14-private-qml-reconciliation.v1"]
    campaign_id: UUID
    manifest_object_id: UUID
    manifest_sha256: str
    qml_results: list[QMLReconciliationItem]
    matched_count: int
    missing_count: int
    mismatch_count: int
    all_six_qml_match_manifest: bool
    all_thirteen_files_received: Literal[False]
    scientific_validated: Literal[False]
    institutional_approved: Literal[False]
    published: Literal[False]


def _hidden() -> HTTPException:
    return HTTPException(404, detail="Conciliación científica no disponible.")


def _enabled() -> None:
    if (
        os.environ.get("DBI_SCIENTIFIC_QML_RECONCILIATION_ENABLED") != "1"
        or os.environ.get("DBI_ENVIRONMENT", "").strip().lower()
        not in {"test", "development", "local"}
    ):
        raise _hidden()


def _store(request: Request) -> DBIS3ObjectStore:
    store = getattr(request.app.state, "dbi_object_store", None)
    if not isinstance(store, DBIS3ObjectStore) or any(
        not callable(getattr(store, name, None))
        for name in ("stat", "open_read")
    ):
        raise HTTPException(503, detail="Almacenamiento S3 privado no configurado.")
    return store


def _qml_address(
    context: DBIAccessContext, organization_ref: str,
    farm_id: UUID, plot_id: UUID, campaign_id: UUID, index: str,
):
    # Esta identidad debe permanecer byte-a-byte compatible con H14/2E.
    if index not in INDEXES:
        raise DBIStorageConflict("Índice científico inválido.")
    object_id = uuid5(
        NAMESPACE_URL,
        "dalgoro-dbi:h14:private-original-qml:v1:"
        + "|".join((
            context.tenant_ref, organization_ref, str(farm_id),
            str(plot_id), str(campaign_id), index,
        )),
    )
    return DBIStoragePolicy.build_address(
        tenant_ref=context.tenant_ref,
        purpose=DBIStoragePurpose.ANALYSIS_INPUT,
        object_id=object_id,
    )


def _check_qml(
    store: DBIS3ObjectStore, *, address, index: str,
    relative_path: str, size: int, declared_hash: str,
) -> QMLReconciliationItem:
    fields = dict(
        index=index, relative_path=relative_path,
        expected_size_bytes=size, declared_sha256=declared_hash,
    )
    try:
        record = store.stat(address)
    except DBIStorageNotFound:
        return QMLReconciliationItem(
            **fields, observed_size_bytes=None, verified_sha256=None,
            state="missing",
        )
    metadata = record.metadata
    if (
        metadata.address != address
        or metadata.content_type != "application/octet-stream"
        or metadata.size_bytes > MAX_QML_BYTES
    ):
        raise DBIStorageConflict("El objeto QML no cumple la política privada.")

    # Una lectura íntegra y acotada, no confiar solo en los metadatos HEAD de S3.
    with store.open_read(address) as stream:
        payload = stream.read(MAX_QML_BYTES + 1)
        extra = stream.read(1)
    if (
        not isinstance(payload, bytes) or extra not in (b"", None)
        or len(payload) != metadata.size_bytes
        or sha256(payload).hexdigest() != metadata.sha256
    ):
        raise DBIStorageConflict("El contenido QML no coincide con el objeto S3.")
    verified_hash = sha256(payload).hexdigest()
    state = (
        "size_mismatch" if len(payload) != size else
        "sha256_mismatch" if verified_hash != declared_hash else
        "matched"
    )
    return QMLReconciliationItem(
        **fields, observed_size_bytes=len(payload),
        verified_sha256=verified_hash, state=state,
    )


@router.get(
    "/organizations/{organization_ref}/farms/{farm_id}/plots/{plot_id}"
    "/campaigns/{campaign_id}/scientific-intake/private-qml-reconciliation",
    response_model=PrivateQMLReconciliationReport,
)
def get_private_qml_reconciliation(
    organization_ref: str, farm_id: UUID, plot_id: UUID, campaign_id: UUID,
    request: Request, response: Response, session: SessionDep, context: AccessDep,
) -> PrivateQMLReconciliationReport:
    _enabled()
    _authorize(
        session, context, organization_ref=organization_ref,
        farm_id=farm_id, plot_id=plot_id, campaign_id=campaign_id,
    )
    store = _store(request)
    try:
        manifest, record = read_manifest(
            store, manifest_address(
                context, organization_ref, farm_id, plot_id, campaign_id,
            ),
        )
        scope = manifest.submission.draft.scope
        if (
            scope.tenant_ref != context.tenant_ref
            or scope.organization_ref != organization_ref
            or scope.farm_id != farm_id or scope.plot_id != plot_id
            or scope.campaign_id != campaign_id
        ):
            raise _hidden()

        expected = {
            (item.role, item.index): item
            for item in manifest.submission.draft.files
        }
        digests = {
            (item.role, item.index): item.declared_sha256
            for item in manifest.submission.declared_hashes
        }
        results = [
            _check_qml(
                store,
                address=_qml_address(
                    context, organization_ref, farm_id, plot_id, campaign_id, index,
                ),
                index=index,
                relative_path=expected[("qml_style", index)].relative_path,
                size=expected[("qml_style", index)].size_bytes,
                declared_hash=digests[("qml_style", index)],
            )
            for index in QML_INDEX_ORDER
        ]
    except DBIStorageNotFound as error:
        # Ausencia de manifiesto NO equivale a seis QML faltantes.
        raise _hidden() from error
    except (DBIStorageError, ValueError, KeyError, TypeError) as error:
        raise HTTPException(
            503, detail="Conciliación privada inaccesible o sin integridad.",
        ) from error

    matched = sum(item.state == "matched" for item in results)
    missing = sum(item.state == "missing" for item in results)
    mismatch = len(results) - matched - missing
    response.headers["Cache-Control"] = "no-store"
    return PrivateQMLReconciliationReport(
        schema_version="dbi-h14-private-qml-reconciliation.v1",
        campaign_id=campaign_id,
        manifest_object_id=record.metadata.address.object_id,
        manifest_sha256=record.metadata.sha256,
        qml_results=results,
        matched_count=matched, missing_count=missing, mismatch_count=mismatch,
        all_six_qml_match_manifest=matched == 6,
        all_thirteen_files_received=False, scientific_validated=False,
        institutional_approved=False, published=False,
    )
