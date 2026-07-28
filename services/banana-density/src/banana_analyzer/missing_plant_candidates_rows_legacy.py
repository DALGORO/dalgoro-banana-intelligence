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
from scipy.spatial import cKDTree
from shapely.geometry import LineString, Point


PROJECT_ROOT = Path(__file__).resolve().parents[2]
GLOBAL_LOGS_DIRECTORY = PROJECT_ROOT / "logs"
DEFAULT_CONFIG_PATH = PROJECT_ROOT / "config" / "spatial_analysis.yaml"


@dataclass
class MissingPlantCandidatesResult:
    """Resultado del análisis de huecos y puestos probablemente faltantes."""

    success: bool
    started_at: str
    finished_at: str | None
    inventory_gpkg: str
    boundary_gpkg: str
    spatial_report_json: str
    inventory_layer: str
    boundary_layer: str
    config_path: str
    requested_orientation_deg: float | None
    requested_within_spacing_m: float | None
    requested_between_spacing_m: float | None
    output_directory: str | None = None
    assigned_points_gpkg: str | None = None
    rows_gpkg: str | None = None
    gaps_gpkg: str | None = None
    candidates_csv: str | None = None
    candidates_gpkg: str | None = None
    summary_csv: str | None = None
    report_path: str | None = None
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


class UnionFind:
    """Estructura mínima para agrupar plantas conectadas en una misma fila."""

    def __init__(self, size: int) -> None:
        self.parent = np.arange(size, dtype=int)
        self.rank = np.zeros(size, dtype=np.uint8)

    def find(self, index: int) -> int:
        parent = int(self.parent[index])
        if parent != index:
            self.parent[index] = self.find(parent)
        return int(self.parent[index])

    def union(self, first: int, second: int) -> None:
        root_first = self.find(first)
        root_second = self.find(second)

        if root_first == root_second:
            return

        if self.rank[root_first] < self.rank[root_second]:
            root_first, root_second = root_second, root_first

        self.parent[root_second] = root_first

        if self.rank[root_first] == self.rank[root_second]:
            self.rank[root_first] += 1


def clamp(value: float, minimum: float, maximum: float) -> float:
    """Limita un valor al intervalo indicado."""

    return max(minimum, min(maximum, value))


def resolve_output_directory(
    inventory_gpkg: Path,
    output_dir: str | Path | None,
) -> Path:
    """Determina la carpeta de salida del análisis de puestos faltantes."""

    if output_dir is not None:
        return Path(output_dir).expanduser().resolve(strict=False)

    if inventory_gpkg.parent.name == "05_gis":
        return inventory_gpkg.parent / "puestos_faltantes"

    return inventory_gpkg.parent / "puestos_faltantes"


def load_gap_config(config_path: Path) -> dict[str, Any]:
    """Carga y valida la configuración de reconstrucción de filas y huecos."""

    if not config_path.is_file():
        raise FileNotFoundError(
            f"No existe el archivo de configuración: {config_path}"
        )

    with config_path.open("r", encoding="utf-8") as file:
        config = yaml.safe_load(file)

    if not isinstance(config, dict):
        raise ValueError("La configuración YAML no contiene un diccionario.")

    gap_config = config.get("gaps", {})

    if not isinstance(gap_config, dict):
        raise ValueError("La sección gaps debe ser un diccionario.")

    defaults: dict[str, Any] = {
        "factor": 1.60,
        "minimum_candidates_per_row": 2,
        "row_cluster_tolerance_factor": 0.35,
        "row_cluster_min_m": 0.60,
        "row_cluster_max_m": 1.50,
        "row_link_max_factor": 6.50,
        "min_plants_per_row": 4,
        "max_missing_per_gap": 5,
        "integer_ratio_tolerance": 0.35,
        "candidate_min_nn_factor": 0.55,
        "boundary_margin_factor": 0.50,
        "row_fit_max_residual_factor": 0.35,
        "high_confidence_threshold": 0.80,
        "medium_confidence_threshold": 0.60,
    }

    merged = {**defaults, **gap_config}

    float_keys = (
        "factor",
        "row_cluster_tolerance_factor",
        "row_cluster_min_m",
        "row_cluster_max_m",
        "row_link_max_factor",
        "integer_ratio_tolerance",
        "candidate_min_nn_factor",
        "boundary_margin_factor",
        "row_fit_max_residual_factor",
        "high_confidence_threshold",
        "medium_confidence_threshold",
    )

    integer_keys = (
        "minimum_candidates_per_row",
        "min_plants_per_row",
        "max_missing_per_gap",
    )

    for key in float_keys:
        value = float(merged[key])
        if not math.isfinite(value):
            raise ValueError(f"gaps.{key} debe ser un número finito.")
        merged[key] = value

    for key in integer_keys:
        value = int(merged[key])
        if value <= 0:
            raise ValueError(f"gaps.{key} debe ser mayor que cero.")
        merged[key] = value

    if merged["factor"] <= 1.0:
        raise ValueError("gaps.factor debe ser mayor que 1.")

    if not (
        0.0
        < merged["row_cluster_min_m"]
        <= merged["row_cluster_max_m"]
    ):
        raise ValueError(
            "gaps.row_cluster_min_m y gaps.row_cluster_max_m "
            "no forman un intervalo válido."
        )

    if not 0.0 < merged["candidate_min_nn_factor"] < 1.0:
        raise ValueError(
            "gaps.candidate_min_nn_factor debe estar entre 0 y 1."
        )

    if not (
        0.0
        < merged["medium_confidence_threshold"]
        < merged["high_confidence_threshold"]
        <= 1.0
    ):
        raise ValueError(
            "Los umbrales de confianza deben cumplir: "
            "0 < medio < alto <= 1."
        )

    return merged


def load_spatial_parameters(
    report_path: Path,
    orientation_override: float | None,
    within_spacing_override: float | None,
    between_spacing_override: float | None,
) -> dict[str, Any]:
    """Obtiene orientación y espaciamientos desde el informe espacial."""

    if not report_path.is_file():
        raise FileNotFoundError(
            f"No existe el informe del patrón espacial: {report_path}"
        )

    with report_path.open("r", encoding="utf-8") as file:
        report = json.load(file)

    if not isinstance(report, dict):
        raise ValueError("El informe espacial JSON no es válido.")

    metadata = report.get("metadata", {})
    orientation_data = metadata.get("orientation", {})
    spacing_data = metadata.get("spacing", {})

    orientation = (
        float(orientation_override)
        if orientation_override is not None
        else float(orientation_data.get("estimated_row_orientation_deg"))
    )

    within_spacing = (
        float(within_spacing_override)
        if within_spacing_override is not None
        else float(spacing_data.get("within_row_m"))
    )

    between_value = (
        between_spacing_override
        if between_spacing_override is not None
        else spacing_data.get("between_rows_m")
    )

    between_spacing = (
        float(between_value)
        if between_value is not None
        else None
    )

    if not math.isfinite(orientation):
        raise ValueError("La orientación de las filas no es finita.")

    orientation %= 180.0

    if not math.isfinite(within_spacing) or within_spacing <= 0.0:
        raise ValueError(
            "El espaciamiento dentro de fila debe ser mayor que cero."
        )

    if between_spacing is not None:
        if not math.isfinite(between_spacing) or between_spacing <= 0.0:
            raise ValueError(
                "El espaciamiento entre filas debe ser mayor que cero."
            )

    return {
        "orientation_deg": orientation,
        "within_spacing_m": within_spacing,
        "between_spacing_m": between_spacing,
        "orientation_source": (
            "manual_override"
            if orientation_override is not None
            else "spatial_pattern_report"
        ),
        "within_spacing_source": (
            "manual_override"
            if within_spacing_override is not None
            else "spatial_pattern_report"
        ),
        "between_spacing_source": (
            "manual_override"
            if between_spacing_override is not None
            else "spatial_pattern_report"
        ),
    }


def validate_projected_meter_crs(crs: Any) -> CRS:
    """Valida que el CRS sea proyectado y utilice metros."""

    if crs is None:
        raise ValueError("La capa no tiene CRS.")

    parsed = CRS.from_user_input(crs)

    if not parsed.is_projected:
        raise ValueError("El análisis requiere un CRS proyectado.")

    unit_names = [
        axis.unit_name.lower()
        for axis in parsed.axis_info
        if axis.unit_name
    ]

    if not unit_names or not all(
        "metre" in name or "meter" in name
        for name in unit_names
    ):
        raise ValueError("El CRS debe utilizar metros.")

    return parsed


def load_layers(
    inventory_gpkg: Path,
    boundary_gpkg: Path,
    inventory_layer: str,
    boundary_layer: str,
) -> tuple[gpd.GeoDataFrame, gpd.GeoDataFrame]:
    """Carga y valida inventario y límite."""

    if not inventory_gpkg.is_file():
        raise FileNotFoundError(
            f"No existe el inventario: {inventory_gpkg}"
        )

    if not boundary_gpkg.is_file():
        raise FileNotFoundError(
            f"No existe el límite: {boundary_gpkg}"
        )

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

    if "detection_id" not in inventory.columns:
        raise ValueError("El inventario no contiene detection_id.")

    if inventory["detection_id"].isna().any():
        raise ValueError("El inventario contiene detection_id vacíos.")

    if inventory["detection_id"].duplicated().any():
        raise ValueError("El inventario contiene detection_id repetidos.")

    if inventory.geometry.isna().any() or inventory.geometry.is_empty.any():
        raise ValueError("El inventario contiene geometrías vacías.")

    if inventory.geometry.geom_type.ne("Point").any():
        raise ValueError("El inventario debe contener únicamente puntos.")

    validate_projected_meter_crs(inventory.crs)
    validate_projected_meter_crs(boundary.crs)

    if inventory.crs != boundary.crs:
        boundary = boundary.to_crs(inventory.crs)

    boundary_geometry = boundary.geometry.union_all()

    if boundary_geometry.is_empty or not boundary_geometry.is_valid:
        raise ValueError("La geometría consolidada del límite no es válida.")

    covered_mask = inventory.geometry.apply(boundary_geometry.covers)

    if not covered_mask.all():
        inventory = inventory.loc[covered_mask].copy()

    if len(inventory) < 4:
        raise ValueError(
            "Se requieren al menos cuatro plantas dentro del límite."
        )

    return inventory.reset_index(drop=True), boundary


def rotate_coordinates(
    coordinates: np.ndarray,
    orientation_deg: float,
) -> tuple[np.ndarray, np.ndarray, tuple[float, float]]:
    """Proyecta coordenadas en ejes paralelo y perpendicular a las filas."""

    origin_x = float(np.mean(coordinates[:, 0]))
    origin_y = float(np.mean(coordinates[:, 1]))

    centered_x = coordinates[:, 0] - origin_x
    centered_y = coordinates[:, 1] - origin_y

    angle = math.radians(orientation_deg)
    cosine = math.cos(angle)
    sine = math.sin(angle)

    along = centered_x * cosine + centered_y * sine
    cross = -centered_x * sine + centered_y * cosine

    return along, cross, (origin_x, origin_y)


def inverse_rotated_coordinate(
    along: float,
    cross: float,
    orientation_deg: float,
    origin: tuple[float, float],
) -> tuple[float, float]:
    """Convierte coordenadas fila/transversal nuevamente al CRS del proyecto."""

    angle = math.radians(orientation_deg)
    cosine = math.cos(angle)
    sine = math.sin(angle)

    x_value = along * cosine - cross * sine + origin[0]
    y_value = along * sine + cross * cosine + origin[1]

    return float(x_value), float(y_value)


def build_row_components(
    along: np.ndarray,
    cross: np.ndarray,
    row_tolerance_m: float,
    max_along_link_m: float,
) -> list[np.ndarray]:
    """Agrupa plantas mediante conectividad local paralela a las filas."""

    rotated_coordinates = np.column_stack((along, cross))
    tree = cKDTree(rotated_coordinates)
    search_radius = math.hypot(max_along_link_m, row_tolerance_m)
    pairs = tree.query_pairs(r=search_radius, output_type="ndarray")

    union_find = UnionFind(len(along))

    if pairs.size:
        for first, second in pairs:
            along_difference = abs(float(along[first] - along[second]))
            cross_difference = abs(float(cross[first] - cross[second]))

            if (
                along_difference <= max_along_link_m
                and cross_difference <= row_tolerance_m
            ):
                union_find.union(int(first), int(second))

    groups: dict[int, list[int]] = {}

    for index in range(len(along)):
        groups.setdefault(union_find.find(index), []).append(index)

    return [
        np.asarray(indices, dtype=int)
        for indices in groups.values()
    ]


def robust_row_fit(
    along: np.ndarray,
    cross: np.ndarray,
    max_residual_m: float,
) -> tuple[float, float, np.ndarray, float]:
    """Ajusta una fila en ejes rotados mediante rechazo iterativo de atípicos."""

    if len(along) < 2:
        raise ValueError("No hay puntos suficientes para ajustar la fila.")

    mask = np.ones(len(along), dtype=bool)

    for _ in range(4):
        if int(mask.sum()) < 2:
            break

        slope, intercept = np.polyfit(along[mask], cross[mask], 1)
        residuals = cross - (slope * along + intercept)
        active_residuals = residuals[mask]
        median_residual = float(np.median(active_residuals))
        mad = float(
            np.median(np.abs(active_residuals - median_residual))
        )
        robust_sigma = 1.4826 * mad
        threshold = max(0.20, 2.75 * robust_sigma)
        threshold = min(max_residual_m, threshold)
        new_mask = np.abs(residuals) <= threshold

        if np.array_equal(new_mask, mask):
            break

        if int(new_mask.sum()) < 2:
            break

        mask = new_mask

    slope, intercept = np.polyfit(along[mask], cross[mask], 1)
    final_residuals = cross - (slope * along + intercept)
    median_absolute_residual = float(
        np.median(np.abs(final_residuals[mask]))
    )

    return (
        float(slope),
        float(intercept),
        mask,
        median_absolute_residual,
    )


def determine_row_spacing(
    sorted_along: np.ndarray,
    global_spacing_m: float,
    gap_factor: float,
) -> float:
    """Estima el espaciamiento típico de una fila sin incluir huecos grandes."""

    differences = np.diff(sorted_along)
    valid = differences[
        (differences >= global_spacing_m * 0.50)
        & (differences < global_spacing_m * gap_factor)
    ]

    if valid.size < 3:
        return global_spacing_m

    row_spacing = float(np.median(valid))

    return clamp(
        row_spacing,
        global_spacing_m * 0.75,
        global_spacing_m * 1.25,
    )


def confidence_class(
    score: float,
    gap_config: dict[str, Any],
) -> str:
    """Clasifica la confianza operativa de un candidato."""

    if score >= gap_config["high_confidence_threshold"]:
        return "alta"

    if score >= gap_config["medium_confidence_threshold"]:
        return "media"

    return "baja"


def calculate_candidate_confidence(
    gap_ratio: float,
    estimated_missing_count: int,
    row_residual_m: float,
    max_row_residual_m: float,
    row_plant_count: int,
    distance_boundary_m: float,
    boundary_margin_m: float,
    nearest_existing_m: float,
    expected_spacing_m: float,
    gap_config: dict[str, Any],
) -> tuple[float, dict[str, float]]:
    """Calcula una puntuación explicable para verificación de campo."""

    expected_multiple = estimated_missing_count + 1
    integer_error = abs(gap_ratio - expected_multiple)
    integer_score = clamp(
        1.0
        - integer_error
        / max(gap_config["integer_ratio_tolerance"], 1e-9),
        0.0,
        1.0,
    )

    row_fit_score = clamp(
        1.0 - row_residual_m / max(max_row_residual_m, 1e-9),
        0.0,
        1.0,
    )

    row_support_score = clamp(row_plant_count / 10.0, 0.0, 1.0)

    boundary_score = clamp(
        distance_boundary_m / max(boundary_margin_m, 1e-9),
        0.0,
        1.0,
    )

    nearest_ratio = nearest_existing_m / expected_spacing_m
    nearest_score = clamp(
        1.0 - abs(nearest_ratio - 1.0) / 0.60,
        0.0,
        1.0,
    )

    score = (
        0.35 * integer_score
        + 0.25 * row_fit_score
        + 0.15 * row_support_score
        + 0.10 * boundary_score
        + 0.15 * nearest_score
    )

    if estimated_missing_count >= 4:
        score *= 0.85

    components = {
        "integer_score": round(integer_score, 6),
        "row_fit_score": round(row_fit_score, 6),
        "row_support_score": round(row_support_score, 6),
        "boundary_score": round(boundary_score, 6),
        "nearest_score": round(nearest_score, 6),
    }

    return round(clamp(score, 0.0, 1.0), 6), components


def analyze_rows_and_gaps(
    inventory: gpd.GeoDataFrame,
    boundary: gpd.GeoDataFrame,
    orientation_deg: float,
    within_spacing_m: float,
    between_spacing_m: float | None,
    gap_config: dict[str, Any],
) -> tuple[
    gpd.GeoDataFrame,
    gpd.GeoDataFrame,
    gpd.GeoDataFrame,
    gpd.GeoDataFrame,
    dict[str, Any],
]:
    """Reconstruye filas y genera candidatos a puestos faltantes."""

    coordinates = np.column_stack(
        (inventory.geometry.x.to_numpy(), inventory.geometry.y.to_numpy())
    )

    along, cross, origin = rotate_coordinates(
        coordinates,
        orientation_deg,
    )

    reference_between_spacing = (
        between_spacing_m
        if between_spacing_m is not None
        else within_spacing_m * 1.25
    )

    row_tolerance_m = clamp(
        reference_between_spacing
        * gap_config["row_cluster_tolerance_factor"],
        gap_config["row_cluster_min_m"],
        gap_config["row_cluster_max_m"],
    )

    max_along_link_m = (
        gap_config["row_link_max_factor"] * within_spacing_m
    )

    max_row_residual_m = max(
        0.35,
        reference_between_spacing
        * gap_config["row_fit_max_residual_factor"],
    )

    boundary_margin_m = max(
        within_spacing_m,
        reference_between_spacing,
    ) * gap_config["boundary_margin_factor"]

    components = build_row_components(
        along=along,
        cross=cross,
        row_tolerance_m=row_tolerance_m,
        max_along_link_m=max_along_link_m,
    )

    min_plants_per_row = int(gap_config["min_plants_per_row"])
    components = [
        component
        for component in components
        if len(component) >= min_plants_per_row
    ]

    if not components:
        raise ValueError(
            "No se reconstruyeron filas con el número mínimo de plantas."
        )

    # Orden estable de filas según posición transversal.
    components.sort(key=lambda indices: float(np.median(cross[indices])))

    existing_tree = cKDTree(coordinates)
    boundary_geometry = boundary.geometry.union_all()

    assigned_inventory = inventory.copy()
    assigned_inventory["row_id"] = None
    assigned_inventory["row_along_m"] = np.nan
    assigned_inventory["row_cross_m"] = np.nan
    assigned_inventory["row_fit_residual_m"] = np.nan
    assigned_inventory["row_inlier"] = False

    row_records: list[dict[str, Any]] = []
    row_geometries: list[LineString] = []
    gap_records: list[dict[str, Any]] = []
    gap_geometries: list[LineString] = []
    candidate_records: list[dict[str, Any]] = []
    candidate_geometries: list[Point] = []

    gap_counter = 0
    candidate_counter = 0
    rows_rejected_after_fit = 0

    for row_number, component_indices in enumerate(components, start=1):
        row_id = f"fila_{row_number:04d}"
        component_along = along[component_indices]
        component_cross = cross[component_indices]

        try:
            slope, intercept, inlier_mask, row_residual_m = robust_row_fit(
                component_along,
                component_cross,
                max_residual_m=max_row_residual_m,
            )
        except Exception:
            rows_rejected_after_fit += 1
            continue

        inlier_indices = component_indices[inlier_mask]

        if len(inlier_indices) < min_plants_per_row:
            rows_rejected_after_fit += 1
            continue

        inlier_along = along[inlier_indices]
        order = np.argsort(inlier_along)
        sorted_indices = inlier_indices[order]
        sorted_along = along[sorted_indices]

        predicted_cross_all = slope * along[component_indices] + intercept
        residuals_all = np.abs(cross[component_indices] - predicted_cross_all)

        assigned_inventory.loc[component_indices, "row_id"] = row_id
        assigned_inventory.loc[component_indices, "row_along_m"] = np.round(
            along[component_indices], 6
        )
        assigned_inventory.loc[component_indices, "row_cross_m"] = np.round(
            cross[component_indices], 6
        )
        assigned_inventory.loc[
            component_indices,
            "row_fit_residual_m",
        ] = np.round(residuals_all, 6)
        assigned_inventory.loc[inlier_indices, "row_inlier"] = True

        row_spacing_m = determine_row_spacing(
            sorted_along=sorted_along,
            global_spacing_m=within_spacing_m,
            gap_factor=gap_config["factor"],
        )

        start_along = float(sorted_along.min())
        end_along = float(sorted_along.max())
        start_cross = slope * start_along + intercept
        end_cross = slope * end_along + intercept
        start_xy = inverse_rotated_coordinate(
            start_along,
            start_cross,
            orientation_deg,
            origin,
        )
        end_xy = inverse_rotated_coordinate(
            end_along,
            end_cross,
            orientation_deg,
            origin,
        )
        row_line = LineString([start_xy, end_xy])

        row_gap_count = 0
        row_candidate_count = 0
        row_intervals = np.diff(sorted_along)

        for interval_index, gap_distance_m in enumerate(row_intervals):
            gap_distance_m = float(gap_distance_m)

            if gap_distance_m < gap_config["factor"] * row_spacing_m:
                continue

            start_index = int(sorted_indices[interval_index])
            end_index = int(sorted_indices[interval_index + 1])
            start_point = inventory.geometry.iloc[start_index]
            end_point = inventory.geometry.iloc[end_index]
            gap_ratio = gap_distance_m / row_spacing_m
            estimated_missing_count = max(1, int(round(gap_ratio)) - 1)
            estimated_missing_count = min(
                estimated_missing_count,
                int(gap_config["max_missing_per_gap"]),
            )

            gap_counter += 1
            row_gap_count += 1
            gap_id = f"hueco_{gap_counter:06d}"
            gap_line = LineString([start_point, end_point])

            accepted_candidates = 0
            candidate_ids_for_gap: list[str] = []
            gap_confidences: list[float] = []

            for missing_index in range(1, estimated_missing_count + 1):
                fraction = missing_index / (estimated_missing_count + 1)
                candidate_x = start_point.x + fraction * (
                    end_point.x - start_point.x
                )
                candidate_y = start_point.y + fraction * (
                    end_point.y - start_point.y
                )
                candidate_point = Point(candidate_x, candidate_y)

                if not boundary_geometry.covers(candidate_point):
                    continue

                nearest_existing_m = float(
                    existing_tree.query(
                        np.asarray([candidate_x, candidate_y]),
                        k=1,
                    )[0]
                )

                minimum_allowed_nn_m = (
                    gap_config["candidate_min_nn_factor"] * row_spacing_m
                )

                if nearest_existing_m < minimum_allowed_nn_m:
                    continue

                distance_boundary_m = float(
                    candidate_point.distance(boundary_geometry.boundary)
                )

                confidence_score, score_components = (
                    calculate_candidate_confidence(
                        gap_ratio=gap_ratio,
                        estimated_missing_count=estimated_missing_count,
                        row_residual_m=row_residual_m,
                        max_row_residual_m=max_row_residual_m,
                        row_plant_count=len(inlier_indices),
                        distance_boundary_m=distance_boundary_m,
                        boundary_margin_m=boundary_margin_m,
                        nearest_existing_m=nearest_existing_m,
                        expected_spacing_m=row_spacing_m,
                        gap_config=gap_config,
                    )
                )

                candidate_counter += 1
                accepted_candidates += 1
                row_candidate_count += 1
                candidate_id = f"candidato_{candidate_counter:07d}"
                candidate_ids_for_gap.append(candidate_id)
                gap_confidences.append(confidence_score)

                candidate_records.append(
                    {
                        "candidate_id": candidate_id,
                        "gap_id": gap_id,
                        "row_id": row_id,
                        "candidate_order": missing_index,
                        "estimated_missing_total": estimated_missing_count,
                        "coord_x": round(candidate_x, 6),
                        "coord_y": round(candidate_y, 6),
                        "start_detection_id": str(
                            inventory.iloc[start_index]["detection_id"]
                        ),
                        "end_detection_id": str(
                            inventory.iloc[end_index]["detection_id"]
                        ),
                        "gap_distance_m": round(gap_distance_m, 6),
                        "expected_spacing_m": round(row_spacing_m, 6),
                        "gap_ratio": round(gap_ratio, 6),
                        "nearest_existing_m": round(nearest_existing_m, 6),
                        "distance_boundary_m": round(
                            distance_boundary_m,
                            6,
                        ),
                        "row_plant_count": int(len(inlier_indices)),
                        "row_fit_residual_m": round(row_residual_m, 6),
                        "confidence_score": confidence_score,
                        "confidence_class": confidence_class(
                            confidence_score,
                            gap_config,
                        ),
                        "integer_score": score_components["integer_score"],
                        "row_fit_score": score_components["row_fit_score"],
                        "row_support_score": score_components[
                            "row_support_score"
                        ],
                        "boundary_score": score_components["boundary_score"],
                        "nearest_score": score_components["nearest_score"],
                        "status": "candidato_verificacion_campo",
                        "management_action": (
                            "verificar_en_campo_antes_de_resiembra"
                        ),
                    }
                )
                candidate_geometries.append(candidate_point)

            gap_records.append(
                {
                    "gap_id": gap_id,
                    "row_id": row_id,
                    "start_detection_id": str(
                        inventory.iloc[start_index]["detection_id"]
                    ),
                    "end_detection_id": str(
                        inventory.iloc[end_index]["detection_id"]
                    ),
                    "gap_distance_m": round(gap_distance_m, 6),
                    "expected_spacing_m": round(row_spacing_m, 6),
                    "gap_ratio": round(gap_ratio, 6),
                    "estimated_missing_count": estimated_missing_count,
                    "accepted_candidates": accepted_candidates,
                    "candidate_ids": ",".join(candidate_ids_for_gap),
                    "mean_candidate_confidence": (
                        round(float(np.mean(gap_confidences)), 6)
                        if gap_confidences
                        else None
                    ),
                    "status": (
                        "candidatos_generados"
                        if accepted_candidates > 0
                        else "sin_candidato_por_filtros"
                    ),
                }
            )
            gap_geometries.append(gap_line)

        row_records.append(
            {
                "row_id": row_id,
                "plant_count": int(len(inlier_indices)),
                "component_plant_count": int(len(component_indices)),
                "row_length_m": round(float(row_line.length), 6),
                "orientation_base_deg": round(orientation_deg, 6),
                "fit_slope_rotated": round(slope, 8),
                "row_fit_residual_m": round(row_residual_m, 6),
                "expected_spacing_m": round(row_spacing_m, 6),
                "gaps_detected": row_gap_count,
                "candidates_generated": row_candidate_count,
                "row_status": "fila_estimada_para_revision",
            }
        )
        row_geometries.append(row_line)

    rows = gpd.GeoDataFrame(
        row_records,
        geometry=row_geometries,
        crs=inventory.crs,
    )

    gaps = gpd.GeoDataFrame(
        gap_records,
        geometry=gap_geometries,
        crs=inventory.crs,
    )

    candidates = gpd.GeoDataFrame(
        candidate_records,
        geometry=candidate_geometries,
        crs=inventory.crs,
    )

    assigned_count = int(assigned_inventory["row_id"].notna().sum())
    inlier_count = int(assigned_inventory["row_inlier"].sum())

    diagnostics = {
        "row_tolerance_m": round(row_tolerance_m, 6),
        "max_along_link_m": round(max_along_link_m, 6),
        "max_row_residual_m": round(max_row_residual_m, 6),
        "boundary_margin_m": round(boundary_margin_m, 6),
        "initial_components": int(len(components)),
        "rows_rejected_after_fit": int(rows_rejected_after_fit),
        "rows_created": int(len(rows)),
        "assigned_plants": assigned_count,
        "row_inlier_plants": inlier_count,
        "unassigned_plants": int(len(inventory) - assigned_count),
        "gaps_detected": int(len(gaps)),
        "candidates_generated": int(len(candidates)),
    }

    return assigned_inventory, rows, gaps, candidates, diagnostics


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
    """Escribe un GeoPackage mediante un archivo temporal."""

    if geodataframe.empty:
        raise ValueError(
            f"No es posible crear {layer_name}: la capa está vacía."
        )

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
    """Reabre y valida una salida GeoPackage."""

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

    if verified.geometry.isna().any() or verified.geometry.is_empty.any():
        raise RuntimeError("El GeoPackage contiene geometrías vacías.")

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
    result: MissingPlantCandidatesResult,
    report_path: Path,
) -> Path:
    """Guarda el informe JSON."""

    report_path.parent.mkdir(parents=True, exist_ok=True)
    result.report_path = str(report_path)

    with report_path.open("w", encoding="utf-8") as file:
        json.dump(
            asdict(result),
            file,
            ensure_ascii=False,
            indent=4,
        )

    return report_path


def detect_missing_plant_candidates(
    inventory_gpkg: str | Path,
    boundary_gpkg: str | Path,
    spatial_report_json: str | Path,
    inventory_layer: str = "plantas_banano_validas",
    boundary_layer: str = "limite_analisis",
    config_path: str | Path | None = None,
    orientation_deg: float | None = None,
    within_spacing_m: float | None = None,
    between_spacing_m: float | None = None,
    output_dir: str | Path | None = None,
) -> MissingPlantCandidatesResult:
    """Reconstruye filas y propone puestos faltantes para verificación."""

    started_at = datetime.now().isoformat(timespec="seconds")
    start_time = time.perf_counter()

    normalized_inventory_gpkg = Path(inventory_gpkg).expanduser().resolve(
        strict=False
    )
    normalized_boundary_gpkg = Path(boundary_gpkg).expanduser().resolve(
        strict=False
    )
    normalized_spatial_report = Path(spatial_report_json).expanduser().resolve(
        strict=False
    )
    normalized_config_path = (
        Path(config_path)
        if config_path is not None
        else DEFAULT_CONFIG_PATH
    ).expanduser().resolve(strict=False)

    result = MissingPlantCandidatesResult(
        success=False,
        started_at=started_at,
        finished_at=None,
        inventory_gpkg=str(normalized_inventory_gpkg),
        boundary_gpkg=str(normalized_boundary_gpkg),
        spatial_report_json=str(normalized_spatial_report),
        inventory_layer=inventory_layer,
        boundary_layer=boundary_layer,
        config_path=str(normalized_config_path),
        requested_orientation_deg=orientation_deg,
        requested_within_spacing_m=within_spacing_m,
        requested_between_spacing_m=between_spacing_m,
    )

    output_directory = resolve_output_directory(
        inventory_gpkg=normalized_inventory_gpkg,
        output_dir=output_dir,
    )
    result.output_directory = str(output_directory)

    assigned_points_gpkg_path = (
        output_directory / "plantas_asignadas_filas.gpkg"
    )
    rows_gpkg_path = output_directory / "filas_estimadas.gpkg"
    gaps_gpkg_path = output_directory / "huecos_detectados.gpkg"
    candidates_csv_path = (
        output_directory / "candidatos_puestos_faltantes.csv"
    )
    candidates_gpkg_path = (
        output_directory / "candidatos_puestos_faltantes.gpkg"
    )
    summary_csv_path = output_directory / "resumen_puestos_faltantes.csv"
    report_path = output_directory / "puestos_faltantes.json"

    protected_outputs = (
        assigned_points_gpkg_path,
        rows_gpkg_path,
        gaps_gpkg_path,
        candidates_csv_path,
        candidates_gpkg_path,
        summary_csv_path,
        report_path,
    )

    existing_outputs = [path for path in protected_outputs if path.exists()]

    if existing_outputs:
        result.errors.append(
            "No se sobrescribirán salidas existentes: "
            + ", ".join(str(path) for path in existing_outputs)
        )

    if result.errors:
        result.finished_at = datetime.now().isoformat(timespec="seconds")
        error_report = GLOBAL_LOGS_DIRECTORY / (
            "missing_candidates_error_"
            + datetime.now().strftime("%Y%m%d_%H%M%S")
            + ".json"
        )
        save_report(result, error_report)
        return result

    output_directory.mkdir(parents=True, exist_ok=True)
    generated_paths: list[Path] = []

    try:
        gap_config = load_gap_config(normalized_config_path)
        spatial_parameters = load_spatial_parameters(
            report_path=normalized_spatial_report,
            orientation_override=orientation_deg,
            within_spacing_override=within_spacing_m,
            between_spacing_override=between_spacing_m,
        )

        inventory, boundary = load_layers(
            inventory_gpkg=normalized_inventory_gpkg,
            boundary_gpkg=normalized_boundary_gpkg,
            inventory_layer=inventory_layer,
            boundary_layer=boundary_layer,
        )

        assigned, rows, gaps, candidates, diagnostics = (
            analyze_rows_and_gaps(
                inventory=inventory,
                boundary=boundary,
                orientation_deg=spatial_parameters["orientation_deg"],
                within_spacing_m=spatial_parameters["within_spacing_m"],
                between_spacing_m=spatial_parameters["between_spacing_m"],
                gap_config=gap_config,
            )
        )

        write_gpkg_atomic(
            assigned,
            assigned_points_gpkg_path,
            "plantas_asignadas_filas",
        )
        generated_paths.append(assigned_points_gpkg_path)

        write_gpkg_atomic(
            rows,
            rows_gpkg_path,
            "filas_estimadas",
        )
        generated_paths.append(rows_gpkg_path)

        if not gaps.empty:
            write_gpkg_atomic(
                gaps,
                gaps_gpkg_path,
                "huecos_detectados",
            )
            generated_paths.append(gaps_gpkg_path)
            result.gaps_gpkg = str(gaps_gpkg_path)

        candidates_without_geometry = pd.DataFrame(
            candidates.drop(columns="geometry")
            if "geometry" in candidates.columns
            else candidates
        )
        write_csv_atomic(candidates_without_geometry, candidates_csv_path)
        generated_paths.append(candidates_csv_path)

        if not candidates.empty:
            write_gpkg_atomic(
                candidates,
                candidates_gpkg_path,
                "candidatos_puestos_faltantes",
            )
            generated_paths.append(candidates_gpkg_path)
            result.candidates_gpkg = str(candidates_gpkg_path)

        high_count = (
            int((candidates["confidence_class"] == "alta").sum())
            if not candidates.empty
            else 0
        )
        medium_count = (
            int((candidates["confidence_class"] == "media").sum())
            if not candidates.empty
            else 0
        )
        low_count = (
            int((candidates["confidence_class"] == "baja").sum())
            if not candidates.empty
            else 0
        )

        summary_record = {
            "fecha_proceso": datetime.now().isoformat(timespec="seconds"),
            "epsg": inventory.crs.to_epsg(),
            "plantas_inventario": int(len(inventory)),
            "plantas_asignadas_filas": diagnostics["assigned_plants"],
            "plantas_no_asignadas": diagnostics["unassigned_plants"],
            "filas_estimadas": diagnostics["rows_created"],
            "huecos_detectados": diagnostics["gaps_detected"],
            "candidatos_totales": diagnostics["candidates_generated"],
            "candidatos_confianza_alta": high_count,
            "candidatos_confianza_media": medium_count,
            "candidatos_confianza_baja": low_count,
            "orientacion_fila_grados": round(
                spatial_parameters["orientation_deg"], 6
            ),
            "espaciamiento_en_fila_m": round(
                spatial_parameters["within_spacing_m"], 6
            ),
            "espaciamiento_entre_filas_m": (
                round(spatial_parameters["between_spacing_m"], 6)
                if spatial_parameters["between_spacing_m"] is not None
                else None
            ),
            "umbral_hueco_m": round(
                gap_config["factor"]
                * spatial_parameters["within_spacing_m"],
                6,
            ),
            "tolerancia_asignacion_fila_m": diagnostics[
                "row_tolerance_m"
            ],
            "estado": "candidatos_para_verificacion_de_campo",
        }

        write_csv_atomic(pd.DataFrame([summary_record]), summary_csv_path)
        generated_paths.append(summary_csv_path)

        result.assigned_points_gpkg = str(assigned_points_gpkg_path)
        result.rows_gpkg = str(rows_gpkg_path)
        result.candidates_csv = str(candidates_csv_path)
        result.summary_csv = str(summary_csv_path)

        verification: dict[str, Any] = {
            "assigned_points": verify_gpkg(
                assigned_points_gpkg_path,
                "plantas_asignadas_filas",
                len(assigned),
            ),
            "rows": verify_gpkg(
                rows_gpkg_path,
                "filas_estimadas",
                len(rows),
            ),
        }

        if not gaps.empty:
            verification["gaps"] = verify_gpkg(
                gaps_gpkg_path,
                "huecos_detectados",
                len(gaps),
            )

        if not candidates.empty:
            verification["candidates"] = verify_gpkg(
                candidates_gpkg_path,
                "candidatos_puestos_faltantes",
                len(candidates),
            )

        elapsed_seconds = round(time.perf_counter() - start_time, 3)

        result.metadata = {
            "inventory": {
                "plants": int(len(inventory)),
                "crs": inventory.crs.to_string(),
                "epsg": inventory.crs.to_epsg(),
            },
            "spatial_parameters": spatial_parameters,
            "gap_configuration": gap_config,
            "diagnostics": diagnostics,
            "candidate_counts": {
                "total": int(len(candidates)),
                "high_confidence": high_count,
                "medium_confidence": medium_count,
                "low_confidence": low_count,
            },
            "verification": verification,
            "elapsed_seconds": elapsed_seconds,
            "interpretation": {
                "status": "candidate_for_field_verification",
                "confirmed_missing_plants": False,
                "automatic_replanting_decision": False,
            },
        }

        if diagnostics["unassigned_plants"] > 0:
            result.warnings.append(
                f"{diagnostics['unassigned_plants']} plantas no pudieron "
                "asignarse a una fila estimada."
            )

        if candidates.empty:
            result.warnings.append(
                "No se generaron candidatos con los parámetros actuales."
            )
        else:
            result.warnings.append(
                "Los puntos generados son candidatos para verificación "
                "de campo; no son faltantes confirmados."
            )

        if low_count > 0:
            result.warnings.append(
                f"Existen {low_count} candidatos de confianza baja que "
                "deben revisarse con prioridad antes de usarlos."
            )

        result.success = True

    except Exception as error:
        result.errors.append(
            "No fue posible detectar puestos faltantes: "
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


def print_missing_candidates_summary(
    result: MissingPlantCandidatesResult,
) -> None:
    """Muestra el resumen en la terminal."""

    print("=" * 72)
    print("DETECCIÓN DE CANDIDATOS A PUESTOS FALTANTES")
    print("=" * 72)
    print(f"Inventario: {result.inventory_gpkg}")
    print(f"Informe espacial: {result.spatial_report_json}")
    print(
        "Estado: "
        f"{'COMPLETADO' if result.success else 'ERROR'}"
    )

    if result.metadata:
        diagnostics = result.metadata["diagnostics"]
        parameters = result.metadata["spatial_parameters"]
        counts = result.metadata["candidate_counts"]

        print(f"Plantas: {result.metadata['inventory']['plants']}")
        print(f"Filas estimadas: {diagnostics['rows_created']}")
        print(f"Huecos detectados: {diagnostics['gaps_detected']}")
        print(f"Candidatos totales: {counts['total']}")
        print(f"  Confianza alta: {counts['high_confidence']}")
        print(f"  Confianza media: {counts['medium_confidence']}")
        print(f"  Confianza baja: {counts['low_confidence']}")
        print(
            "Orientación: "
            f"{parameters['orientation_deg']}°"
        )
        print(
            "Espaciamiento dentro de fila: "
            f"{parameters['within_spacing_m']} m"
        )
        print(
            "Tiempo: "
            f"{result.metadata['elapsed_seconds']} segundos"
        )

    if result.rows_gpkg:
        print(f"Filas: {result.rows_gpkg}")

    if result.gaps_gpkg:
        print(f"Huecos: {result.gaps_gpkg}")

    if result.candidates_csv:
        print(f"CSV de candidatos: {result.candidates_csv}")

    if result.candidates_gpkg:
        print(f"Capa de candidatos: {result.candidates_gpkg}")

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


def run_missing_plant_candidates(
    inventory_gpkg: str | Path,
    boundary_gpkg: str | Path,
    spatial_report_json: str | Path,
    inventory_layer: str = "plantas_banano_validas",
    boundary_layer: str = "limite_analisis",
    config_path: str | Path | None = None,
    orientation_deg: float | None = None,
    within_spacing_m: float | None = None,
    between_spacing_m: float | None = None,
    output_dir: str | Path | None = None,
) -> int:
    """Ejecuta el análisis desde main.py."""

    result = detect_missing_plant_candidates(
        inventory_gpkg=inventory_gpkg,
        boundary_gpkg=boundary_gpkg,
        spatial_report_json=spatial_report_json,
        inventory_layer=inventory_layer,
        boundary_layer=boundary_layer,
        config_path=config_path,
        orientation_deg=orientation_deg,
        within_spacing_m=within_spacing_m,
        between_spacing_m=between_spacing_m,
        output_dir=output_dir,
    )

    print_missing_candidates_summary(result)

    return 0 if result.success else 1
