"""Adaptador local que invoca el renderer Raster en un proceso aislado.

Este módulo pertenece al backend pero no importa Rasterio/GDAL. La única ruta
física que usa proviene del provider local DBI después de validar la dirección
canónica y el SHA del producto autorizado.
"""

from __future__ import annotations

import math
from pathlib import Path
import subprocess
import sys

from app.dbi.raster.tile_service import (
    DBIRasterTileIntegrityError,
    DBIRasterTileOutsideExtent,
    DBIRasterTileRenderPayload,
    DBIRasterTileRenderRequest,
    DBIRasterTileRendererUnavailable,
)
from app.dbi.storage_contracts import (
    DBIStorageError,
    DBIStoragePurpose,
)
from app.dbi.storage_local import DBILocalObjectStore
from app.dbi.storage_policy import DBIStoragePolicy


class DBILocalSubprocessRasterTileRenderer:
    """Renderer local server-side para pruebas/operación de estación DBI."""

    def __init__(
        self,
        object_store: DBILocalObjectStore,
        *,
        script_path: str | Path,
        python_executable: str | Path | None = None,
        timeout_seconds: float = 20.0,
        max_output_bytes: int = 512 * 1024,
    ) -> None:
        if not isinstance(object_store, DBILocalObjectStore):
            raise TypeError("object_store debe ser DBILocalObjectStore.")
        script = Path(script_path).expanduser().resolve()
        if not script.is_file():
            raise ValueError("script_path del renderer no existe.")
        executable = str(
            Path(
                sys.executable if python_executable is None else python_executable
            ).expanduser()
        )
        if (
            not isinstance(timeout_seconds, (int, float))
            or isinstance(timeout_seconds, bool)
            or not math.isfinite(float(timeout_seconds))
            or float(timeout_seconds) <= 0
        ):
            raise ValueError("timeout_seconds debe ser positivo y finito.")
        if (
            not isinstance(max_output_bytes, int)
            or isinstance(max_output_bytes, bool)
            or max_output_bytes <= 0
        ):
            raise ValueError("max_output_bytes debe ser entero positivo.")

        self._store = object_store
        self._script = script
        self._python = executable
        self._timeout = float(timeout_seconds)
        self._max_output_bytes = max_output_bytes

    def render_tile(
        self,
        request: DBIRasterTileRenderRequest,
    ) -> DBIRasterTileRenderPayload:
        if not isinstance(request, DBIRasterTileRenderRequest):
            raise DBIRasterTileIntegrityError(
                "request del renderer local no cumple el contrato."
            )

        address = DBIStoragePolicy.build_address(
            tenant_ref=request.tenant_ref,
            purpose=DBIStoragePurpose.RASTER_PRODUCT,
            object_id=request.product_id,
        )
        try:
            record = self._store.stat(address)
            source_path = self._store.resolve_internal_path(address)
        except DBIStorageError as error:
            raise DBIRasterTileRendererUnavailable(
                "producto Raster local no disponible."
            ) from error

        if (
            record.metadata.content_type != "image/tiff"
            or record.metadata.sha256 != request.product_sha256
        ):
            raise DBIRasterTileIntegrityError(
                "producto Raster local diverge de la metadata autorizada."
            )

        style = request.style
        command = [
            self._python,
            str(self._script),
            str(source_path),
            str(request.coordinate.z),
            str(request.coordinate.x),
            str(request.coordinate.y),
            "--render-mode",
            style.render_mode,
            "--style-id",
            style.style_id,
            "--bands",
            ",".join(str(index) for index in style.band_indexes),
            "--tile-size",
            "256",
        ]
        if style.render_mode == "single_band":
            if style.display_min is None or style.display_max is None:
                raise DBIRasterTileIntegrityError(
                    "estilo científico incompleto para renderer local."
                )
            command.extend(
                [
                    "--display-min",
                    repr(float(style.display_min)),
                    "--display-max",
                    repr(float(style.display_max)),
                ]
            )

        try:
            completed = subprocess.run(
                command,
                check=False,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=self._timeout,
            )
        except (OSError, subprocess.SubprocessError) as error:
            raise DBIRasterTileRendererUnavailable(
                "proceso aislado Raster no disponible."
            ) from error

        if completed.returncode == 4:
            raise DBIRasterTileOutsideExtent(
                "tile fuera del extent del producto."
            )
        if completed.returncode != 0:
            raise DBIRasterTileRendererUnavailable(
                "proceso aislado Raster rechazó el render."
            )

        payload = bytes(completed.stdout)
        if not payload or len(payload) > self._max_output_bytes:
            raise DBIRasterTileIntegrityError(
                "salida del renderer local excede la política."
            )
        return DBIRasterTileRenderPayload(data=payload, content_type="image/png")
