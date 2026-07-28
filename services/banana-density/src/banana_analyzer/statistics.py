from __future__ import annotations

import json
import math
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

import geopandas as gpd
import numpy as np
import pandas as pd
import pyogrio
from pyproj import CRS

from banana_analyzer.excel_boundary import (
    load_boundary_from_excel,
)


PROJECT_ROOT = Path(__file__).resolve().parents[2]
GLOBAL_LOGS_DIRECTORY = PROJECT_ROOT / "logs"

REQUIRED_COLUMNS = {
    "detection_id",
    "coord_x",
    "coord_y",
    "epsg",
    "confidence",
}


@dataclass
class SpatialStatisticsResult:
    """Resultado de la validación espacial y estadísticas."""

    success: bool
    started_at: str
    finished_at: str | None
    clean_csv: str
    excel_path: str
    raster_path: str
    sheet_reference: str
    output_directory: str | None = None
    validated_csv: str | None = None
    validated_gpkg: str | None = None
    boundary_gpkg: str | None = None
    outside_csv: str | None = None
    outside_gpkg: str | None = None
    summary_csv: str | None = None
    report_path: str | None = None
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


def resolve_output_directory(
    clean_csv: Path,
    output_dir: str | Path | None,
) -> Path:
    """Determina la carpeta de salida."""

    if output_dir is not None:
        return Path(
            output_dir
        ).expanduser().resolve(strict=False)

    if clean_csv.parent.name == "04_detecciones_limpias":
        run_directory = clean_csv.parent.parent
        return run_directory / "05_gis"

    return clean_csv.parent / "gis_statistics"


def validate_input_table(
    table: pd.DataFrame,
) -> list[str]:
    """Valida las columnas mínimas del inventario."""

    errors: list[str] = []

    missing_columns = sorted(
        REQUIRED_COLUMNS - set(table.columns)
    )

    if missing_columns:
        errors.append(
            "Faltan columnas obligatorias: "
            + ", ".join(missing_columns)
        )

    if table.empty:
        errors.append(
            "El inventario deduplicado está vacío."
        )

    return errors


def normalize_inventory(
    table: pd.DataFrame,
) -> tuple[pd.DataFrame, int]:
    """Normaliza coordenadas, EPSG y confianza."""

    normalized = table.copy()

    for column in (
        "coord_x",
        "coord_y",
        "epsg",
        "confidence",
    ):
        normalized[column] = pd.to_numeric(
            normalized[column],
            errors="coerce",
        )

    invalid_mask = (
        normalized["coord_x"].isna()
        | normalized["coord_y"].isna()
        | normalized["epsg"].isna()
        | normalized["confidence"].isna()
        | ~np.isfinite(normalized["coord_x"])
        | ~np.isfinite(normalized["coord_y"])
        | ~np.isfinite(normalized["confidence"])
    )

    if invalid_mask.any():
        affected_rows = [
            int(index + 2)
            for index in normalized.index[invalid_mask]
        ]

        raise ValueError(
            "Existen coordenadas, EPSG o confianza "
            f"inválidos en las filas: {affected_rows}."
        )

    if not normalized["confidence"].between(
        0.0,
        1.0,
    ).all():
        raise ValueError(
            "La columna confidence contiene valores "
            "fuera del intervalo de 0 a 1."
        )

    if normalized["detection_id"].isna().any():
        raise ValueError(
            "Existen detection_id vacíos."
        )

    if normalized["detection_id"].duplicated().any():
        duplicated_ids = (
            normalized.loc[
                normalized["detection_id"].duplicated(
                    keep=False
                ),
                "detection_id",
            ]
            .astype(str)
            .unique()
            .tolist()
        )

        raise ValueError(
            "Existen detection_id repetidos: "
            f"{duplicated_ids[:20]}."
        )

    epsg_values = sorted(
        {
            int(value)
            for value in normalized["epsg"]
        }
    )

    if len(epsg_values) != 1:
        raise ValueError(
            "El inventario debe contener un solo EPSG. "
            f"Valores encontrados: {epsg_values}."
        )

    epsg_code = epsg_values[0]
    crs = CRS.from_epsg(epsg_code)

    if not crs.is_projected:
        raise ValueError(
            "El inventario debe utilizar un CRS proyectado."
        )

    unit_names = [
        axis.unit_name.lower()
        for axis in crs.axis_info
        if axis.unit_name
    ]

    if not unit_names or not all(
        "metre" in unit_name
        or "meter" in unit_name
        for unit_name in unit_names
    ):
        raise ValueError(
            "El CRS debe utilizar metros para calcular "
            "superficie y densidad."
        )

    normalized["epsg"] = normalized["epsg"].astype(int)

    return normalized, epsg_code


def build_point_layer(
    table: pd.DataFrame,
    epsg_code: int,
) -> gpd.GeoDataFrame:
    """Construye una capa de puntos."""

    geometry = gpd.points_from_xy(
        table["coord_x"],
        table["coord_y"],
    )

    points = gpd.GeoDataFrame(
        table.copy(),
        geometry=geometry,
        crs=f"EPSG:{epsg_code}",
    )

    if points.geometry.is_empty.any():
        raise ValueError(
            "El inventario contiene geometrías vacías."
        )

    if not points.geometry.is_valid.all():
        raise ValueError(
            "El inventario contiene geometrías inválidas."
        )

    return points


def classify_points_by_boundary(
    points: gpd.GeoDataFrame,
    boundary: gpd.GeoDataFrame,
) -> tuple[
    gpd.GeoDataFrame,
    gpd.GeoDataFrame,
    gpd.GeoDataFrame,
]:
    """
    Separa detecciones dentro y fuera del límite.

    Se consideran válidos también los puntos situados
    exactamente sobre el borde del polígono.
    """

    if boundary.crs is None:
        raise ValueError(
            "El límite no tiene CRS."
        )

    if points.crs is None:
        raise ValueError(
            "La capa de puntos no tiene CRS."
        )

    if points.crs != boundary.crs:
        points = points.to_crs(boundary.crs)

    boundary_geometry = boundary.geometry.union_all()

    if boundary_geometry.is_empty:
        raise ValueError(
            "La geometría del límite está vacía."
        )

    inside_mask = points.geometry.apply(
        boundary_geometry.covers
    )

    inside = points.loc[
        inside_mask
    ].copy()

    outside = points.loc[
        ~inside_mask
    ].copy()

    return inside, outside, boundary


def calculate_class_distribution(
    points: gpd.GeoDataFrame,
) -> dict[str, int]:
    """Calcula la distribución de detecciones por clase."""

    if "class_name" in points.columns:
        field_name = "class_name"
    elif "class_id" in points.columns:
        field_name = "class_id"
    else:
        return {}

    counts = (
        points[field_name]
        .astype(str)
        .value_counts(dropna=False)
    )

    return {
        str(class_value): int(count)
        for class_value, count in counts.items()
    }


def calculate_confidence_statistics(
    points: gpd.GeoDataFrame,
) -> dict[str, float | None]:
    """Calcula estadísticas de confianza del modelo."""

    if points.empty:
        return {
            "minimum": None,
            "mean": None,
            "median": None,
            "maximum": None,
            "standard_deviation": None,
        }

    confidence = pd.to_numeric(
        points["confidence"],
        errors="coerce",
    )

    return {
        "minimum": round(
            float(confidence.min()),
            6,
        ),
        "mean": round(
            float(confidence.mean()),
            6,
        ),
        "median": round(
            float(confidence.median()),
            6,
        ),
        "maximum": round(
            float(confidence.max()),
            6,
        ),
        "standard_deviation": round(
            float(confidence.std(ddof=0)),
            6,
        ),
    }


def write_csv_atomic(
    table: pd.DataFrame,
    output_path: Path,
) -> None:
    """Escribe un CSV sin dejar archivos parciales."""

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

        temporary_path.replace(output_path)

    finally:
        if temporary_path.exists():
            temporary_path.unlink()


def write_gpkg_atomic(
    geodataframe: gpd.GeoDataFrame,
    output_path: Path,
    layer_name: str,
) -> None:
    """Escribe un GeoPackage mediante archivo temporal."""

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

        temporary_path.replace(output_path)

    finally:
        if temporary_path.exists():
            temporary_path.unlink()


def verify_gpkg(
    gpkg_path: Path,
    layer_name: str,
    expected_rows: int,
) -> dict[str, Any]:
    """Verifica nuevamente el GeoPackage generado."""

    layers = pyogrio.list_layers(gpkg_path)

    verified = gpd.read_file(
        gpkg_path,
        layer=layer_name,
        engine="pyogrio",
    )

    if len(verified) != expected_rows:
        raise RuntimeError(
            "El número de elementos del GeoPackage "
            "no coincide con la salida esperada."
        )

    if verified.crs is None:
        raise RuntimeError(
            "El GeoPackage generado no tiene CRS."
        )

    return {
        "layers": layers.tolist(),
        "rows": int(len(verified)),
        "crs": verified.crs.to_string(),
        "epsg": verified.crs.to_epsg(),
        "geometry_types": sorted(
            verified.geometry.geom_type.unique().tolist()
        ),
    }


def save_report(
    result: SpatialStatisticsResult,
    output_path: Path,
) -> Path:
    """Guarda el informe JSON."""

    result.report_path = str(output_path)

    with output_path.open(
        "w",
        encoding="utf-8",
    ) as file:
        json.dump(
            asdict(result),
            file,
            ensure_ascii=False,
            indent=4,
        )

    return output_path


def calculate_spatial_statistics(
    clean_csv: str | Path,
    excel_path: str | Path,
    raster_path: str | Path,
    sheet_reference: str | int = 0,
    output_dir: str | Path | None = None,
) -> SpatialStatisticsResult:
    """Valida espacialmente el inventario y calcula estadísticas."""

    started_at = datetime.now().isoformat(
        timespec="seconds"
    )

    start_time = time.perf_counter()

    normalized_clean_csv = Path(
        clean_csv
    ).expanduser().resolve(strict=False)

    normalized_excel_path = Path(
        excel_path
    ).expanduser().resolve(strict=False)

    normalized_raster_path = Path(
        raster_path
    ).expanduser().resolve(strict=False)

    result = SpatialStatisticsResult(
        success=False,
        started_at=started_at,
        finished_at=None,
        clean_csv=str(normalized_clean_csv),
        excel_path=str(normalized_excel_path),
        raster_path=str(normalized_raster_path),
        sheet_reference=str(sheet_reference),
    )

    output_directory = resolve_output_directory(
        clean_csv=normalized_clean_csv,
        output_dir=output_dir,
    )

    output_directory.mkdir(
        parents=True,
        exist_ok=True,
    )

    result.output_directory = str(output_directory)

    validated_csv_path = (
        output_directory
        / "inventario_banano_validado.csv"
    )

    validated_gpkg_path = (
        output_directory
        / "inventario_banano_validado.gpkg"
    )

    boundary_gpkg_path = (
        output_directory
        / "limite_analisis.gpkg"
    )

    outside_csv_path = (
        output_directory
        / "detecciones_fuera_limite.csv"
    )

    outside_gpkg_path = (
        output_directory
        / "detecciones_fuera_limite.gpkg"
    )

    summary_csv_path = (
        output_directory
        / "estadisticas_banano.csv"
    )

    report_path = (
        output_directory
        / "estadisticas_banano.json"
    )

    expected_outputs = (
        validated_csv_path,
        validated_gpkg_path,
        boundary_gpkg_path,
        outside_csv_path,
        outside_gpkg_path,
        summary_csv_path,
        report_path,
    )

    if not normalized_clean_csv.is_file():
        result.errors.append(
            "El inventario deduplicado no existe."
        )

    if not normalized_excel_path.is_file():
        result.errors.append(
            "El archivo Excel del límite no existe."
        )

    if not normalized_raster_path.is_file():
        result.errors.append(
            "La ortofoto no existe."
        )

    existing_outputs = [
        path
        for path in expected_outputs
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

    if result.errors:
        result.finished_at = datetime.now().isoformat(
            timespec="seconds"
        )

        error_report = (
            GLOBAL_LOGS_DIRECTORY
            / (
                "statistics_error_"
                + datetime.now().strftime(
                    "%Y%m%d_%H%M%S"
                )
                + ".json"
            )
        )

        save_report(
            result=result,
            output_path=error_report,
        )

        return result

    generated_paths: list[Path] = []

    try:
        table = pd.read_csv(
            normalized_clean_csv,
            encoding="utf-8-sig",
        )

        result.errors.extend(
            validate_input_table(table)
        )

        if result.errors:
            raise ValueError(
                "El inventario no tiene la estructura requerida."
            )

        normalized_table, epsg_code = normalize_inventory(
            table
        )

        points = build_point_layer(
            table=normalized_table,
            epsg_code=epsg_code,
        )

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

            raise ValueError(
                "El límite generado desde Excel no es válido."
            )

        if boundary is None:
            raise ValueError(
                "No se obtuvo el polígono del límite."
            )

        inside, outside, boundary = (
            classify_points_by_boundary(
                points=points,
                boundary=boundary,
            )
        )

        if inside.empty:
            raise ValueError(
                "Ninguna detección se encuentra dentro "
                "del límite de la finca."
            )

        boundary_geometry = (
            boundary.geometry.union_all()
        )

        area_m2 = float(
            boundary_geometry.area
        )

        if not math.isfinite(area_m2) or area_m2 <= 0:
            raise ValueError(
                "El área calculada del límite es inválida."
            )

        area_hectares = area_m2 / 10000.0
        plant_count = int(len(inside))

        plants_per_hectare = (
            plant_count / area_hectares
        )

        plants_per_square_meter = (
            plant_count / area_m2
        )

        duplicates_removed = 0

        if "duplicates_removed_count" in inside.columns:
            duplicates_removed = int(
                pd.to_numeric(
                    inside["duplicates_removed_count"],
                    errors="coerce",
                )
                .fillna(0)
                .sum()
            )

        outside_count = int(len(outside))
        input_count = int(len(points))

        outside_percent = (
            outside_count / input_count * 100.0
            if input_count > 0
            else 0.0
        )

        boundary_output = boundary.copy()

        boundary_output["area_m2"] = area_m2
        boundary_output["area_ha"] = area_hectares
        boundary_output["plantas"] = plant_count
        boundary_output["plantas_ha"] = (
            plants_per_hectare
        )

        inside_without_geometry = pd.DataFrame(
            inside.drop(columns="geometry")
        )

        write_csv_atomic(
            table=inside_without_geometry,
            output_path=validated_csv_path,
        )

        generated_paths.append(
            validated_csv_path
        )

        write_gpkg_atomic(
            geodataframe=inside,
            output_path=validated_gpkg_path,
            layer_name="plantas_banano_validas",
        )

        generated_paths.append(
            validated_gpkg_path
        )

        write_gpkg_atomic(
            geodataframe=boundary_output,
            output_path=boundary_gpkg_path,
            layer_name="limite_analisis",
        )

        generated_paths.append(
            boundary_gpkg_path
        )

        if not outside.empty:
            outside_without_geometry = pd.DataFrame(
                outside.drop(columns="geometry")
            )

            write_csv_atomic(
                table=outside_without_geometry,
                output_path=outside_csv_path,
            )

            generated_paths.append(
                outside_csv_path
            )

            write_gpkg_atomic(
                geodataframe=outside,
                output_path=outside_gpkg_path,
                layer_name="detecciones_fuera_limite",
            )

            generated_paths.append(
                outside_gpkg_path
            )

            result.outside_csv = str(
                outside_csv_path
            )

            result.outside_gpkg = str(
                outside_gpkg_path
            )

        validated_verification = verify_gpkg(
            gpkg_path=validated_gpkg_path,
            layer_name="plantas_banano_validas",
            expected_rows=plant_count,
        )

        boundary_verification = verify_gpkg(
            gpkg_path=boundary_gpkg_path,
            layer_name="limite_analisis",
            expected_rows=len(boundary_output),
        )

        confidence_statistics = (
            calculate_confidence_statistics(
                inside
            )
        )

        class_distribution = (
            calculate_class_distribution(
                inside
            )
        )

        summary_record = {
            "fecha_proceso": datetime.now().isoformat(
                timespec="seconds"
            ),
            "epsg": epsg_code,
            "crs": f"EPSG:{epsg_code}",
            "area_m2": round(area_m2, 4),
            "area_ha": round(area_hectares, 6),
            "detecciones_deduplicadas_entrada": (
                input_count
            ),
            "plantas_dentro_limite": plant_count,
            "detecciones_fuera_limite": outside_count,
            "porcentaje_fuera_limite": round(
                outside_percent,
                6,
            ),
            "duplicados_eliminados_previos": (
                duplicates_removed
            ),
            "plantas_por_hectarea": round(
                plants_per_hectare,
                4,
            ),
            "plantas_por_m2": round(
                plants_per_square_meter,
                8,
            ),
            "confianza_minima": (
                confidence_statistics["minimum"]
            ),
            "confianza_media": (
                confidence_statistics["mean"]
            ),
            "confianza_mediana": (
                confidence_statistics["median"]
            ),
            "confianza_maxima": (
                confidence_statistics["maximum"]
            ),
        }

        summary_table = pd.DataFrame(
            [summary_record]
        )

        write_csv_atomic(
            table=summary_table,
            output_path=summary_csv_path,
        )

        generated_paths.append(
            summary_csv_path
        )

        elapsed_seconds = round(
            time.perf_counter() - start_time,
            3,
        )

        result.validated_csv = str(
            validated_csv_path
        )

        result.validated_gpkg = str(
            validated_gpkg_path
        )

        result.boundary_gpkg = str(
            boundary_gpkg_path
        )

        result.summary_csv = str(
            summary_csv_path
        )

        result.metadata = {
            "input_deduplicated_rows": input_count,
            "plants_inside_boundary": plant_count,
            "detections_outside_boundary": outside_count,
            "outside_boundary_percent": round(
                outside_percent,
                6,
            ),
            "area": {
                "square_meters": round(
                    area_m2,
                    4,
                ),
                "hectares": round(
                    area_hectares,
                    6,
                ),
            },
            "density": {
                "plants_per_hectare": round(
                    plants_per_hectare,
                    4,
                ),
                "plants_per_square_meter": round(
                    plants_per_square_meter,
                    8,
                ),
            },
            "confidence": confidence_statistics,
            "class_distribution": class_distribution,
            "duplicates_removed_before_statistics": (
                duplicates_removed
            ),
            "epsg": epsg_code,
            "crs": f"EPSG:{epsg_code}",
            "boundary_source": (
                boundary_result.metadata
            ),
            "verification": {
                "validated_inventory": (
                    validated_verification
                ),
                "boundary": (
                    boundary_verification
                ),
            },
            "elapsed_seconds": elapsed_seconds,
        }

        if outside_count > 0:
            result.warnings.append(
                f"Se separaron {outside_count} detecciones "
                "situadas fuera del límite de análisis."
            )

        if outside_percent > 1.0:
            result.warnings.append(
                "Más del 1 % de las detecciones deduplicadas "
                "se encuentra fuera del límite. Se recomienda "
                "una revisión visual."
            )

        result.success = True

    except Exception as error:
        result.errors.append(
            "No fue posible calcular las estadísticas: "
            f"{type(error).__name__}: {error}"
        )

        for generated_path in generated_paths:
            if generated_path.exists():
                try:
                    generated_path.unlink()
                except OSError:
                    result.warnings.append(
                        "No fue posible eliminar una salida "
                        f"incompleta: {generated_path}"
                    )

    result.finished_at = datetime.now().isoformat(
        timespec="seconds"
    )

    save_report(
        result=result,
        output_path=report_path,
    )

    return result


def print_statistics_summary(
    result: SpatialStatisticsResult,
) -> None:
    """Muestra un resumen en la terminal."""

    print("=" * 72)
    print("VALIDACIÓN ESPACIAL Y ESTADÍSTICAS DEL INVENTARIO")
    print("=" * 72)

    print(
        f"Inventario deduplicado: {result.clean_csv}"
    )

    print(
        f"Límite Excel: {result.excel_path}"
    )

    print(
        "Estado: "
        f"{'COMPLETADO' if result.success else 'ERROR'}"
    )

    if result.metadata:
        print(
            "Detecciones deduplicadas: "
            f"{result.metadata['input_deduplicated_rows']}"
        )

        print(
            "Plantas dentro del límite: "
            f"{result.metadata['plants_inside_boundary']}"
        )

        print(
            "Detecciones fuera del límite: "
            f"{result.metadata['detections_outside_boundary']}"
        )

        print(
            "Área: "
            f"{result.metadata['area']['hectares']} ha"
        )

        print(
            "Densidad: "
            f"{result.metadata['density']['plants_per_hectare']} "
            "plantas/ha"
        )

        print(
            "Confianza media: "
            f"{result.metadata['confidence']['mean']}"
        )

        print(
            "Tiempo: "
            f"{result.metadata['elapsed_seconds']} segundos"
        )

    if result.validated_csv:
        print(
            f"CSV validado: {result.validated_csv}"
        )

    if result.validated_gpkg:
        print(
            f"GeoPackage validado: {result.validated_gpkg}"
        )

    if result.boundary_gpkg:
        print(
            f"Límite generado: {result.boundary_gpkg}"
        )

    if result.outside_gpkg:
        print(
            "Detecciones fuera del límite: "
            f"{result.outside_gpkg}"
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


def run_spatial_statistics(
    clean_csv: str | Path,
    excel_path: str | Path,
    raster_path: str | Path,
    sheet_reference: str | int = 0,
    output_dir: str | Path | None = None,
) -> int:
    """Ejecuta las estadísticas desde main.py."""

    result = calculate_spatial_statistics(
        clean_csv=clean_csv,
        excel_path=excel_path,
        raster_path=raster_path,
        sheet_reference=sheet_reference,
        output_dir=output_dir,
    )

    print_statistics_summary(result)

    return 0 if result.success else 1