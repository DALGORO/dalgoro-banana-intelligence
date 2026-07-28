from __future__ import annotations

import csv
import json
import shutil
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np
import rasterio
from rasterio.transform import array_bounds
from rasterio.windows import Window


PROJECT_ROOT = Path(__file__).resolve().parents[2]

DEFAULT_TILE_SIZE = 640
DEFAULT_OVERLAP = 128
DEFAULT_MIN_VALID_PERCENT = 0.0

OUTPUT_NODATA_VALUE = 0
TIFF_BLOCK_SIZE = 256
MINIMUM_SAFETY_BYTES = 256 * 1024**2


@dataclass
class TileGenerationResult:
    """Resultado estructurado de la generación de tiles."""

    success: bool
    started_at: str
    finished_at: str | None
    input_raster: str
    tile_size: int
    overlap: int
    min_valid_percent: float
    output_directory: str | None = None
    manifest_csv: str | None = None
    report_path: str | None = None
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


def bytes_to_gib(value: int | float) -> float:
    """Convierte bytes a GiB."""

    return round(float(value) / (1024**3), 3)


def validate_tiling_parameters(
    tile_size: int,
    overlap: int,
    min_valid_percent: float,
) -> list[str]:
    """Valida los parámetros principales."""

    errors: list[str] = []

    if tile_size <= 0:
        errors.append(
            "El tamaño del tile debe ser mayor que cero."
        )

    if tile_size % 16 != 0:
        errors.append(
            "El tamaño del tile debe ser múltiplo de 16."
        )

    if overlap < 0:
        errors.append(
            "El solape no puede ser negativo."
        )

    if overlap >= tile_size:
        errors.append(
            "El solape debe ser menor que el tamaño del tile."
        )

    if not 0.0 <= min_valid_percent <= 100.0:
        errors.append(
            "El porcentaje mínimo válido debe estar entre 0 y 100."
        )

    return errors


def calculate_start_positions(
    raster_dimension: int,
    tile_size: int,
    step: int,
) -> list[int]:
    """
    Calcula posiciones que cubren toda la dimensión.

    El último tile se alinea con el borde final para evitar
    franjas del raster sin procesar.
    """

    if raster_dimension <= tile_size:
        return [0]

    final_start = raster_dimension - tile_size

    positions = list(
        range(0, final_start + 1, step)
    )

    if positions[-1] != final_start:
        positions.append(final_start)

    return positions


def resolve_output_locations(
    raster_path: Path,
    output_dir: str | Path | None,
) -> tuple[Path, Path]:
    """
    Determina la carpeta definitiva y temporal.

    Cuando el raster está dentro de 01_recorte, se utiliza
    automáticamente el 02_tiles de la misma ejecución.
    """

    if output_dir is not None:
        tiles_root = Path(
            output_dir
        ).expanduser().resolve(strict=False)

        temporary_root = (
            tiles_root.parent
            / f".{tiles_root.name}_partial"
        )

        return tiles_root, temporary_root

    if raster_path.parent.name == "01_recorte":
        run_root = raster_path.parent.parent

        return (
            run_root / "02_tiles",
            run_root / "temp" / "tiles_partial",
        )

    timestamp = datetime.now().strftime(
        "%Y%m%d_%H%M%S"
    )

    run_root = (
        PROJECT_ROOT
        / "runs"
        / f"{raster_path.stem}_tiles_{timestamp}"
    )

    return (
        run_root / "02_tiles",
        run_root / "temp" / "tiles_partial",
    )


def estimate_required_space(
    tile_count: int,
    tile_size: int,
    data_types: tuple[str, ...],
) -> int:
    """Estima el espacio requerido antes de escribir."""

    bytes_per_pixel = sum(
        np.dtype(data_type).itemsize
        for data_type in data_types
    )

    uncompressed_bytes = (
        tile_count
        * tile_size
        * tile_size
        * bytes_per_pixel
    )

    return (
        int(uncompressed_bytes * 1.25)
        + MINIMUM_SAFETY_BYTES
    )


def create_tile_profile(
    source: rasterio.io.DatasetReader,
    tile_transform: rasterio.Affine,
    tile_size: int,
) -> dict[str, Any]:
    """Construye un perfil GeoTIFF válido."""

    profile = source.profile.copy()

    # Elimina tamaños de bloque heredados del raster original.
    profile.pop("blockxsize", None)
    profile.pop("blockysize", None)

    block_size = min(
        TIFF_BLOCK_SIZE,
        tile_size,
    )

    block_size = max(
        16,
        (block_size // 16) * 16,
    )

    predictor = (
        3
        if any(
            np.issubdtype(
                np.dtype(data_type),
                np.floating,
            )
            for data_type in source.dtypes
        )
        else 2
    )

    profile.update(
        {
            "driver": "GTiff",
            "width": tile_size,
            "height": tile_size,
            "count": source.count,
            "transform": tile_transform,
            "crs": source.crs,
            "nodata": (
                source.nodata
                if source.nodata is not None
                else OUTPUT_NODATA_VALUE
            ),
            "compress": "DEFLATE",
            "predictor": predictor,
            "tiled": True,
            "blockxsize": block_size,
            "blockysize": block_size,
            "BIGTIFF": "IF_SAFER",
            "interleave": (
                "pixel"
                if source.count > 1
                else "band"
            ),
        }
    )

    return profile


def calculate_tile_bounds(
    transform: rasterio.Affine,
    tile_size: int,
) -> dict[str, float]:
    """Calcula la extensión geográfica del tile."""

    west, south, east, north = array_bounds(
        tile_size,
        tile_size,
        transform,
    )

    return {
        "min_x": float(west),
        "min_y": float(south),
        "max_x": float(east),
        "max_y": float(north),
    }


def write_tile(
    output_path: Path,
    tile_array: np.ndarray,
    tile_mask: np.ndarray,
    profile: dict[str, Any],
    tags: dict[str, str],
) -> None:
    """Escribe un tile mediante un archivo temporal."""

    temporary_path = output_path.with_suffix(
        ".partial.tif"
    )

    try:
        with rasterio.open(
            temporary_path,
            mode="w",
            **profile,
        ) as destination:
            destination.write(tile_array)
            destination.write_mask(tile_mask)
            destination.update_tags(**tags)

        temporary_path.replace(output_path)

    finally:
        if temporary_path.exists():
            temporary_path.unlink()


def generate_georeferenced_tiles(
    raster_path: str | Path,
    tile_size: int = DEFAULT_TILE_SIZE,
    overlap: int = DEFAULT_OVERLAP,
    min_valid_percent: float = DEFAULT_MIN_VALID_PERCENT,
    output_dir: str | Path | None = None,
) -> TileGenerationResult:
    """
    Genera tiles GeoTIFF georreferenciados.

    No modifica el raster de entrada.
    """

    started_at = datetime.now().isoformat(
        timespec="seconds"
    )

    start_time = time.perf_counter()

    normalized_raster_path = Path(
        raster_path
    ).expanduser().resolve(strict=False)

    result = TileGenerationResult(
        success=False,
        started_at=started_at,
        finished_at=None,
        input_raster=str(normalized_raster_path),
        tile_size=tile_size,
        overlap=overlap,
        min_valid_percent=min_valid_percent,
    )

    result.errors.extend(
        validate_tiling_parameters(
            tile_size=tile_size,
            overlap=overlap,
            min_valid_percent=min_valid_percent,
        )
    )

    if result.errors:
        result.finished_at = datetime.now().isoformat(
            timespec="seconds"
        )

        return result

    if not normalized_raster_path.is_file():
        result.errors.append(
            "El raster de entrada no existe."
        )

        result.finished_at = datetime.now().isoformat(
            timespec="seconds"
        )

        return result

    tiles_root, temporary_root = resolve_output_locations(
        raster_path=normalized_raster_path,
        output_dir=output_dir,
    )

    final_tiles_directory = (
        tiles_root / "geotiff"
    )

    temporary_tiles_directory = (
        temporary_root / "geotiff"
    )

    try:
        if (
            final_tiles_directory.exists()
            and any(final_tiles_directory.iterdir())
        ):
            raise FileExistsError(
                "La carpeta definitiva ya contiene tiles. "
                "No se sobrescribirá una ejecución anterior."
            )

        if temporary_root.exists():
            shutil.rmtree(temporary_root)

        temporary_tiles_directory.mkdir(
            parents=True,
            exist_ok=False,
        )

        with rasterio.open(
            normalized_raster_path
        ) as source:
            if source.crs is None:
                raise ValueError(
                    "El raster no tiene CRS."
                )

            step = tile_size - overlap

            row_positions = calculate_start_positions(
                raster_dimension=source.height,
                tile_size=tile_size,
                step=step,
            )

            column_positions = calculate_start_positions(
                raster_dimension=source.width,
                tile_size=tile_size,
                step=step,
            )

            candidate_tile_count = (
                len(row_positions)
                * len(column_positions)
            )

            required_bytes = estimate_required_space(
                tile_count=candidate_tile_count,
                tile_size=tile_size,
                data_types=source.dtypes,
            )

            disk_usage = shutil.disk_usage(
                temporary_root.anchor
            )

            if disk_usage.free < required_bytes:
                raise RuntimeError(
                    "Espacio insuficiente para generar los tiles. "
                    f"Disponible: {bytes_to_gib(disk_usage.free)} GiB. "
                    f"Requerido estimado: "
                    f"{bytes_to_gib(required_bytes)} GiB."
                )

            manifest_rows: list[
                dict[str, Any]
            ] = []

            generated_tiles = 0
            skipped_tiles = 0
            epsg_code = source.crs.to_epsg()

            for row_index, row_off in enumerate(
                row_positions,
                start=1,
            ):
                for column_index, column_off in enumerate(
                    column_positions,
                    start=1,
                ):
                    window = Window(
                        col_off=column_off,
                        row_off=row_off,
                        width=tile_size,
                        height=tile_size,
                    )

                    fill_value = (
                        source.nodata
                        if source.nodata is not None
                        else OUTPUT_NODATA_VALUE
                    )

                    tile_array = source.read(
                        window=window,
                        boundless=True,
                        fill_value=fill_value,
                    )

                    tile_mask = source.dataset_mask(
                        window=window,
                        boundless=True,
                        out_shape=(
                            tile_size,
                            tile_size,
                        ),
                    )

                    valid_pixels = int(
                        np.count_nonzero(tile_mask)
                    )

                    valid_percent = (
                        valid_pixels
                        / (tile_size * tile_size)
                        * 100.0
                    )

                    # Con cero se omiten únicamente tiles vacíos.
                    if valid_percent <= min_valid_percent:
                        skipped_tiles += 1
                        continue

                    generated_tiles += 1

                    tile_id = (
                        f"{normalized_raster_path.stem}"
                        f"_r{row_index:04d}"
                        f"_c{column_index:04d}"
                    )

                    tile_filename = (
                        f"{tile_id}.tif"
                    )

                    tile_output_path = (
                        temporary_tiles_directory
                        / tile_filename
                    )

                    tile_transform = (
                        source.window_transform(window)
                    )

                    profile = create_tile_profile(
                        source=source,
                        tile_transform=tile_transform,
                        tile_size=tile_size,
                    )

                    bounds = calculate_tile_bounds(
                        transform=tile_transform,
                        tile_size=tile_size,
                    )

                    write_tile(
                        output_path=tile_output_path,
                        tile_array=tile_array,
                        tile_mask=tile_mask,
                        profile=profile,
                        tags={
                            "tile_id": tile_id,
                            "source_raster": str(
                                normalized_raster_path
                            ),
                            "row_index": str(
                                row_index
                            ),
                            "column_index": str(
                                column_index
                            ),
                            "row_offset": str(
                                row_off
                            ),
                            "column_offset": str(
                                column_off
                            ),
                            "tile_size": str(
                                tile_size
                            ),
                            "overlap": str(
                                overlap
                            ),
                            "valid_percent": (
                                f"{valid_percent:.6f}"
                            ),
                        },
                    )

                    manifest_rows.append(
                        {
                            "tile_id": tile_id,
                            "archivo": tile_filename,
                            "fila": row_index,
                            "columna": column_index,
                            "row_off_px": row_off,
                            "col_off_px": column_off,
                            "tile_size_px": tile_size,
                            "overlap_px": overlap,
                            "valid_percent": round(
                                valid_percent,
                                6,
                            ),
                            "crs": (
                                source.crs.to_string()
                            ),
                            "epsg": epsg_code,
                            "resolucion_x": abs(
                                float(source.res[0])
                            ),
                            "resolucion_y": abs(
                                float(source.res[1])
                            ),
                            **bounds,
                        }
                    )

        if generated_tiles == 0:
            raise RuntimeError(
                "No se generó ningún tile. Revise el raster, "
                "el valor NoData o el porcentaje mínimo válido."
            )

        temporary_manifest_path = (
            temporary_root
            / "tiles_manifest.csv"
        )

        with temporary_manifest_path.open(
            "w",
            newline="",
            encoding="utf-8-sig",
        ) as manifest_file:
            writer = csv.DictWriter(
                manifest_file,
                fieldnames=list(
                    manifest_rows[0].keys()
                ),
            )

            writer.writeheader()
            writer.writerows(manifest_rows)

        elapsed_seconds = round(
            time.perf_counter() - start_time,
            3,
        )

        report_data = {
            "success": True,
            "started_at": started_at,
            "finished_at": (
                datetime.now().isoformat(
                    timespec="seconds"
                )
            ),
            "input_raster": str(
                normalized_raster_path
            ),
            "tile_size": tile_size,
            "overlap": overlap,
            "step": tile_size - overlap,
            "min_valid_percent": (
                min_valid_percent
            ),
            "candidate_tiles": (
                candidate_tile_count
            ),
            "generated_tiles": generated_tiles,
            "skipped_tiles": skipped_tiles,
            "rows": len(row_positions),
            "columns": len(
                column_positions
            ),
            "elapsed_seconds": (
                elapsed_seconds
            ),
        }

        temporary_report_path = (
            temporary_root
            / "tiles_report.json"
        )

        with temporary_report_path.open(
            "w",
            encoding="utf-8",
        ) as report_file:
            json.dump(
                report_data,
                report_file,
                ensure_ascii=False,
                indent=4,
            )

        tiles_root.mkdir(
            parents=True,
            exist_ok=True,
        )

        shutil.move(
            str(temporary_tiles_directory),
            str(final_tiles_directory),
        )

        final_manifest_path = (
            tiles_root / "tiles_manifest.csv"
        )

        final_report_path = (
            tiles_root / "tiles_report.json"
        )

        shutil.move(
            str(temporary_manifest_path),
            str(final_manifest_path),
        )

        shutil.move(
            str(temporary_report_path),
            str(final_report_path),
        )

        if temporary_root.exists():
            shutil.rmtree(temporary_root)

        result.output_directory = str(
            final_tiles_directory
        )

        result.manifest_csv = str(
            final_manifest_path
        )

        result.report_path = str(
            final_report_path
        )

        result.metadata = report_data
        result.success = True

    except Exception as error:
        result.errors.append(
            "No fue posible generar los tiles: "
            f"{type(error).__name__}: {error}"
        )

    result.finished_at = datetime.now().isoformat(
        timespec="seconds"
    )

    return result


def save_error_report(
    result: TileGenerationResult,
) -> Path:
    """Guarda un informe cuando el proceso falla."""

    logs_directory = PROJECT_ROOT / "logs"

    logs_directory.mkdir(
        parents=True,
        exist_ok=True,
    )

    timestamp = datetime.now().strftime(
        "%Y%m%d_%H%M%S"
    )

    report_path = (
        logs_directory
        / f"tiles_error_{timestamp}.json"
    )

    result.report_path = str(
        report_path
    )

    with report_path.open(
        "w",
        encoding="utf-8",
    ) as report_file:
        json.dump(
            asdict(result),
            report_file,
            ensure_ascii=False,
            indent=4,
        )

    return report_path


def print_tile_summary(
    result: TileGenerationResult,
) -> None:
    """Muestra un resumen en la terminal."""

    print("=" * 72)
    print("GENERACIÓN DE TILES GEORREFERENCIADOS")
    print("=" * 72)

    print(f"Raster: {result.input_raster}")
    print(
        f"Tamaño del tile: "
        f"{result.tile_size} px"
    )
    print(f"Solape: {result.overlap} px")

    print(
        "Estado: "
        f"{'COMPLETADO' if result.success else 'ERROR'}"
    )

    if result.success:
        print(
            "Tiles candidatos: "
            f"{result.metadata['candidate_tiles']}"
        )

        print(
            "Tiles generados: "
            f"{result.metadata['generated_tiles']}"
        )

        print(
            "Tiles omitidos: "
            f"{result.metadata['skipped_tiles']}"
        )

        print(
            "Carpeta: "
            f"{result.output_directory}"
        )

        print(
            "Manifest: "
            f"{result.manifest_csv}"
        )

        print(
            "Tiempo: "
            f"{result.metadata['elapsed_seconds']} segundos"
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
            "\nInforme: "
            f"{result.report_path}"
        )

    print("=" * 72)


def run_tile_generation(
    raster_path: str | Path,
    tile_size: int = DEFAULT_TILE_SIZE,
    overlap: int = DEFAULT_OVERLAP,
    min_valid_percent: float = DEFAULT_MIN_VALID_PERCENT,
    output_dir: str | Path | None = None,
) -> int:
    """Ejecuta la generación desde main.py."""

    result = generate_georeferenced_tiles(
        raster_path=raster_path,
        tile_size=tile_size,
        overlap=overlap,
        min_valid_percent=min_valid_percent,
        output_dir=output_dir,
    )

    if (
        not result.success
        and result.report_path is None
    ):
        save_error_report(result)

    print_tile_summary(result)

    return 0 if result.success else 1