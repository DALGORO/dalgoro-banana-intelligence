from __future__ import annotations

import json
import re
import time
import unicodedata
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

import geopandas as gpd
import numpy as np
import pandas as pd
import pyogrio


PROJECT_ROOT = Path(__file__).resolve().parents[2]
GLOBAL_LOGS_DIRECTORY = PROJECT_ROOT / "logs"

REQUIRED_COLUMNS = {
    "detection_id",
    "coord_x",
    "coord_y",
    "epsg",
}


@dataclass
class VectorExportResult:
    """Resultado de la exportación de detecciones a formatos GIS."""

    success: bool
    started_at: str
    finished_at: str | None
    input_csv: str
    name_prefix: str
    layer_name: str
    output_directory: str | None = None
    output_csv: str | None = None
    output_gpkg: str | None = None
    report_path: str | None = None
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


def sanitize_name(value: str) -> str:
    """Convierte un nombre en un identificador seguro."""

    normalized = unicodedata.normalize(
        "NFKD",
        str(value),
    )

    normalized = "".join(
        character
        for character in normalized
        if not unicodedata.combining(character)
    )

    normalized = re.sub(
        r"[^A-Za-z0-9_]+",
        "_",
        normalized,
    )

    normalized = normalized.strip("_")

    return normalized or "resultado"


def resolve_output_directory(
    input_csv: Path,
    output_dir: str | Path | None,
) -> Path:
    """
    Determina la carpeta de salida.

    Para:
        ejecucion/03_detecciones_raw/archivo.csv

    devuelve:
        ejecucion/05_gis
    """

    if output_dir is not None:
        return Path(
            output_dir
        ).expanduser().resolve(strict=False)

    if input_csv.parent.name == "03_detecciones_raw":
        run_directory = input_csv.parent.parent

        return run_directory / "05_gis"

    return input_csv.parent / "gis_outputs"


def validate_input_table(
    table: pd.DataFrame,
) -> list[str]:
    """Valida la estructura mínima del CSV."""

    errors: list[str] = []

    missing_columns = sorted(
        REQUIRED_COLUMNS
        - set(table.columns)
    )

    if missing_columns:
        errors.append(
            "Faltan columnas obligatorias: "
            + ", ".join(missing_columns)
        )

    if table.empty:
        errors.append(
            "El CSV no contiene detecciones."
        )

    return errors


def normalize_coordinate_data(
    table: pd.DataFrame,
) -> tuple[pd.DataFrame, int]:
    """
    Convierte coordenadas y EPSG a valores numéricos.

    Retorna la tabla normalizada y el único EPSG encontrado.
    """

    normalized = table.copy()

    normalized["coord_x"] = pd.to_numeric(
        normalized["coord_x"],
        errors="coerce",
    )

    normalized["coord_y"] = pd.to_numeric(
        normalized["coord_y"],
        errors="coerce",
    )

    normalized["epsg"] = pd.to_numeric(
        normalized["epsg"],
        errors="coerce",
    )

    finite_coordinates = (
        np.isfinite(normalized["coord_x"])
        & np.isfinite(normalized["coord_y"])
    )

    invalid_mask = (
        normalized["coord_x"].isna()
        | normalized["coord_y"].isna()
        | normalized["epsg"].isna()
        | ~finite_coordinates
    )

    if invalid_mask.any():
        affected_rows = [
            int(index + 2)
            for index
            in normalized.index[invalid_mask]
        ]

        raise ValueError(
            "Existen coordenadas o códigos EPSG inválidos "
            f"en las filas: {affected_rows}."
        )

    epsg_values = sorted(
        {
            int(value)
            for value
            in normalized["epsg"]
        }
    )

    if len(epsg_values) != 1:
        raise ValueError(
            "La tabla debe contener un único EPSG. "
            f"Valores encontrados: {epsg_values}."
        )

    epsg_code = epsg_values[0]

    normalized["epsg"] = (
        normalized["epsg"]
        .astype(int)
    )

    return normalized, epsg_code


def reorder_output_columns(
    table: pd.DataFrame,
) -> pd.DataFrame:
    """Organiza los campos principales al inicio."""

    preferred_columns = [
        "detection_id",
        "class_id",
        "class_name",
        "confidence",
        "coord_x",
        "coord_y",
        "epsg",
        "tile_id",
        "tile_file",
        "center_x_px",
        "center_y_px",
        "x_min_px",
        "y_min_px",
        "x_max_px",
        "y_max_px",
        "width_px",
        "height_px",
    ]

    existing_preferred = [
        column
        for column in preferred_columns
        if column in table.columns
    ]

    remaining_columns = [
        column
        for column in table.columns
        if column not in existing_preferred
    ]

    return table[
        existing_preferred
        + remaining_columns
    ].copy()


def build_geodataframe(
    table: pd.DataFrame,
    epsg_code: int,
) -> gpd.GeoDataFrame:
    """Construye una capa de puntos desde X e Y."""

    geometry = gpd.points_from_xy(
        x=table["coord_x"],
        y=table["coord_y"],
    )

    geodataframe = gpd.GeoDataFrame(
        table.copy(),
        geometry=geometry,
        crs=f"EPSG:{epsg_code}",
    )

    if geodataframe.geometry.isna().any():
        raise ValueError(
            "La capa contiene geometrías vacías."
        )

    if geodataframe.geometry.is_empty.any():
        raise ValueError(
            "La capa contiene geometrías de punto vacías."
        )

    if not geodataframe.geometry.is_valid.all():
        raise ValueError(
            "La capa contiene geometrías inválidas."
        )

    return geodataframe


def write_csv_atomic(
    table: pd.DataFrame,
    output_path: Path,
) -> None:
    """Escribe el CSV sin dejar archivos parciales."""

    temporary_path = output_path.with_suffix(
        ".partial.csv"
    )

    try:
        table.to_csv(
            temporary_path,
            index=False,
            encoding="utf-8-sig",
            float_format="%.8f",
        )

        temporary_path.replace(
            output_path
        )

    finally:
        if temporary_path.exists():
            temporary_path.unlink()


def write_gpkg_atomic(
    geodataframe: gpd.GeoDataFrame,
    output_path: Path,
    layer_name: str,
) -> None:
    """Escribe el GeoPackage mediante un archivo temporal."""

    temporary_path = output_path.with_suffix(
        ".partial.gpkg"
    )

    try:
        if temporary_path.exists():
            temporary_path.unlink()

        geodataframe.to_file(
            temporary_path,
            layer=layer_name,
            driver="GPKG",
            engine="pyogrio",
            index=False,
        )

        temporary_path.replace(
            output_path
        )

    finally:
        if temporary_path.exists():
            temporary_path.unlink()


def verify_gpkg_output(
    gpkg_path: Path,
    layer_name: str,
    expected_rows: int,
) -> dict[str, Any]:
    """Abre nuevamente el GeoPackage y verifica su contenido."""

    available_layers = pyogrio.list_layers(
        gpkg_path
    )

    verified = gpd.read_file(
        gpkg_path,
        layer=layer_name,
        engine="pyogrio",
    )

    if len(verified) != expected_rows:
        raise RuntimeError(
            "El número de elementos del GeoPackage "
            "no coincide con el CSV de entrada."
        )

    if verified.crs is None:
        raise RuntimeError(
            "El GeoPackage generado no tiene CRS."
        )

    if verified.geometry.geom_type.ne("Point").any():
        raise RuntimeError(
            "El GeoPackage contiene geometrías "
            "diferentes de punto."
        )

    bounds = verified.total_bounds

    return {
        "layers": available_layers.tolist(),
        "rows": int(len(verified)),
        "geometry_type": "Point",
        "crs": verified.crs.to_string(),
        "epsg": verified.crs.to_epsg(),
        "bounds": {
            "min_x": float(bounds[0]),
            "min_y": float(bounds[1]),
            "max_x": float(bounds[2]),
            "max_y": float(bounds[3]),
        },
    }


def save_export_report(
    result: VectorExportResult,
    report_path: Path,
) -> Path:
    """Guarda el informe JSON de la exportación."""

    report_path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    result.report_path = str(
        report_path
    )

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


def export_detection_vectors(
    input_csv: str | Path,
    output_dir: str | Path | None = None,
    name_prefix: str = "inventario_banano_raw",
    layer_name: str = "detecciones_raw",
) -> VectorExportResult:
    """
    Exporta detecciones georreferenciadas a CSV y GeoPackage.

    No realiza deduplicación.
    """

    started_at = datetime.now().isoformat(
        timespec="seconds"
    )

    start_time = time.perf_counter()

    normalized_input_csv = Path(
        input_csv
    ).expanduser().resolve(strict=False)

    safe_prefix = sanitize_name(
        name_prefix
    )

    safe_layer_name = sanitize_name(
        layer_name
    )

    result = VectorExportResult(
        success=False,
        started_at=started_at,
        finished_at=None,
        input_csv=str(normalized_input_csv),
        name_prefix=safe_prefix,
        layer_name=safe_layer_name,
    )

    output_directory = resolve_output_directory(
        input_csv=normalized_input_csv,
        output_dir=output_dir,
    )

    output_directory.mkdir(
        parents=True,
        exist_ok=True,
    )

    output_csv_path = (
        output_directory
        / f"{safe_prefix}.csv"
    )

    output_gpkg_path = (
        output_directory
        / f"{safe_prefix}.gpkg"
    )

    base_report_path = (
        output_directory
        / f"{safe_prefix}_export_report.json"
    )

    result.output_directory = str(
        output_directory
    )

    if not normalized_input_csv.is_file():
        result.errors.append(
            "El CSV de entrada no existe."
        )

    existing_outputs = [
        path
        for path in (
            output_csv_path,
            output_gpkg_path,
        )
        if path.exists()
    ]

    if existing_outputs:
        result.errors.append(
            "No se sobrescribirán salidas existentes: "
            + ", ".join(
                str(path)
                for path in existing_outputs
            )
        )

    if not result.errors:
        try:
            table = pd.read_csv(
                normalized_input_csv,
                encoding="utf-8-sig",
            )

            result.errors.extend(
                validate_input_table(table)
            )

            if result.errors:
                raise ValueError(
                    "El CSV no cumple la estructura requerida."
                )

            normalized_table, epsg_code = (
                normalize_coordinate_data(
                    table
                )
            )

            is_deduplicated = (
                "dedup_status"
                in normalized_table.columns
                or "duplicates_removed_count"
                in normalized_table.columns
                or "deduplicated"
                in normalized_input_csv.stem.lower()
            )

            ordered_table = reorder_output_columns(
                normalized_table
            )

            geodataframe = build_geodataframe(
                table=ordered_table,
                epsg_code=epsg_code,
            )

            write_csv_atomic(
                table=ordered_table,
                output_path=output_csv_path,
            )

            write_gpkg_atomic(
                geodataframe=geodataframe,
                output_path=output_gpkg_path,
                layer_name=safe_layer_name,
            )

            verification = verify_gpkg_output(
                gpkg_path=output_gpkg_path,
                layer_name=safe_layer_name,
                expected_rows=len(
                    ordered_table
                ),
            )

            elapsed_seconds = round(
                time.perf_counter() - start_time,
                3,
            )

            result.output_csv = str(
                output_csv_path
            )

            result.output_gpkg = str(
                output_gpkg_path
            )

            result.metadata = {
                "input_rows": int(
                    len(table)
                ),
                "output_rows": int(
                    len(ordered_table)
                ),
                "epsg": epsg_code,
                "crs": f"EPSG:{epsg_code}",
                "columns": list(
                    ordered_table.columns
                ),
                "verification": verification,
                "elapsed_seconds": (
                    elapsed_seconds
                ),
                "processing_stage": (
                    "deduplicated_detections"
                    if is_deduplicated
                    else "raw_georeferenced_detections"
                ),
                "deduplication_applied": (
                    is_deduplicated
                ),
                "contains_possible_duplicates": (
                    not is_deduplicated
                ),
            }

            if not is_deduplicated:
                result.warnings.append(
                    "La capa contiene detecciones crudas. "
                    "Todavía pueden existir plantas duplicadas "
                    "por el solape entre tiles."
                )

            result.success = True

        except Exception as error:
            result.errors.append(
                "No fue posible generar las salidas GIS: "
                f"{type(error).__name__}: {error}"
            )

            for incomplete_path in (
                output_csv_path,
                output_gpkg_path,
            ):
                if incomplete_path.exists():
                    try:
                        incomplete_path.unlink()
                    except OSError:
                        result.warnings.append(
                            "No fue posible eliminar una "
                            "salida incompleta: "
                            f"{incomplete_path}"
                        )

    result.finished_at = datetime.now().isoformat(
        timespec="seconds"
    )

    report_path = base_report_path

    if report_path.exists():
        timestamp = datetime.now().strftime(
            "%Y%m%d_%H%M%S"
        )

        report_path = (
            output_directory
            / (
                f"{safe_prefix}_export_report_"
                f"{timestamp}.json"
            )
        )

    save_export_report(
        result=result,
        report_path=report_path,
    )

    return result


def print_vector_export_summary(
    result: VectorExportResult,
) -> None:
    """Muestra el resultado en la terminal."""

    print("=" * 72)
    print("EXPORTACIÓN DE DETECCIONES A FORMATOS GIS")
    print("=" * 72)

    print(f"CSV de entrada: {result.input_csv}")

    print(
        "Estado: "
        f"{'COMPLETADO' if result.success else 'ERROR'}"
    )

    if result.metadata:
        print(
            "Detecciones exportadas: "
            f"{result.metadata['output_rows']}"
        )

        print(
            f"CRS: {result.metadata['crs']}"
        )

        print(
            "Tipo de geometría: "
            f"{result.metadata['verification']['geometry_type']}"
        )

        print(
            "Tiempo: "
            f"{result.metadata['elapsed_seconds']} segundos"
        )

    if result.output_csv:
        print(
            f"CSV estructurado: {result.output_csv}"
        )

    if result.output_gpkg:
        print(
            f"GeoPackage: {result.output_gpkg}"
        )

        print(
            f"Capa: {result.layer_name}"
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
            f"\nInforme: {result.report_path}"
        )

    print("=" * 72)


def run_vector_export(
    input_csv: str | Path,
    output_dir: str | Path | None = None,
    name_prefix: str = "inventario_banano_raw",
    layer_name: str = "detecciones_raw",
) -> int:
    """Ejecuta la exportación desde main.py."""

    result = export_detection_vectors(
        input_csv=input_csv,
        output_dir=output_dir,
        name_prefix=name_prefix,
        layer_name=layer_name,
    )

    print_vector_export_summary(
        result
    )

    return 0 if result.success else 1