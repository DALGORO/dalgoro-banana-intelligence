"""Servicio de autoridad y registro de productos COG privados DBI."""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.dbi.models.analysis_jobs import AnalysisJob
from app.dbi.models.assets import AnalysisArtifact, AnalysisInputAsset
from app.dbi.raster.contracts import (
    DBIRasterConflict,
    DBIRasterProductCandidate,
    DBIRasterSource,
    DBIRasterSourceKind,
    validate_candidate,
)
from app.dbi.raster.repository import DBIRasterProductRepository
from app.dbi.storage_contracts import (
    DBIPrivateObjectStore,
    DBIStorageError,
    DBIStorageObjectState,
    DBIStoragePurpose,
)
from app.dbi.storage_policy import DBIStoragePolicy


class DBIRasterUnavailable(DBIRasterConflict):
    """La autoridad o el objeto privado no están disponibles para registrar."""


@dataclass(frozen=True, slots=True)
class DBIRasterRegistrationEvidence:
    product_id: UUID
    source_ref: UUID
    source_kind: DBIRasterSourceKind
    created: bool
    size_bytes: int
    sha256: str


class DBIRasterProductService:
    """Verifica source + Storage sin ejecutar procesamiento geoespacial pesado."""

    def __init__(
        self,
        session: Session,
        object_store: DBIPrivateObjectStore,
    ) -> None:
        if not isinstance(session, Session):
            raise DBIRasterConflict("session debe ser Session.")
        self._session = session
        self._store = object_store
        self._repository = DBIRasterProductRepository(session)

    def _input_asset_source(
        self,
        candidate: DBIRasterProductCandidate,
        *,
        tenant_ref: str,
    ) -> DBIRasterSource:
        asset = self._session.execute(
            select(AnalysisInputAsset).where(
                AnalysisInputAsset.id == candidate.source_ref,
                AnalysisInputAsset.tenant_ref == tenant_ref,
            )
        ).scalar_one_or_none()
        if asset is None:
            raise DBIRasterUnavailable("La ortofoto source no está disponible.")
        if (
            asset.asset_kind != "orthophoto"
            or asset.status != "verified"
            or asset.plot_id is None
        ):
            raise DBIRasterConflict(
                "El source debe ser una ortofoto verificada asociada a un lote."
            )
        if asset.sha256 != candidate.source_sha256:
            raise DBIRasterConflict("source_sha256 diverge de la ortofoto registrada.")
        return DBIRasterSource(
            tenant_ref=asset.tenant_ref,
            farm_id=asset.farm_id,
            plot_id=asset.plot_id,
            source_kind=DBIRasterSourceKind.INPUT_ASSET,
            source_ref=asset.id,
            source_sha256=asset.sha256,
        )

    def _artifact_source(
        self,
        candidate: DBIRasterProductCandidate,
        *,
        tenant_ref: str,
    ) -> DBIRasterSource:
        row = self._session.execute(
            select(AnalysisArtifact, AnalysisJob)
            .join(AnalysisJob, AnalysisJob.id == AnalysisArtifact.job_id)
            .where(
                AnalysisArtifact.id == candidate.source_ref,
                AnalysisJob.tenant_ref == tenant_ref,
            )
        ).one_or_none()
        if row is None:
            raise DBIRasterUnavailable("El artifact source no está disponible.")
        artifact, job = row
        if artifact.content_type != "image/tiff":
            raise DBIRasterConflict("El artifact source no es un ráster TIFF.")
        if artifact.sha256 != candidate.source_sha256:
            raise DBIRasterConflict("source_sha256 diverge del artifact persistido.")
        return DBIRasterSource(
            tenant_ref=job.tenant_ref,
            farm_id=job.farm_id,
            plot_id=job.plot_id,
            source_kind=DBIRasterSourceKind.ANALYSIS_ARTIFACT,
            source_ref=artifact.id,
            source_sha256=artifact.sha256,
        )

    def resolve_source(
        self,
        candidate: DBIRasterProductCandidate,
        *,
        tenant_ref: str,
    ) -> DBIRasterSource:
        prepared = validate_candidate(candidate)
        if not isinstance(tenant_ref, str) or not tenant_ref or tenant_ref.strip() != tenant_ref:
            raise DBIRasterConflict("tenant_ref no es canónico.")
        if prepared.source_kind is DBIRasterSourceKind.INPUT_ASSET:
            return self._input_asset_source(prepared, tenant_ref=tenant_ref)
        return self._artifact_source(prepared, tenant_ref=tenant_ref)

    def register_ready(
        self,
        candidate: DBIRasterProductCandidate,
        *,
        tenant_ref: str,
    ) -> DBIRasterRegistrationEvidence:
        prepared = validate_candidate(candidate)
        source = self.resolve_source(prepared, tenant_ref=tenant_ref)
        if (
            source.source_kind is not prepared.source_kind
            or source.source_ref != prepared.source_ref
            or source.source_sha256 != prepared.source_sha256
        ):
            raise DBIRasterConflict("La autoridad source diverge del candidato COG.")

        address = DBIStoragePolicy.build_address(
            tenant_ref=source.tenant_ref,
            purpose=DBIStoragePurpose.RASTER_PRODUCT,
            object_id=prepared.object_id,
        )
        expected = DBIStoragePolicy.build_metadata(
            address=address,
            content_type=prepared.content_type,
            size_bytes=prepared.size_bytes,
            sha256_hex=prepared.sha256,
        )
        try:
            record = self._store.stat(address)
        except DBIStorageError as error:
            raise DBIRasterUnavailable(
                "El COG privado no está disponible para registro."
            ) from error
        if record.state is not DBIStorageObjectState.ACTIVE:
            raise DBIRasterUnavailable("El COG privado no está activo.")
        if record.metadata != expected:
            raise DBIRasterConflict("Storage diverge del manifiesto COG validado.")

        row, created = self._repository.persist_ready(
            source,
            prepared,
            object_key=address.object_key,
        )
        return DBIRasterRegistrationEvidence(
            product_id=row.id,
            source_ref=row.source_ref,
            source_kind=DBIRasterSourceKind(row.source_kind),
            created=created,
            size_bytes=row.size_bytes,
            sha256=row.sha256,
        )
