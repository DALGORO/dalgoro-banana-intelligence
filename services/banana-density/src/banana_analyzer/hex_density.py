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
import yaml
from pyproj import CRS
from shapely.geometry import Polygon


PROJECT_ROOT = Path(__file__).resolve().parents[2]
GLOBAL_LOGS_DIRECTORY = PROJECT_ROOT / "logs"
DEFAULT_CONFIG_PATH = PROJECT_ROOT / "config" / "spatial_analysis.yaml"


@dataclass
class HexDensityResult:
    """Resultado de la generación del mapa de densidad hexagonal."""

    success: bool
    started_at: str
    finished_at: str | None
    inventory_gpkg: str
    boundary_gpkg: str
    inventory_layer: str
    boundary_layer: str
    config_path: str
    requested_reference_density: float | None
    output_directory: str | None = None
    density_csv: str | None = None
    density_gpkg: str | None = None
    deficit_gpkg: str | None = None
    high_density_gpkg: str | None = None
    summary_csv: str | None = None
    report_path: str | None = None
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


def load_hex_config(config_path: Path) -> dict[str, Any]:
    """Carga y valida la sección hexagons del YAML."""

    if not config_path.is_file():
        raise FileNotFoundError(
            f"No existe el archivo de configuración: {config_path}"
        )

    with config_path.open("r", encoding="utf-8") as file:
        config = yaml.safe_load(file)

    if not isinstance(config, dict):
        raise ValueError("La configuración YAML no contiene un diccionario.")

    if "hexagons" not in config or not isinstance(config["hexagons"], dict):
        raise ValueError("La configuración no contiene la sección hexagons.")

    hex_config = config["hexagons"]

    defaults: dict[str, Any] = {
        "area_m2": 100.0,
        "min_coverage_ratio": 0.50,
        "reference_coverage_ratio": 0.90,
        "reference_exclude_zero": True,
        "deficit_severe_ratio": 0.70,
        "deficit_moderate_ratio": 0.90,
        "expected_upper_ratio": 1.10,
        "elevated_upper_ratio": 1.25,
    }

    merged = {**defaults, **hex_config}

    numeric_keys = (
        "area_m2",
        "min_coverage_ratio",
        "reference_coverage_ratio",
        "deficit_severe_ratio",
        "deficit_moderate_ratio",
        "expected_upper_ratio",
        "elevated_upper_ratio",
    )

    for key in numeric_keys:
        value = float(merged[key])
        if not math.isfinite(value):
            raise ValueError(f"hexagons.{key} debe ser un número finito.")
        merged[key] = value

    if merged["area_m2"] <= 0:
        raise ValueError("hexagons.area_m2 debe ser mayor que cero.")

    for key in ("min_coverage_ratio", "reference_coverage_ratio"):
        if not 0.0 < merged[key] <= 1.0:
            raise ValueError(f"hexagons.{key} debe estar entre 0 y 1.")

    ordered_thresholds = (
        merged["deficit_severe_ratio"],
        merged["deficit_moderate_ratio"],
        merged["expected_upper_ratio"],
        merged["elevated_upper_ratio"],
    )

    if not (
        0.0
        < ordered_thresholds[0]
        < ordered_thresholds[1]
        < ordered_thresholds[2]
        < ordered_thresholds[3]
    ):
        raise ValueError(
            "Los umbrales de clasificación hexagonal deben ser "
            "positivos y estrictamente crecientes."
        )

    merged["reference_exclude_zero"] = bool(
        merged["reference_exclude_zero"]
    )

    return merged


def resolve_output_directory(
    inventory_gpkg: Path,
    output_dir: str | Path | None,
) -> Path:
    """Determina la carpeta de salida del mapa hexagonal."""

    if output_dir is not None:
        return Path(output_dir).expanduser().resolve(strict=False)

    return inventory_gpkg.parent / "densidad_hexagonal"


def read_inputs(
    inventory_gpkg: Path,
    boundary_gpkg: Path,
    inventory_layer: str,
    boundary_layer: str,
) -> tuple[gpd.GeoDataFrame, gpd.GeoDataFrame]:
    """Lee y valida el inventario y el límite."""

    if not inventory_gpkg.is_file():
        raise FileNotFoundError(f"No existe el inventario: {inventory_gpkg}")

    if not boundary_gpkg.is_file():
        raise FileNotFoundError(f"No existe el límite: {boundary_gpkg}")

    inventory = gpd.read_file(
        inventory_gpkg,
        layer=inventory_layer,
        engine="pyogrio",
    )

    boundary = gpd.read_file(
        boundary_gpkg,
        layer=boundary_layer,
        engine="pyogrio",
    )

    if inventory.empty:
        raise ValueError("El inventario validado está vacío.")

    if boundary.empty:
        raise ValueError("La capa de límite está vacía.")

    if inventory.crs is None or boundary.crs is None:
        raise ValueError("Las capas de entrada deben tener CRS.")

    if inventory.crs != boundary.crs:
        boundary = boundary.to_crs(inventory.crs)

    crs = CRS.from_user_input(inventory.crs)

    if not crs.is_projected:
        raise ValueError("El análisis requiere un CRS proyectado.")

    unit_names = [
        axis.unit_name.lower()
        for axis in crs.axis_info
        if axis.unit_name
    ]

    if not unit_names or not all(
        "metre" in unit_name or "meter" in unit_name
        for unit_name in unit_names
    ):
        raise ValueError("El CRS debe utilizar metros.")

    if inventory.geometry.geom_type.ne("Point").any():
        raise ValueError("El inventario debe contener solamente puntos.")

    if inventory.geometry.is_empty.any():
        raise ValueError("El inventario contiene geometrías vacías.")

    if not inventory.geometry.is_valid.all():
        raise ValueError("El inventario contiene geometrías inválidas.")

    if not boundary.geometry.is_valid.all():
        raise ValueError("El límite contiene geometrías inválidas.")

    boundary_geometry = boundary.geometry.union_all()

    if boundary_geometry.is_empty:
        raise ValueError("La geometría unificada del límite está vacía.")

    outside_mask = ~inventory.geometry.apply(boundary_geometry.covers)

    if outside_mask.any():
        raise ValueError(
            f"El inventario contiene {int(outside_mask.sum())} puntos fuera "
            "del límite. Utilice el inventario espacialmente validado."
        )

    return inventory.reset_index(drop=True), boundary


def regular_hexagon(center_x: float, center_y: float, side_m: float) -> Polygon:
    """Construye un hexágono regular con orientación de punta vertical."""

    vertices = []

    for index in range(6):
        angle = math.radians(30.0 + 60.0 * index)
        vertices.append(
            (
                center_x + side_m * math.cos(angle),
                center_y + side_m * math.sin(angle),
            )
        )

    return Polygon(vertices)


def build_hex_grid(
    boundary: gpd.GeoDataFrame,
    nominal_area_m2: float,
) -> tuple[gpd.GeoDataFrame, gpd.GeoDataFrame, dict[str, float]]:
    """Construye la malla completa y su versión recortada por el límite."""

    boundary_geometry = boundary.geometry.union_all()
    min_x, min_y, max_x, max_y = boundary_geometry.bounds

    side_m = math.sqrt(
        (2.0 * nominal_area_m2) / (3.0 * math.sqrt(3.0))
    )

    hex_width_m = math.sqrt(3.0) * side_m
    row_step_m = 1.5 * side_m

    start_x = min_x - 2.0 * hex_width_m
    end_x = max_x + 2.0 * hex_width_m
    start_y = min_y - 2.0 * side_m
    end_y = max_y + 2.0 * side_m

    full_records: list[dict[str, Any]] = []
    clipped_records: list[dict[str, Any]] = []
    full_geometries: list[Polygon] = []
    clipped_geometries: list[Any] = []

    row_index = 0
    center_y = start_y
    sequence = 0

    while center_y <= end_y:
        row_shift = hex_width_m / 2.0 if row_index % 2 else 0.0
        center_x = start_x + row_shift
        column_index = 0

        while center_x <= end_x:
            geometry = regular_hexagon(center_x, center_y, side_m)

            if geometry.intersects(boundary_geometry):
                clipped_geometry = geometry.intersection(boundary_geometry)

                if not clipped_geometry.is_empty:
                    clipped_area_m2 = float(clipped_geometry.area)

                    if clipped_area_m2 > 1e-9:
                        sequence += 1
                        hex_id = f"hex_{sequence:06d}"
                        coverage_ratio = clipped_area_m2 / nominal_area_m2

                        common_record = {
                            "hex_id": hex_id,
                            "grid_row": row_index,
                            "grid_col": column_index,
                            "center_x": float(center_x),
                            "center_y": float(center_y),
                            "nominal_area_m2": float(nominal_area_m2),
                            "clipped_area_m2": clipped_area_m2,
                            "coverage_ratio": coverage_ratio,
                        }

                        full_records.append(common_record.copy())
                        clipped_records.append(common_record.copy())
                        full_geometries.append(geometry)
                        clipped_geometries.append(clipped_geometry)

            center_x += hex_width_m
            column_index += 1

        center_y += row_step_m
        row_index += 1

    if not full_records:
        raise RuntimeError("No fue posible construir hexágonos sobre el límite.")

    full_grid = gpd.GeoDataFrame(
        full_records,
        geometry=full_geometries,
        crs=boundary.crs,
    )

    clipped_grid = gpd.GeoDataFrame(
        clipped_records,
        geometry=clipped_geometries,
        crs=boundary.crs,
    )

    metrics = {
        "side_m": float(side_m),
        "hex_width_m": float(hex_width_m),
        "hex_height_m": float(2.0 * side_m),
        "row_step_m": float(row_step_m),
    }

    return full_grid, clipped_grid, metrics


def assign_points_to_hexagons(
    inventory: gpd.GeoDataFrame,
    full_grid: gpd.GeoDataFrame,
) -> pd.Series:
    """Asigna cada planta a un único hexágono de forma determinista."""

    points = inventory[["geometry"]].copy()
    points["point_index"] = np.arange(len(points), dtype=int)

    join_grid = full_grid[["hex_id", "geometry"]].copy()

    joined = gpd.sjoin(
        points,
        join_grid,
        how="left",
        predicate="within",
    )

    assignments = joined.loc[
        joined["hex_id"].notna(),
        ["point_index", "hex_id"],
    ].copy()

    assignments = assignments.sort_values(
        ["point_index", "hex_id"],
        kind="stable",
    ).drop_duplicates("point_index", keep="first")

    matched_indices = set(assignments["point_index"].astype(int))
    all_indices = set(range(len(points)))
    missing_indices = sorted(all_indices - matched_indices)

    if missing_indices:
        fallback_points = points.loc[
            points["point_index"].isin(missing_indices)
        ]

        fallback = gpd.sjoin(
            fallback_points,
            join_grid,
            how="left",
            predicate="intersects",
        )

        fallback = fallback.loc[
            fallback["hex_id"].notna(),
            ["point_index", "hex_id"],
        ].sort_values(
            ["point_index", "hex_id"],
            kind="stable",
        ).drop_duplicates("point_index", keep="first")

        assignments = pd.concat(
            [assignments, fallback],
            ignore_index=True,
        )

    assignments = assignments.sort_values("point_index", kind="stable")

    if len(assignments) != len(points):
        missing_count = len(points) - len(assignments)
        raise RuntimeError(
            f"No fue posible asignar {missing_count} plantas a la malla."
        )

    if assignments["point_index"].duplicated().any():
        raise RuntimeError("Una planta fue asignada a más de un hexágono.")

    return assignments.set_index("point_index")["hex_id"]


def estimate_reference_density(
    density_grid: gpd.GeoDataFrame,
    requested_reference_density: float | None,
    config: dict[str, Any],
) -> tuple[float, str, int]:
    """Determina la densidad de referencia manual o automática."""

    if requested_reference_density is not None:
        value = float(requested_reference_density)

        if not math.isfinite(value) or value <= 0:
            raise ValueError(
                "La densidad de referencia manual debe ser mayor que cero."
            )

        return value, "manual_producer_target", 0

    candidates = density_grid.loc[
        density_grid["coverage_ratio"]
        >= float(config["reference_coverage_ratio"])
    ].copy()

    if bool(config["reference_exclude_zero"]):
        candidates = candidates.loc[candidates["plant_count"] > 0]

    if candidates.empty:
        candidates = density_grid.loc[
            density_grid["coverage_ratio"]
            >= float(config["min_coverage_ratio"])
        ].copy()

        if bool(config["reference_exclude_zero"]):
            candidates = candidates.loc[candidates["plant_count"] > 0]

    if candidates.empty:
        raise ValueError(
            "No existen hexágonos suficientes para estimar la densidad "
            "de referencia."
        )

    reference_density = float(candidates["plants_per_ha"].median())

    if not math.isfinite(reference_density) or reference_density <= 0:
        raise ValueError("La densidad de referencia calculada es inválida.")

    return (
        reference_density,
        "median_high_coverage_positive_hexagons",
        int(len(candidates)),
    )


def classify_density(
    density_ratio: float,
    coverage_ratio: float,
    config: dict[str, Any],
) -> tuple[str, str, int]:
    """Clasifica una celda y asigna una prioridad operativa."""

    if coverage_ratio < float(config["min_coverage_ratio"]):
        return (
            "borde_no_evaluable",
            "no_interpretar_sin_revision",
            0,
        )

    if density_ratio < float(config["deficit_severe_ratio"]):
        return (
            "deficit_severo",
            "revisar_resiembra_o_zona_no_sembrada",
            5,
        )

    if density_ratio < float(config["deficit_moderate_ratio"]):
        return (
            "deficit_moderado",
            "verificacion_prioritaria",
            4,
        )

    if density_ratio <= float(config["expected_upper_ratio"]):
        return (
            "densidad_esperada",
            "sin_alerta",
            1,
        )

    if density_ratio <= float(config["elevated_upper_ratio"]):
        return (
            "densidad_elevada",
            "revisar_competencia_local",
            3,
        )

    return (
        "densidad_muy_elevada",
        "revisar_competencia_y_duplicados_residuales",
        4,
    )


def calculate_density_grid(
    inventory: gpd.GeoDataFrame,
    boundary: gpd.GeoDataFrame,
    nominal_area_m2: float,
    requested_reference_density: float | None,
    config: dict[str, Any],
) -> tuple[gpd.GeoDataFrame, dict[str, Any]]:
    """Genera la malla, cuenta plantas y calcula densidades."""

    full_grid, clipped_grid, grid_metrics = build_hex_grid(
        boundary=boundary,
        nominal_area_m2=nominal_area_m2,
    )

    assignments = assign_points_to_hexagons(
        inventory=inventory,
        full_grid=full_grid,
    )

    counts = assignments.value_counts().astype(int)

    density_grid = clipped_grid.copy()
    density_grid["plant_count"] = (
        density_grid["hex_id"].map(counts).fillna(0).astype(int)
    )
    density_grid["area_ha"] = density_grid["clipped_area_m2"] / 10000.0
    density_grid["plants_per_ha"] = np.where(
        density_grid["clipped_area_m2"] > 0,
        density_grid["plant_count"]
        / density_grid["clipped_area_m2"]
        * 10000.0,
        np.nan,
    )

    reference_density, reference_method, reference_cells = (
        estimate_reference_density(
            density_grid=density_grid,
            requested_reference_density=requested_reference_density,
            config=config,
        )
    )

    density_grid["reference_plants_ha"] = reference_density
    density_grid["density_ratio"] = (
        density_grid["plants_per_ha"] / reference_density
    )
    density_grid["density_percent_ref"] = (
        density_grid["density_ratio"] * 100.0
    )

    classifications = density_grid.apply(
        lambda row: classify_density(
            density_ratio=float(row["density_ratio"]),
            coverage_ratio=float(row["coverage_ratio"]),
            config=config,
        ),
        axis=1,
    )

    density_grid["density_class"] = [value[0] for value in classifications]
    density_grid["management_action"] = [value[1] for value in classifications]
    density_grid["priority_level"] = [value[2] for value in classifications]
    density_grid["is_evaluable"] = (
        density_grid["coverage_ratio"]
        >= float(config["min_coverage_ratio"])
    )

    total_assigned = int(density_grid["plant_count"].sum())

    if total_assigned != len(inventory):
        raise RuntimeError(
            "La suma de plantas por hexágono no coincide con el inventario."
        )

    boundary_area_m2 = float(boundary.geometry.union_all().area)
    grid_area_m2 = float(density_grid["clipped_area_m2"].sum())
    area_error_percent = (
        abs(grid_area_m2 - boundary_area_m2) / boundary_area_m2 * 100.0
    )

    if area_error_percent > 0.10:
        raise RuntimeError(
            "La suma del área hexagonal recortada no coincide con el límite "
            f"dentro de la tolerancia: {area_error_percent:.6f} %."
        )

    metrics = {
        "grid": grid_metrics,
        "reference_density_plants_ha": reference_density,
        "reference_method": reference_method,
        "reference_cells": reference_cells,
        "boundary_area_m2": boundary_area_m2,
        "grid_clipped_area_m2": grid_area_m2,
        "area_closure_error_percent": area_error_percent,
    }

    return density_grid, metrics


def build_class_summary(
    density_grid: gpd.GeoDataFrame,
) -> list[dict[str, Any]]:
    """Resume cantidad, superficie y plantas por clase."""

    records: list[dict[str, Any]] = []

    for density_class, group in density_grid.groupby(
        "density_class",
        sort=True,
    ):
        records.append(
            {
                "density_class": str(density_class),
                "hexagons": int(len(group)),
                "area_m2": round(float(group["clipped_area_m2"].sum()), 4),
                "area_ha": round(float(group["area_ha"].sum()), 6),
                "plants": int(group["plant_count"].sum()),
                "mean_plants_per_ha": round(
                    float(group["plants_per_ha"].mean()),
                    4,
                ),
            }
        )

    return records


def write_csv_atomic(table: pd.DataFrame, output_path: Path) -> None:
    """Escribe un CSV sin dejar archivos parciales."""

    temporary_path = output_path.with_suffix(".partial.csv")

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

    temporary_path = output_path.with_suffix(".partial.gpkg")

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
    """Reabre y verifica una salida GeoPackage."""

    layers = pyogrio.list_layers(gpkg_path)
    verified = gpd.read_file(
        gpkg_path,
        layer=layer_name,
        engine="pyogrio",
    )

    if len(verified) != expected_rows:
        raise RuntimeError(
            "La cantidad de elementos del GeoPackage no coincide."
        )

    if verified.crs is None:
        raise RuntimeError("El GeoPackage generado no tiene CRS.")

    if not verified.geometry.is_valid.all():
        raise RuntimeError("El GeoPackage contiene geometrías inválidas.")

    return {
        "layers": layers.tolist(),
        "rows": int(len(verified)),
        "crs": verified.crs.to_string(),
        "epsg": verified.crs.to_epsg(),
        "geometry_types": sorted(
            verified.geometry.geom_type.unique().tolist()
        ),
    }


def save_report(result: HexDensityResult, report_path: Path) -> Path:
    """Guarda el informe JSON."""

    result.report_path = str(report_path)

    with report_path.open("w", encoding="utf-8") as file:
        json.dump(
            asdict(result),
            file,
            ensure_ascii=False,
            indent=4,
        )

    return report_path


def generate_hex_density(
    inventory_gpkg: str | Path,
    boundary_gpkg: str | Path,
    inventory_layer: str = "plantas_banano_validas",
    boundary_layer: str = "limite_analisis",
    config_path: str | Path | None = None,
    reference_density: float | None = None,
    output_dir: str | Path | None = None,
) -> HexDensityResult:
    """Genera el mapa operativo de densidad por hexágonos."""

    started_at = datetime.now().isoformat(timespec="seconds")
    start_time = time.perf_counter()

    normalized_inventory_gpkg = Path(inventory_gpkg).expanduser().resolve(
        strict=False
    )
    normalized_boundary_gpkg = Path(boundary_gpkg).expanduser().resolve(
        strict=False
    )
    normalized_config_path = (
        Path(config_path)
        if config_path is not None
        else DEFAULT_CONFIG_PATH
    ).expanduser().resolve(strict=False)

    result = HexDensityResult(
        success=False,
        started_at=started_at,
        finished_at=None,
        inventory_gpkg=str(normalized_inventory_gpkg),
        boundary_gpkg=str(normalized_boundary_gpkg),
        inventory_layer=inventory_layer,
        boundary_layer=boundary_layer,
        config_path=str(normalized_config_path),
        requested_reference_density=reference_density,
    )

    output_directory = resolve_output_directory(
        inventory_gpkg=normalized_inventory_gpkg,
        output_dir=output_dir,
    )
    result.output_directory = str(output_directory)

    density_csv_path = output_directory / "densidad_hexagonal.csv"
    density_gpkg_path = output_directory / "densidad_hexagonal.gpkg"
    deficit_gpkg_path = output_directory / "zonas_deficit.gpkg"
    high_density_gpkg_path = output_directory / "zonas_alta_densidad.gpkg"
    summary_csv_path = output_directory / "resumen_densidad_hexagonal.csv"
    report_path = output_directory / "densidad_hexagonal.json"

    expected_outputs = (
        density_csv_path,
        density_gpkg_path,
        deficit_gpkg_path,
        high_density_gpkg_path,
        summary_csv_path,
        report_path,
    )

    existing_outputs = [path for path in expected_outputs if path.exists()]

    if existing_outputs:
        result.errors.append(
            "No se sobrescribirán salidas existentes: "
            + ", ".join(str(path) for path in existing_outputs)
        )

    if result.errors:
        result.finished_at = datetime.now().isoformat(timespec="seconds")
        GLOBAL_LOGS_DIRECTORY.mkdir(parents=True, exist_ok=True)
        error_report = GLOBAL_LOGS_DIRECTORY / (
            "hex_density_error_"
            + datetime.now().strftime("%Y%m%d_%H%M%S")
            + ".json"
        )
        save_report(result, error_report)
        return result

    output_directory.mkdir(parents=True, exist_ok=True)
    generated_paths: list[Path] = []

    try:
        config = load_hex_config(normalized_config_path)

        inventory, boundary = read_inputs(
            inventory_gpkg=normalized_inventory_gpkg,
            boundary_gpkg=normalized_boundary_gpkg,
            inventory_layer=inventory_layer,
            boundary_layer=boundary_layer,
        )

        density_grid, calculation_metrics = calculate_density_grid(
            inventory=inventory,
            boundary=boundary,
            nominal_area_m2=float(config["area_m2"]),
            requested_reference_density=reference_density,
            config=config,
        )

        density_without_geometry = pd.DataFrame(
            density_grid.drop(columns="geometry")
        )

        write_csv_atomic(density_without_geometry, density_csv_path)
        generated_paths.append(density_csv_path)

        write_gpkg_atomic(
            density_grid,
            density_gpkg_path,
            "densidad_hexagonal",
        )
        generated_paths.append(density_gpkg_path)

        deficit = density_grid.loc[
            density_grid["density_class"].isin(
                ["deficit_severo", "deficit_moderado"]
            )
        ].copy()

        high_density = density_grid.loc[
            density_grid["density_class"].isin(
                ["densidad_elevada", "densidad_muy_elevada"]
            )
        ].copy()

        if not deficit.empty:
            write_gpkg_atomic(
                deficit,
                deficit_gpkg_path,
                "zonas_deficit",
            )
            generated_paths.append(deficit_gpkg_path)
            result.deficit_gpkg = str(deficit_gpkg_path)
        else:
            result.warnings.append(
                "No se generó zonas_deficit.gpkg porque no existen "
                "hexágonos clasificados con déficit."
            )

        if not high_density.empty:
            write_gpkg_atomic(
                high_density,
                high_density_gpkg_path,
                "zonas_alta_densidad",
            )
            generated_paths.append(high_density_gpkg_path)
            result.high_density_gpkg = str(high_density_gpkg_path)
        else:
            result.warnings.append(
                "No se generó zonas_alta_densidad.gpkg porque no existen "
                "hexágonos clasificados con alta densidad."
            )

        class_summary = build_class_summary(density_grid)

        boundary_area_m2 = float(calculation_metrics["boundary_area_m2"])
        overall_density = len(inventory) / boundary_area_m2 * 10000.0

        summary_record = {
            "fecha_proceso": datetime.now().isoformat(timespec="seconds"),
            "epsg": inventory.crs.to_epsg(),
            "plantas_inventario": int(len(inventory)),
            "area_limite_m2": round(boundary_area_m2, 4),
            "area_limite_ha": round(boundary_area_m2 / 10000.0, 6),
            "densidad_global_plantas_ha": round(overall_density, 4),
            "area_nominal_hexagono_m2": round(float(config["area_m2"]), 4),
            "hexagonos_totales": int(len(density_grid)),
            "hexagonos_evaluables": int(density_grid["is_evaluable"].sum()),
            "densidad_referencia_plantas_ha": round(
                float(calculation_metrics["reference_density_plants_ha"]),
                4,
            ),
            "metodo_densidad_referencia": calculation_metrics[
                "reference_method"
            ],
            "celdas_referencia": int(calculation_metrics["reference_cells"]),
            "hexagonos_deficit_severo": int(
                (density_grid["density_class"] == "deficit_severo").sum()
            ),
            "hexagonos_deficit_moderado": int(
                (density_grid["density_class"] == "deficit_moderado").sum()
            ),
            "hexagonos_densidad_esperada": int(
                (density_grid["density_class"] == "densidad_esperada").sum()
            ),
            "hexagonos_densidad_elevada": int(
                (density_grid["density_class"] == "densidad_elevada").sum()
            ),
            "hexagonos_densidad_muy_elevada": int(
                (
                    density_grid["density_class"]
                    == "densidad_muy_elevada"
                ).sum()
            ),
            "hexagonos_borde_no_evaluable": int(
                (density_grid["density_class"] == "borde_no_evaluable").sum()
            ),
        }

        write_csv_atomic(pd.DataFrame([summary_record]), summary_csv_path)
        generated_paths.append(summary_csv_path)

        density_verification = verify_gpkg(
            density_gpkg_path,
            "densidad_hexagonal",
            len(density_grid),
        )

        deficit_verification = None
        if result.deficit_gpkg:
            deficit_verification = verify_gpkg(
                deficit_gpkg_path,
                "zonas_deficit",
                len(deficit),
            )

        high_density_verification = None
        if result.high_density_gpkg:
            high_density_verification = verify_gpkg(
                high_density_gpkg_path,
                "zonas_alta_densidad",
                len(high_density),
            )

        result.density_csv = str(density_csv_path)
        result.density_gpkg = str(density_gpkg_path)
        result.summary_csv = str(summary_csv_path)

        result.metadata = {
            "inventory": {
                "plants": int(len(inventory)),
                "epsg": inventory.crs.to_epsg(),
                "crs": inventory.crs.to_string(),
            },
            "boundary": {
                "area_m2": round(boundary_area_m2, 6),
                "area_ha": round(boundary_area_m2 / 10000.0, 8),
                "overall_density_plants_ha": round(overall_density, 6),
            },
            "hexagons": {
                "nominal_area_m2": float(config["area_m2"]),
                "total": int(len(density_grid)),
                "evaluable": int(density_grid["is_evaluable"].sum()),
                "minimum_coverage_ratio": float(
                    config["min_coverage_ratio"]
                ),
                "grid_dimensions": calculation_metrics["grid"],
                "area_closure_error_percent": round(
                    float(calculation_metrics["area_closure_error_percent"]),
                    10,
                ),
            },
            "reference_density": {
                "plants_per_ha": round(
                    float(calculation_metrics["reference_density_plants_ha"]),
                    6,
                ),
                "method": calculation_metrics["reference_method"],
                "cells_used": int(calculation_metrics["reference_cells"]),
                "manual_value_requested": reference_density,
            },
            "classification_thresholds": {
                "deficit_severe_below_ratio": float(
                    config["deficit_severe_ratio"]
                ),
                "deficit_moderate_below_ratio": float(
                    config["deficit_moderate_ratio"]
                ),
                "expected_up_to_ratio": float(
                    config["expected_upper_ratio"]
                ),
                "elevated_up_to_ratio": float(
                    config["elevated_upper_ratio"]
                ),
                "very_elevated_above_ratio": float(
                    config["elevated_upper_ratio"]
                ),
            },
            "class_summary": class_summary,
            "verification": {
                "density": density_verification,
                "deficit": deficit_verification,
                "high_density": high_density_verification,
            },
            "elapsed_seconds": round(time.perf_counter() - start_time, 3),
        }

        result.warnings.append(
            "Las clases de densidad son indicadores de gestión. Las zonas de "
            "déficit deben verificarse frente a caminos, canales, bordes e "
            "infraestructura antes de recomendar resiembra."
        )

        if reference_density is None:
            result.warnings.append(
                "La densidad de referencia fue estimada automáticamente con "
                "la mediana de hexágonos interiores de alta cobertura. Puede "
                "reemplazarse por la meta técnica del productor."
            )

        result.success = True

    except Exception as error:
        result.errors.append(
            "No fue posible generar la densidad hexagonal: "
            f"{type(error).__name__}: {error}"
        )

        for generated_path in generated_paths:
            if generated_path.exists():
                try:
                    generated_path.unlink()
                except OSError:
                    result.warnings.append(
                        "No fue posible eliminar una salida incompleta: "
                        f"{generated_path}"
                    )

    result.finished_at = datetime.now().isoformat(timespec="seconds")
    save_report(result, report_path)
    return result


def print_hex_density_summary(result: HexDensityResult) -> None:
    """Muestra el resumen en la terminal."""

    print("=" * 72)
    print("MAPA OPERATIVO DE DENSIDAD POR HEXÁGONOS")
    print("=" * 72)
    print(f"Inventario: {result.inventory_gpkg}")
    print(f"Límite: {result.boundary_gpkg}")
    print(
        "Estado: "
        f"{'COMPLETADO' if result.success else 'ERROR'}"
    )

    if result.metadata:
        boundary = result.metadata["boundary"]
        hexagons = result.metadata["hexagons"]
        reference = result.metadata["reference_density"]

        print(f"Plantas: {result.metadata['inventory']['plants']}")
        print(f"Área: {boundary['area_ha']} ha")
        print(
            "Densidad global: "
            f"{boundary['overall_density_plants_ha']} plantas/ha"
        )
        print(
            "Densidad de referencia: "
            f"{reference['plants_per_ha']} plantas/ha"
        )
        print(f"Método de referencia: {reference['method']}")
        print(f"Hexágonos totales: {hexagons['total']}")
        print(f"Hexágonos evaluables: {hexagons['evaluable']}")
        print(
            "Tiempo: "
            f"{result.metadata['elapsed_seconds']} segundos"
        )

    if result.density_gpkg:
        print(f"Mapa hexagonal: {result.density_gpkg}")

    if result.deficit_gpkg:
        print(f"Zonas de déficit: {result.deficit_gpkg}")

    if result.high_density_gpkg:
        print(f"Zonas de alta densidad: {result.high_density_gpkg}")

    if result.summary_csv:
        print(f"Resumen CSV: {result.summary_csv}")

    if result.errors:
        print("\nERRORES:")
        for error in result.errors:
            print(f"  - {error}")

    if result.warnings:
        print("\nADVERTENCIAS:")
        for warning in result.warnings:
            print(f"  - {warning}")

    if result.report_path:
        print(f"\nInforme: {result.report_path}")

    print("=" * 72)


def run_hex_density(
    inventory_gpkg: str | Path,
    boundary_gpkg: str | Path,
    inventory_layer: str = "plantas_banano_validas",
    boundary_layer: str = "limite_analisis",
    config_path: str | Path | None = None,
    reference_density: float | None = None,
    output_dir: str | Path | None = None,
) -> int:
    """Ejecuta la densidad hexagonal desde main.py."""

    result = generate_hex_density(
        inventory_gpkg=inventory_gpkg,
        boundary_gpkg=boundary_gpkg,
        inventory_layer=inventory_layer,
        boundary_layer=boundary_layer,
        config_path=config_path,
        reference_density=reference_density,
        output_dir=output_dir,
    )

    print_hex_density_summary(result)
    return 0 if result.success else 1
