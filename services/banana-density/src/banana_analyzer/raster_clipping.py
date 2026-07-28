from __future__ import annotations

import json
import math
import shutil
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np
import rasterio
from rasterio.mask import mask
from rasterio.windows import (
    Window,
    from_bounds,
    intersection,
)
from shapely.geometry import mapping

from banana_analyzer.excel_boundary import (
    load_boundary_from_excel,
)
from banana_analyzer.workspace import (
    RunWorkspace,
    create_run_workspace,
)


PROJECT_ROOT = Path(__file__).resolve().parents[2]
GLOBAL_LOGS_DIRECTORY = PROJECT_ROOT / "logs"

MINIMUM_SAFETY_BYTES = 512 * 1024**2
OUTPUT_NODATA_VALUE = 0


@dataclass
class RasterClipResult:
    """Resultado estructurado del recorte."""

    success: bool
    started_at: str
    finished_at: str | None
    input_raster: str
    input_excel: str
    sheet_reference: str
    run_directory: str | None = None
    output_raster: str | None = None
    report_path: str | None = None
    errors: list[str] = field(
        default_factory=list
    )
    warnings: list[str] = field(
        default_factory=list
    )
    metadata: dict[str, Any] = field(
        default_factory=dict
    )


def bytes_to_gib(value: int | float) -> float:
    """Convierte bytes a GiB."""

    return round(
        float(value) / (1024**3),
        3,
    )


def estimate_crop_size_bytes(
    source: rasterio.io.DatasetReader,
    geometry_bounds: tuple[
        float,
        float,
        float,
        float,
    ],
) -> dict[str, int]:
    """
    Estima dimensiones y tamaño sin compresión.

    Se utiliza la caja envolvente del polígono.
    """

    geometry_window = from_bounds(
        *geometry_bounds,
        transform=source.transform,
    )

    full_window = Window(
        col_off=0,
        row_off=0,
        width=source.width,
        height=source.height,
    )

    crop_window = intersection(
        geometry_window,
        full_window,
    )

    crop_window = (
        crop_window
        .round_offsets()
        .round_lengths()
    )

    estimated_width = max(
        1,
        int(math.ceil(crop_window.width)),
    )

    estimated_height = max(
        1,
        int(math.ceil(crop_window.height)),
    )

    bytes_per_pixel = sum(
        np.dtype(data_type).itemsize
        for data_type in source.dtypes
    )

    estimated_bytes = (
        estimated_width
        * estimated_height
        * bytes_per_pixel
    )

    return {
        "width": estimated_width,
        "height": estimated_height,
        "bytes": estimated_bytes,
    }


def validate_output_space(
    output_directory: Path,
    estimated_output_bytes: int,
) -> dict[str, Any]:
    """
    Verifica espacio antes de comenzar el recorte.

    Se reserva el doble del tamaño estimado más
    un margen fijo de seguridad.
    """

    disk_usage = shutil.disk_usage(
        output_directory.anchor
    )

    required_bytes = (
        estimated_output_bytes * 2
        + MINIMUM_SAFETY_BYTES
    )

    return {
        "unit": output_directory.anchor,
        "free_bytes": disk_usage.free,
        "free_gib": bytes_to_gib(
            disk_usage.free
        ),
        "required_bytes": required_bytes,
        "required_gib": bytes_to_gib(
            required_bytes
        ),
        "sufficient": (
            disk_usage.free >= required_bytes
        ),
    }


def calculate_tiff_block_size(
    dimension: int,
    preferred_size: int = 512,
) -> int:
    """
    Calcula un tamaño de bloque válido para GeoTIFF.

    Los bloques TIFF deben ser múltiplos de 16.
    El valor tampoco debe superar la dimensión
    correspondiente del raster.
    """

    limited_size = min(
        int(dimension),
        preferred_size,
    )

    block_size = (
        limited_size // 16
    ) * 16

    return max(16, block_size)


def build_output_profile(
    source: rasterio.io.DatasetReader,
    output_array: np.ndarray,
    output_transform: rasterio.Affine,
) -> dict[str, Any]:
    """Construye el perfil del GeoTIFF recortado."""

    output_height = int(
        output_array.shape[1]
    )

    output_width = int(
        output_array.shape[2]
    )

    use_tiling = (
        output_width >= 16
        and output_height >= 16
    )

    profile = source.profile.copy()

    # El perfil original puede contener tamaños de bloque
    # propios de un TIFF organizado por franjas. Esos valores
    # no siempre son válidos al activar tiled=True.
    profile.pop("blockxsize", None)
    profile.pop("blockysize", None)

    profile.update(
        {
            "driver": "GTiff",
            "height": output_height,
            "width": output_width,
            "count": output_array.shape[0],
            "transform": output_transform,
            "crs": source.crs,
            "nodata": OUTPUT_NODATA_VALUE,
            "compress": "DEFLATE",
            "tiled": use_tiling,
            "BIGTIFF": "IF_SAFER",
            "interleave": "pixel",
        }
    )

    if use_tiling:
        profile.update(
            {
                "blockxsize": (
                    calculate_tiff_block_size(
                        output_width
                    )
                ),
                "blockysize": (
                    calculate_tiff_block_size(
                        output_height
                    )
                ),
            }
        )

    return profile


def write_clipped_raster(
    source: rasterio.io.DatasetReader,
    geometry: Any,
    temporary_path: Path,
    final_path: Path,
    source_raster_path: Path,
    excel_path: Path,
) -> None:
    """
    Recorta y escribe el raster de forma controlada.

    El archivo se escribe primero con extensión temporal.
    """

    output_array, output_transform = mask(
        dataset=source,
        shapes=[mapping(geometry)],
        crop=True,
        filled=True,
        nodata=OUTPUT_NODATA_VALUE,
        all_touched=False,
    )

    profile = build_output_profile(
        source=source,
        output_array=output_array,
        output_transform=output_transform,
    )

    with rasterio.open(
        temporary_path,
        mode="w",
        **profile,
    ) as destination:
        destination.write(output_array)

        try:
            destination.colorinterp = (
                source.colorinterp
            )
        except Exception:
            pass

        destination.update_tags(
            source_raster=str(
                source_raster_path
            ),
            boundary_excel=str(excel_path),
            processing_date=(
                datetime.now().isoformat(
                    timespec="seconds"
                )
            ),
            processing_module=(
                "banana_analyzer.raster_clipping"
            ),
        )

    temporary_path.replace(final_path)


def inspect_output_raster(
    output_path: Path,
) -> dict[str, Any]:
    """Verifica el raster después de escribirlo."""

    with rasterio.open(output_path) as result:
        compression = (
            result.compression.value
            if result.compression is not None
            else None
        )

        return {
            "driver": result.driver,
            "width": result.width,
            "height": result.height,
            "bands": result.count,
            "data_types": list(result.dtypes),
            "crs": (
                result.crs.to_string()
                if result.crs is not None
                else None
            ),
            "epsg": (
                result.crs.to_epsg()
                if result.crs is not None
                else None
            ),
            "resolution_x": abs(
                float(result.res[0])
            ),
            "resolution_y": abs(
                float(result.res[1])
            ),
            "nodata": result.nodata,
            "compression": compression,
            "tiled": bool(
                result.profile.get(
                    "tiled",
                    False,
                )
            ),
            "bounds": {
                "left": float(
                    result.bounds.left
                ),
                "bottom": float(
                    result.bounds.bottom
                ),
                "right": float(
                    result.bounds.right
                ),
                "top": float(
                    result.bounds.top
                ),
            },
            "file_size_gib": bytes_to_gib(
                output_path.stat().st_size
            ),
        }


def save_clip_report(
    result: RasterClipResult,
    workspace: RunWorkspace | None,
) -> Path:
    """Guarda el informe JSON del recorte."""

    if workspace is not None:
        report_directory = workspace.logs
    else:
        report_directory = (
            GLOBAL_LOGS_DIRECTORY
        )

    report_directory.mkdir(
        parents=True,
        exist_ok=True,
    )

    if workspace is not None:
        report_name = "clip_report.json"
    else:
        timestamp = datetime.now().strftime(
            "%Y%m%d_%H%M%S"
        )

        report_name = (
            f"clip_report_error_{timestamp}.json"
        )

    report_path = (
        report_directory / report_name
    )

    result.report_path = str(report_path)

    with report_path.open(
        "w",
        encoding="utf-8",
    ) as file:
        json.dump(
            asdict(result),
            file,
            ensure_ascii=False,
            indent=4,
        )

    return report_path


def clip_raster_with_excel_boundary(
    excel_path: str | Path,
    raster_path: str | Path,
    sheet_reference: str | int = 0,
    output_root: str | Path | None = None,
) -> RasterClipResult:
    """
    Construye el límite desde Excel y recorta la ortofoto.

    El raster original no se modifica.
    """

    started_at = (
        datetime.now().isoformat(
            timespec="seconds"
        )
    )

    start_time = time.perf_counter()

    normalized_excel_path = Path(
        excel_path
    ).expanduser().resolve(strict=False)

    normalized_raster_path = Path(
        raster_path
    ).expanduser().resolve(strict=False)

    result = RasterClipResult(
        success=False,
        started_at=started_at,
        finished_at=None,
        input_raster=str(
            normalized_raster_path
        ),
        input_excel=str(
            normalized_excel_path
        ),
        sheet_reference=str(
            sheet_reference
        ),
    )

    workspace: RunWorkspace | None = None
    temporary_path: Path | None = None

    boundary_result, boundary = (
        load_boundary_from_excel(
            excel_path=normalized_excel_path,
            raster_path=normalized_raster_path,
            sheet_reference=sheet_reference,
        )
    )

    result.warnings.extend(
        boundary_result.warnings
    )

    if not boundary_result.valid:
        result.errors.extend(
            boundary_result.errors
        )

        result.metadata[
            "boundary_validation"
        ] = boundary_result.metadata

        result.finished_at = (
            datetime.now().isoformat(
                timespec="seconds"
            )
        )

        save_clip_report(
            result=result,
            workspace=None,
        )

        return result

    if boundary is None:
        result.errors.append(
            "El límite fue validado, pero no se "
            "obtuvo una geometría utilizable."
        )

        result.finished_at = (
            datetime.now().isoformat(
                timespec="seconds"
            )
        )

        save_clip_report(
            result=result,
            workspace=None,
        )

        return result

    try:
        workspace = create_run_workspace(
            project_name=(
                normalized_raster_path.stem
            ),
            output_root=output_root,
        )

        result.run_directory = str(
            workspace.root
        )

        output_path = (
            workspace.clipped
            / (
                f"{normalized_raster_path.stem}"
                "_recortada.tif"
            )
        )

        temporary_path = (
            workspace.temp
            / (
                f"{normalized_raster_path.stem}"
                "_recortada.partial.tif"
            )
        )

        geometry = boundary.geometry.iloc[0]

        with rasterio.open(
            normalized_raster_path
        ) as source:
            size_estimate = (
                estimate_crop_size_bytes(
                    source=source,
                    geometry_bounds=(
                        geometry.bounds
                    ),
                )
            )

            space_check = validate_output_space(
                output_directory=workspace.root,
                estimated_output_bytes=(
                    size_estimate["bytes"]
                ),
            )

            if not space_check["sufficient"]:
                raise RuntimeError(
                    "Espacio insuficiente para realizar "
                    "el recorte. Disponible: "
                    f"{space_check['free_gib']} GiB. "
                    "Requerido estimado: "
                    f"{space_check['required_gib']} GiB."
                )

            write_clipped_raster(
                source=source,
                geometry=geometry,
                temporary_path=temporary_path,
                final_path=output_path,
                source_raster_path=(
                    normalized_raster_path
                ),
                excel_path=(
                    normalized_excel_path
                ),
            )

        output_metadata = (
            inspect_output_raster(
                output_path
            )
        )

        elapsed_seconds = round(
            time.perf_counter() - start_time,
            3,
        )

        result.output_raster = str(
            output_path
        )

        result.metadata = {
            "boundary_validation": (
                boundary_result.metadata
            ),
            "estimated_crop": {
                "width": (
                    size_estimate["width"]
                ),
                "height": (
                    size_estimate["height"]
                ),
                "uncompressed_gib": (
                    bytes_to_gib(
                        size_estimate["bytes"]
                    )
                ),
            },
            "disk_space": space_check,
            "output": output_metadata,
            "elapsed_seconds": (
                elapsed_seconds
            ),
        }

        result.success = True

    except Exception as error:
        result.errors.append(
            "No fue posible generar el recorte: "
            f"{type(error).__name__}: {error}"
        )

    finally:
        if (
            temporary_path is not None
            and temporary_path.exists()
        ):
            try:
                temporary_path.unlink()
            except OSError:
                result.warnings.append(
                    "No fue posible eliminar el "
                    "archivo temporal incompleto."
                )

    result.finished_at = (
        datetime.now().isoformat(
            timespec="seconds"
        )
    )

    save_clip_report(
        result=result,
        workspace=workspace,
    )

    return result


def print_clip_summary(
    result: RasterClipResult,
) -> None:
    """Muestra el resultado del recorte."""

    print("=" * 72)
    print("RECORTE AUTOMÁTICO DE ORTOFOTO")
    print("=" * 72)

    print(f"Ortofoto: {result.input_raster}")
    print(f"Excel: {result.input_excel}")
    print(f"Hoja: {result.sheet_reference}")

    print(
        "Estado: "
        f"{'COMPLETADO' if result.success else 'ERROR'}"
    )

    if result.run_directory:
        print(
            "Carpeta de ejecución: "
            f"{result.run_directory}"
        )

    if result.output_raster:
        print(
            "Raster recortado: "
            f"{result.output_raster}"
        )

    if result.metadata.get("output"):
        output = result.metadata["output"]

        print(
            "Dimensiones: "
            f"{output['width']} x "
            f"{output['height']} píxeles"
        )

        print(
            f"CRS: {output['crs']}"
        )

        print(
            "Resolución: "
            f"{output['resolution_x']} x "
            f"{output['resolution_y']}"
        )

        print(
            "Tamaño final: "
            f"{output['file_size_gib']} GiB"
        )

        print(
            "Tiempo: "
            f"{result.metadata['elapsed_seconds']} "
            "segundos"
        )

    if result.errors:
        print("\nERRORES:")

        for error in result.errors:
            print(f"  - {error}")

    if result.warnings:
        print("\nADVERTENCIAS:")

        for warning in result.warnings:
            print(f"  - {warning}")

    if result.report_path:
        print(
            "\nInforme guardado en: "
            f"{result.report_path}"
        )

    print("=" * 72)


def run_raster_clipping(
    excel_path: str | Path,
    raster_path: str | Path,
    sheet_reference: str | int = 0,
    output_root: str | Path | None = None,
) -> int:
    """Ejecuta el recorte desde la aplicación."""

    result = (
        clip_raster_with_excel_boundary(
            excel_path=excel_path,
            raster_path=raster_path,
            sheet_reference=sheet_reference,
            output_root=output_root,
        )
    )

    print_clip_summary(result)

    return 0 if result.success else 1