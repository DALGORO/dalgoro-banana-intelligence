"""Preparación local de COG RGB para la primera prueba real DBI.

El backend coordina identidad, Storage y persistencia, pero delega Rasterio/GDAL
a flight_test_cog.py ejecutado con el Python del motor Density.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import shutil
import subprocess
from tempfile import mkdtemp
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.dbi.models.assets import AnalysisInputAsset
from app.dbi.models.raster_products import DBIRasterProduct
from app.dbi.raster.contracts import (
    DBIRasterConflict,
    DBIRasterProductKind,
    DBIRasterSourceKind,
    raster_product_id,
)
from app.dbi.raster.manifest import prepare_candidate_from_manifest
from app.dbi.raster.service import DBIRasterProductService, DBIRasterUnavailable
from app.dbi.storage_contracts import (
    DBIStorageError,
    DBIStoragePurpose,
    DBIStorageWriteRequest,
)
from app.dbi.storage_local import DBILocalObjectStore
from app.dbi.storage_policy import DBIStoragePolicy


PROFILE_VERSION = "cog_v1"
_MAX_MANIFEST_BYTES = 64 * 1024


class DBIPilotRasterError(RuntimeError):
    """Error operativo acotado del puente local Raster."""


class DBIPilotRasterUnavailable(DBIPilotRasterError):
    """Falta runtime, fuente o producto requerido."""


class DBIPilotRasterConflict(DBIPilotRasterError):
    """La fuente o el resultado divergen de la autoridad DBI."""


@dataclass(frozen=True, slots=True)
class DBIPilotRasterResult:
    product_id: UUID
    created: bool
    status: str
    source_asset_id: UUID
    profile_version: str
    size_bytes: int
    sha256: str
    crs: str
    width: int
    height: int
    band_count: int


def _ready_result(
    row: DBIRasterProduct,
    *,
    source_asset_id: UUID,
) -> DBIPilotRasterResult:
    return DBIPilotRasterResult(
        product_id=row.id,
        created=False,
        status=row.status,
        source_asset_id=source_asset_id,
        profile_version=row.profile_version,
        size_bytes=row.size_bytes,
        sha256=row.sha256,
        crs=row.crs,
        width=row.width,
        height=row.height,
        band_count=row.band_count,
    )


class DBIPilotRasterBuilder:
    """Convierte una ortofoto verificada a COG privado de forma recuperable."""

    def __init__(
        self,
        session: Session,
        store: DBILocalObjectStore,
        *,
        raster_python: str | Path,
        flight_test_script: str | Path,
        timeout_seconds: int = 1800,
    ) -> None:
        if not isinstance(session, Session):
            raise TypeError("session debe ser Session.")
        if not isinstance(store, DBILocalObjectStore):
            raise TypeError("store debe ser DBILocalObjectStore.")

        python = Path(raster_python).expanduser().resolve(strict=False)
        script = Path(flight_test_script).expanduser().resolve(strict=False)
        if not python.is_file():
            raise DBIPilotRasterUnavailable("Python Raster/Density no disponible.")
        if not script.is_file():
            raise DBIPilotRasterUnavailable("flight_test_cog.py no disponible.")
        if (
            not isinstance(timeout_seconds, int)
            or isinstance(timeout_seconds, bool)
            or timeout_seconds <= 0
        ):
            raise ValueError("timeout_seconds debe ser entero positivo.")

        self._session = session
        self._store = store
        self._python = python
        self._script = script
        self._timeout_seconds = timeout_seconds

    def _source(
        self,
        *,
        tenant_ref: str,
        farm_id: UUID,
        plot_id: UUID,
        asset_id: UUID,
    ) -> AnalysisInputAsset:
        asset = self._session.execute(
            select(AnalysisInputAsset).where(
                AnalysisInputAsset.id == asset_id,
                AnalysisInputAsset.tenant_ref == tenant_ref,
                AnalysisInputAsset.farm_id == farm_id,
                AnalysisInputAsset.plot_id == plot_id,
                AnalysisInputAsset.asset_kind == "orthophoto",
                AnalysisInputAsset.status == "verified",
            )
        ).scalar_one_or_none()
        if asset is None:
            raise DBIPilotRasterUnavailable(
                "Ortofoto verificada no disponible en este lote."
            )
        return asset

    def _existing(
        self,
        *,
        asset: AnalysisInputAsset,
        tenant_ref: str,
        farm_id: UUID,
        plot_id: UUID,
    ) -> DBIPilotRasterResult | None:
        product_id = raster_product_id(
            source_kind=DBIRasterSourceKind.INPUT_ASSET,
            source_ref=asset.id,
            source_sha256=asset.sha256,
            product_kind=DBIRasterProductKind.RGB_VISUAL,
            profile_version=PROFILE_VERSION,
        )
        row = self._session.execute(
            select(DBIRasterProduct).where(
                DBIRasterProduct.id == product_id,
                DBIRasterProduct.tenant_ref == tenant_ref,
                DBIRasterProduct.farm_id == farm_id,
                DBIRasterProduct.plot_id == plot_id,
                DBIRasterProduct.source_kind
                == DBIRasterSourceKind.INPUT_ASSET.value,
                DBIRasterProduct.source_ref == asset.id,
                DBIRasterProduct.source_sha256 == asset.sha256,
                DBIRasterProduct.product_kind
                == DBIRasterProductKind.RGB_VISUAL.value,
                DBIRasterProduct.profile_version == PROFILE_VERSION,
                DBIRasterProduct.status == "ready",
            )
        ).scalar_one_or_none()
        if row is None:
            return None

        address = DBIStoragePolicy.build_address(
            tenant_ref=tenant_ref,
            purpose=DBIStoragePurpose.RASTER_PRODUCT,
            object_id=row.id,
        )
        try:
            record = self._store.stat(address)
        except Exception as error:
            raise DBIPilotRasterConflict(
                "El producto Raster ready no está íntegro en Storage."
            ) from error
        if (
            record.metadata.content_type != row.content_type
            or record.metadata.size_bytes != row.size_bytes
            or record.metadata.sha256 != row.sha256
        ):
            raise DBIPilotRasterConflict(
                "Storage diverge del producto Raster ready."
            )
        return _ready_result(row, source_asset_id=asset.id)

    def prepare_rgb(
        self,
        *,
        tenant_ref: str,
        farm_id: UUID,
        plot_id: UUID,
        asset_id: UUID,
    ) -> DBIPilotRasterResult:
        asset = self._source(
            tenant_ref=tenant_ref,
            farm_id=farm_id,
            plot_id=plot_id,
            asset_id=asset_id,
        )

        replay = self._existing(
            asset=asset,
            tenant_ref=tenant_ref,
            farm_id=farm_id,
            plot_id=plot_id,
        )
        if replay is not None:
            return replay

        input_address = DBIStoragePolicy.build_address(
            tenant_ref=tenant_ref,
            purpose=DBIStoragePurpose.ANALYSIS_INPUT,
            object_id=asset.id,
        )
        if asset.object_key != input_address.object_key:
            raise DBIPilotRasterConflict(
                "La ortofoto no conserva su dirección privada canónica."
            )
        try:
            source_path = self._store.resolve_internal_path(input_address)
        except Exception as error:
            raise DBIPilotRasterUnavailable(
                "No se pudo resolver la ortofoto privada."
            ) from error

        workspace = Path(
            mkdtemp(
                prefix="pilot-raster-",
                dir=str(self._store.staging_directory),
            )
        )
        cog_path = workspace / "rgb.cog.tif"
        manifest_path = workspace / "rgb.cog.manifest.json"

        try:
            completed = subprocess.run(
                [
                    str(self._python),
                    str(self._script),
                    str(source_path),
                    str(cog_path),
                    "--product-kind",
                    "rgb_visual",
                    "--profile-version",
                    PROFILE_VERSION,
                    "--manifest",
                    str(manifest_path),
                ],
                check=False,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=self._timeout_seconds,
            )
            if (
                completed.returncode != 0
                or not cog_path.is_file()
                or not manifest_path.is_file()
            ):
                raise DBIPilotRasterUnavailable(
                    "El proceso aislado no pudo generar un COG RGB validado."
                )

            if manifest_path.stat().st_size > _MAX_MANIFEST_BYTES:
                raise DBIPilotRasterConflict(
                    "El manifiesto COG excede la política DBI."
                )
            manifest_text = manifest_path.read_text(encoding="utf-8")
            candidate = prepare_candidate_from_manifest(
                manifest_text,
                source_kind=DBIRasterSourceKind.INPUT_ASSET,
                source_ref=asset.id,
            )
            expected_id = raster_product_id(
                source_kind=DBIRasterSourceKind.INPUT_ASSET,
                source_ref=asset.id,
                source_sha256=asset.sha256,
                product_kind=DBIRasterProductKind.RGB_VISUAL,
                profile_version=PROFILE_VERSION,
            )
            if (
                candidate.product_kind is not DBIRasterProductKind.RGB_VISUAL
                or candidate.source_sha256 != asset.sha256
                or candidate.object_id != expected_id
                or candidate.profile_version != PROFILE_VERSION
            ):
                raise DBIPilotRasterConflict(
                    "El manifiesto COG diverge de la ortofoto autorizada."
                )
            if candidate.size_bytes != cog_path.stat().st_size:
                raise DBIPilotRasterConflict(
                    "El COG generado diverge del manifiesto."
                )

            service = DBIRasterProductService(self._session, self._store)
            # Verifica autoridad source ANTES de publicar el producto.
            service.resolve_source(candidate, tenant_ref=tenant_ref)

            output_address = DBIStoragePolicy.build_address(
                tenant_ref=tenant_ref,
                purpose=DBIStoragePurpose.RASTER_PRODUCT,
                object_id=candidate.object_id,
            )
            metadata = DBIStoragePolicy.build_metadata(
                address=output_address,
                content_type=candidate.content_type,
                size_bytes=candidate.size_bytes,
                sha256_hex=candidate.sha256,
            )
            with cog_path.open("rb") as stream:
                self._store.put(
                    DBIStorageWriteRequest(metadata=metadata),
                    stream,
                )

            evidence = service.register_ready(
                candidate,
                tenant_ref=tenant_ref,
            )
            row = self._session.get(DBIRasterProduct, evidence.product_id)
            if row is None:
                raise DBIPilotRasterConflict(
                    "El producto Raster no quedó disponible en la unidad de trabajo."
                )
            return DBIPilotRasterResult(
                product_id=evidence.product_id,
                created=evidence.created,
                status="ready",
                source_asset_id=asset.id,
                profile_version=candidate.profile_version,
                size_bytes=candidate.size_bytes,
                sha256=candidate.sha256,
                crs=candidate.crs,
                width=candidate.width,
                height=candidate.height,
                band_count=candidate.band_count,
            )
        except subprocess.TimeoutExpired as error:
            raise DBIPilotRasterUnavailable(
                "La generación COG excedió el tiempo permitido."
            ) from error
        except DBIStorageError as error:
            raise DBIPilotRasterConflict(
                "Storage rechazó el producto Raster generado."
            ) from error
        except OSError as error:
            raise DBIPilotRasterUnavailable(
                "No se pudo leer/escribir el staging Raster local."
            ) from error
        except (DBIRasterConflict, DBIRasterUnavailable) as error:
            raise DBIPilotRasterConflict(
                "La autoridad Raster rechazó el producto generado."
            ) from error
        finally:
            shutil.rmtree(workspace, ignore_errors=True)
