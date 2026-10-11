"""Trabajador independiente para preparar originales GIS, sin autoridad de publicación.

El proceso web no debe llamar process_one(). El despliegue posterior
ejecutará este servicio en el entorno GIS con un adaptador de conversión.
"""
from __future__ import annotations

import json
import tempfile
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from hashlib import sha256
from pathlib import Path
from typing import Callable
from uuid import UUID, uuid4

from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session

from app.dbi.models.portal_gis_imports import DBIPortalGISImport, DBIPortalGISPreview
from app.dbi.portal_vector_validation import DBIPortalVectorInvalid, MAX_VECTOR_BYTES, validate_portal_geojson
from app.dbi.storage_contracts import DBIPrivateObjectStore, DBIStorageError, DBIStoragePurpose
from app.dbi.storage_policy import DBIStoragePolicy

MAX_ATTEMPTS = 3
STALE_AFTER = timedelta(minutes=15)


class DBIPortalGISWorkerFailure(RuntimeError):
    pass


@dataclass(frozen=True)
class GISClaim:
    import_id: UUID
    processing_ref: UUID
    tenant_ref: str
    source_object_id: UUID
    source_format: str
    sha256: str
    size_bytes: int
    created_at: datetime


class DBIPortalGISPreparationWorker:
    """Ejecuta un solo claim a la vez. Ninguna ruta FastAPI importa GDAL."""

    def __init__(
        self,
        session_factory: Callable[[], Session],
        store: DBIPrivateObjectStore,
        converter: Callable[[Path, Path], tuple[Path, Path]],
        *,
        workspace_root: Path,
        clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
    ) -> None:
        self.session_factory = session_factory
        self.store = store
        self.converter = converter
        self.workspace_root = Path(workspace_root).resolve()
        self.clock = clock

    def claim_one(self, *, tenant_ref: str) -> GISClaim | None:
        if not tenant_ref or len(tenant_ref) > 128:
            raise ValueError("Se requiere tenant_ref no vacío y acotado.")
        now = self.clock()
        if now.tzinfo is None:
            raise ValueError("El reloj debe tener zona horaria.")
        with self.session_factory() as session:
            row = session.execute(
                select(DBIPortalGISImport)
                .where(
                    DBIPortalGISImport.tenant_ref == tenant_ref,
                    DBIPortalGISImport.attempt_count < MAX_ATTEMPTS,
                    or_(
                        DBIPortalGISImport.status == "received",
                        and_(
                            DBIPortalGISImport.status == "processing",
                            DBIPortalGISImport.processing_started_at < now - STALE_AFTER,
                        ),
                    ),
                )
                .order_by(DBIPortalGISImport.created_at, DBIPortalGISImport.id)
                .limit(1)
                .with_for_update(skip_locked=True)
            ).scalar_one_or_none()
            if row is None:
                return None
            row.status = "processing"
            row.processing_started_at = now
            row.processing_ref = uuid4()
            row.attempt_count += 1
            claim = GISClaim(
                import_id=row.id, processing_ref=row.processing_ref,
                tenant_ref=row.tenant_ref, source_object_id=row.source_object_id,
                source_format=row.source_format, sha256=row.sha256,
                size_bytes=row.size_bytes, created_at=row.created_at,
            )
            session.commit()
            return claim

    def _prepare(self, claim: GISClaim) -> tuple[str, str, int]:
        self.workspace_root.mkdir(parents=True, exist_ok=True)
        address = DBIStoragePolicy.build_address(
            tenant_ref=claim.tenant_ref,
            purpose=DBIStoragePurpose.TECHNICAL_SOURCE,
            object_id=claim.source_object_id,
        )
        expected = DBIStoragePolicy.build_metadata(
            address=address,
            content_type="application/geopackage+sqlite3" if claim.source_format == "gpkg" else "application/zip",
            size_bytes=claim.size_bytes,
            sha256_hex=claim.sha256,
        )
        with tempfile.TemporaryDirectory(prefix="dbi-gis-", dir=self.workspace_root) as directory:
            root = Path(directory)
            source = root / ("input.gpkg" if claim.source_format == "gpkg" else "input.zip")
            with source.open("xb") as destination:
                record = self.store.copy_to(address, destination)
                if record.metadata != expected:
                    raise DBIPortalGISWorkerFailure("Fuente privada distinta de su manifiesto.")
            if source.stat().st_size != claim.size_bytes:
                raise DBIPortalGISWorkerFailure("Fuente incompleta.")
            with source.open("rb") as stream:
                digest = sha256()
                for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                    digest.update(chunk)
                if digest.hexdigest() != claim.sha256:
                    raise DBIPortalGISWorkerFailure("Integridad SHA256 del origen inválida.")
            output_dir = root / "out"
            output_dir.mkdir(mode=0o700)
            output, manifest_file = self.converter(source, output_dir)
            output = Path(output).resolve()
            manifest_file = Path(manifest_file).resolve()
            if (
                output.parent != output_dir.resolve()
                or manifest_file.parent != output_dir.resolve()
                or output.is_symlink() or manifest_file.is_symlink()
                or not output.is_file() or not manifest_file.is_file()
                or output.stat().st_size > MAX_VECTOR_BYTES
                or manifest_file.stat().st_size > 16384
            ):
                raise DBIPortalGISWorkerFailure("Derivado externo o sobredimensionado.")
            manifest = json.loads(manifest_file.read_text(encoding="utf-8"))
            raw = output.read_bytes()
            parsed = validate_portal_geojson(raw)
            if (
                manifest.get("schema_version") != "dbi-portal-gis-conversion.v1"
                or manifest.get("source_sha256") != claim.sha256
                or manifest.get("source_size_bytes") != claim.size_bytes
                or manifest.get("output_sha256") != sha256(raw).hexdigest()
                or manifest.get("output_crs") != "EPSG:4326"
                or manifest.get("feature_count") != parsed.feature_count
                or manifest.get("captured_at") is not None
            ):
                raise DBIPortalGISWorkerFailure("Manifiesto de conversión no concuerda.")
            return parsed.geojson_text, parsed.source_sha256, parsed.feature_count

    def _complete(self, claim: GISClaim, result: tuple[str, str, int] | None) -> bool:
        """Fencing: ningún resultado de un intento vencido puede modificar la fila."""
        with self.session_factory() as session:
            row = session.execute(
                select(DBIPortalGISImport).where(
                    DBIPortalGISImport.id == claim.import_id,
                    DBIPortalGISImport.tenant_ref == claim.tenant_ref,
                ).with_for_update()
            ).scalar_one_or_none()
            if (
                row is None or row.status != "processing"
                or row.processing_ref != claim.processing_ref
                or row.source_object_id != claim.source_object_id
                or row.sha256 != claim.sha256
            ):
                return False
            if result is None:
                # El original permanece privado; el motivo técnico jamás se expone.
                row.status = "failed"
            else:
                text, digest, count = result
                existing = session.get(DBIPortalGISPreview, claim.import_id)
                if existing is None:
                    session.add(DBIPortalGISPreview(
                        import_id=claim.import_id, geojson_text=text,
                        sha256=digest, feature_count=count,
                    ))
                elif (existing.geojson_text, existing.sha256, existing.feature_count) != result:
                    raise DBIPortalGISWorkerFailure("Preview existente divergente.")
                row.status = "prepared"
            row.processing_ref = None
            row.processing_started_at = None
            session.commit()
            return True

    def process_one(self, *, tenant_ref: str) -> str | None:
        """Solo prepara; nunca inserta en DBIPortalVectorLayer."""
        claim = self.claim_one(tenant_ref=tenant_ref)
        if claim is None:
            return None
        try:
            preview = self._prepare(claim)
        except (DBIStorageError, DBIPortalGISWorkerFailure, DBIPortalVectorInvalid, ValueError, OSError, RuntimeError):
            self._complete(claim, None)
            return "failed"
        return "prepared" if self._complete(claim, preview) else "lease_lost"
