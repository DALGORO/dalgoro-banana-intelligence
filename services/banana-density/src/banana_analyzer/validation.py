from __future__ import annotations

import json
import shutil
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np
import rasterio
from affine import Affine
from rasterio.errors import RasterioIOError


PROJECT_ROOT = Path(__file__).resolve().parents[2]
LOGS_DIRECTORY = PROJECT_ROOT / "logs"

SUPPORTED_RASTER_EXTENSIONS = {
    ".tif",
    ".tiff",
    ".vrt",
    ".img",
    ".jp2",
}


@dataclass
class RasterValidationResult:
    """Resultado estructurado de la validación de una ortofoto."""

    valid: bool
    checked_at: str
    raster_path: str
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


def bytes_to_gib(value: int | float) -> float:
    """Convierte bytes a GiB."""

    return round(float(value) / (1024**3), 3)


def normalize_raster_path(raster_path: str | Path) -> Path:
    """Normaliza una ruta sin exigir que el archivo exista."""

    return Path(raster_path).expanduser().resolve(strict=False)


def calculate_uncompressed_size(
    width: int,
    height: int,
    data_types: tuple[str, ...],
) -> int:
    """
    Estima el tamaño sin compresión del raster.

    El cálculo no incluye pirámides, metadatos, máscaras internas
    ni archivos temporales.
    """

    bytes_per_pixel = sum(
        np.dtype(data_type).itemsize
        for data_type in data_types
    )

    return width * height * bytes_per_pixel


def get_available_disk_space(path: Path) -> dict[str, Any]:
    """Obtiene el espacio disponible en la unidad del raster."""

    usage = shutil.disk_usage(path.anchor)

    return {
        "unidad": path.anchor,
        "capacidad_gib": bytes_to_gib(usage.total),
        "usado_gib": bytes_to_gib(usage.used),
        "libre_gib": bytes_to_gib(usage.free),
    }


def build_invalid_result(
    raster_path: Path,
    error_message: str,
) -> RasterValidationResult:
    """Construye un resultado inválido antes de abrir el raster."""

    return RasterValidationResult(
        valid=False,
        checked_at=datetime.now().isoformat(timespec="seconds"),
        raster_path=str(raster_path),
        errors=[error_message],
    )


def inspect_raster(
    raster_path: str | Path,
) -> RasterValidationResult:
    """
    Inspecciona una ortofoto sin cargar todos sus píxeles en memoria.

    La función abre únicamente la estructura y los metadatos del raster.
    No modifica el archivo original.
    """

    normalized_path = normalize_raster_path(raster_path)

    if not normalized_path.exists():
        return build_invalid_result(
            normalized_path,
            "El archivo raster no existe.",
        )

    if not normalized_path.is_file():
        return build_invalid_result(
            normalized_path,
            "La ruta recibida no corresponde a un archivo.",
        )

    result = RasterValidationResult(
        valid=False,
        checked_at=datetime.now().isoformat(timespec="seconds"),
        raster_path=str(normalized_path),
    )

    extension = normalized_path.suffix.lower()

    if extension not in SUPPORTED_RASTER_EXTENSIONS:
        result.warnings.append(
            "La extensión del archivo no pertenece a la lista de "
            "formatos raster previstos para la automatización."
        )

    try:
        with rasterio.open(normalized_path) as source:
            gcps, gcp_crs = source.gcps
            rpcs = source.rpcs

            has_affine_transform = (
                source.transform != Affine.identity()
            )
            has_gcps = len(gcps) > 0
            has_rpcs = rpcs is not None

            has_georeferencing = (
                has_affine_transform
                or has_gcps
                or has_rpcs
            )

            effective_crs = source.crs or gcp_crs

            x_resolution = abs(float(source.res[0]))
            y_resolution = abs(float(source.res[1]))

            file_size_bytes = normalized_path.stat().st_size

            estimated_uncompressed_bytes = (
                calculate_uncompressed_size(
                    width=source.width,
                    height=source.height,
                    data_types=source.dtypes,
                )
            )

            epsg_code = (
                effective_crs.to_epsg()
                if effective_crs is not None
                else None
            )

            is_projected = (
                effective_crs.is_projected
                if effective_crs is not None
                else False
            )

            is_geographic = (
                effective_crs.is_geographic
                if effective_crs is not None
                else False
            )

            transform = source.transform

            is_north_up = (
                abs(transform.b) < 1e-12
                and abs(transform.d) < 1e-12
            )

            color_interpretations = [
                interpretation.name
                for interpretation in source.colorinterp
            ]

            metadata = {
                "archivo": {
                    "nombre": normalized_path.name,
                    "extension": extension,
                    "tamano_archivo_gib": bytes_to_gib(
                        file_size_bytes
                    ),
                    "tamano_estimado_sin_compresion_gib": (
                        bytes_to_gib(
                            estimated_uncompressed_bytes
                        )
                    ),
                },
                "raster": {
                    "driver": source.driver,
                    "ancho_pixeles": source.width,
                    "alto_pixeles": source.height,
                    "cantidad_bandas": source.count,
                    "tipos_datos": list(source.dtypes),
                    "interpretacion_color": (
                        color_interpretations
                    ),
                    "nodata": source.nodata,
                    "descripciones_bandas": list(
                        source.descriptions
                    ),
                    "unidades_bandas": list(source.units),
                    "bloques": [
                        list(block_shape)
                        for block_shape in source.block_shapes
                    ],
                    "tiled": bool(
                        source.profile.get("tiled", False)
                    ),
                    "compresion": (
                        str(source.profile.get("compress"))
                        if source.profile.get("compress")
                        else None
                    ),
                },
                "georreferenciacion": {
                    "crs": (
                        effective_crs.to_string()
                        if effective_crs is not None
                        else None
                    ),
                    "epsg": epsg_code,
                    "crs_proyectado": is_projected,
                    "crs_geografico": is_geographic,
                    "transformacion_afin": list(transform),
                    "tiene_transformacion_afin": (
                        has_affine_transform
                    ),
                    "cantidad_gcps": len(gcps),
                    "crs_gcps": (
                        gcp_crs.to_string()
                        if gcp_crs is not None
                        else None
                    ),
                    "tiene_rpcs": has_rpcs,
                    "georreferenciado": has_georeferencing,
                    "orientacion_norte_arriba": is_north_up,
                    "resolucion_x": x_resolution,
                    "resolucion_y": y_resolution,
                    "limites": {
                        "izquierda": float(
                            source.bounds.left
                        ),
                        "inferior": float(
                            source.bounds.bottom
                        ),
                        "derecha": float(
                            source.bounds.right
                        ),
                        "superior": float(
                            source.bounds.top
                        ),
                    },
                },
                "almacenamiento": get_available_disk_space(
                    normalized_path
                ),
            }

            result.metadata = metadata

            if source.width <= 0 or source.height <= 0:
                result.errors.append(
                    "El raster tiene dimensiones inválidas."
                )

            if source.count <= 0:
                result.errors.append(
                    "El raster no contiene bandas."
                )

            if effective_crs is None:
                result.errors.append(
                    "El raster no tiene un sistema de "
                    "coordenadas identificable."
                )

            if not has_georeferencing:
                result.errors.append(
                    "El raster no tiene una transformación "
                    "geográfica válida, GCP o RPC."
                )

            if x_resolution <= 0 or y_resolution <= 0:
                result.errors.append(
                    "La resolución espacial del raster es inválida."
                )

            if source.count not in {3, 4}:
                result.warnings.append(
                    "La ortofoto no tiene 3 o 4 bandas. "
                    "Se deberá revisar cómo preparar la imagen "
                    "para la inferencia YOLO."
                )

            if is_geographic:
                result.warnings.append(
                    "El raster utiliza un CRS geográfico. "
                    "Para calcular superficies y densidades será "
                    "necesario trabajar en un CRS proyectado."
                )

            if not is_north_up:
                result.warnings.append(
                    "El raster presenta rotación o inclinación "
                    "en su transformación espacial."
                )

            if source.nodata is None:
                result.warnings.append(
                    "El raster no tiene un valor NoData definido."
                )

            if x_resolution > 0 and y_resolution > 0:
                relative_difference = (
                    abs(x_resolution - y_resolution)
                    / max(x_resolution, y_resolution)
                )

                if relative_difference > 0.01:
                    result.warnings.append(
                        "La resolución horizontal y vertical "
                        "difieren en más del 1 %."
                    )

    except RasterioIOError as error:
        result.errors.append(
            f"Rasterio no pudo abrir el archivo: {error}"
        )

    except PermissionError as error:
        result.errors.append(
            f"No existe permiso para leer el archivo: {error}"
        )

    except Exception as error:
        result.errors.append(
            "Ocurrió un error no esperado durante la inspección: "
            f"{type(error).__name__}: {error}"
        )

    result.valid = len(result.errors) == 0

    return result


def save_validation_report(
    result: RasterValidationResult,
) -> Path:
    """Guarda el resultado de la inspección en JSON."""

    LOGS_DIRECTORY.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    raster_name = Path(result.raster_path).stem or "raster"

    output_path = (
        LOGS_DIRECTORY
        / f"raster_validation_{raster_name}_{timestamp}.json"
    )

    with output_path.open("w", encoding="utf-8") as file:
        json.dump(
            asdict(result),
            file,
            ensure_ascii=False,
            indent=4,
        )

    return output_path


def print_validation_summary(
    result: RasterValidationResult,
    report_path: Path,
) -> None:
    """Muestra un resumen legible en la terminal."""

    print("=" * 72)
    print("VALIDACIÓN DE ORTOFOTO")
    print("=" * 72)

    print(f"Archivo: {result.raster_path}")
    print(
        "Estado: "
        f"{'VÁLIDO' if result.valid else 'NO VÁLIDO'}"
    )

    if result.metadata:
        raster = result.metadata["raster"]
        georef = result.metadata["georreferenciacion"]
        file_info = result.metadata["archivo"]

        print(f"Driver: {raster['driver']}")
        print(
            "Dimensiones: "
            f"{raster['ancho_pixeles']} x "
            f"{raster['alto_pixeles']} píxeles"
        )
        print(
            f"Bandas: {raster['cantidad_bandas']}"
        )
        print(
            f"Tipos de datos: {raster['tipos_datos']}"
        )
        print(
            f"CRS: {georef['crs'] or 'NO DEFINIDO'}"
        )
        print(
            f"EPSG: {georef['epsg'] or 'NO IDENTIFICADO'}"
        )
        print(
            "Resolución: "
            f"{georef['resolucion_x']} x "
            f"{georef['resolucion_y']}"
        )
        print(
            "Georreferenciado: "
            f"{georef['georreferenciado']}"
        )
        print(
            "Tamaño del archivo: "
            f"{file_info['tamano_archivo_gib']} GiB"
        )
        print(
            "Tamaño estimado sin compresión: "
            f"{file_info['tamano_estimado_sin_compresion_gib']} GiB"
        )

    if result.errors:
        print("\nERRORES:")

        for error in result.errors:
            print(f"  - {error}")

    if result.warnings:
        print("\nADVERTENCIAS:")

        for warning in result.warnings:
            print(f"  - {warning}")

    if not result.errors and not result.warnings:
        print("\nNo se detectaron errores ni advertencias.")

    print(f"\nInforme guardado en: {report_path}")
    print("=" * 72)


def run_raster_validation(
    raster_path: str | Path,
) -> int:
    """Ejecuta la validación completa desde la aplicación."""

    result = inspect_raster(raster_path)
    report_path = save_validation_report(result)

    print_validation_summary(result, report_path)

    return 0 if result.valid else 1