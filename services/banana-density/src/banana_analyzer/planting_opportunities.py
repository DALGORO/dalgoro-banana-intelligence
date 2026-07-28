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
import rasterio
import yaml
from pyproj import CRS
from rasterio.features import shapes
from scipy.spatial import cKDTree
from shapely import contains_xy, get_parts, voronoi_polygons
from shapely.geometry import MultiPoint, Point, shape


PROJECT_ROOT = Path(__file__).resolve().parents[2]
GLOBAL_LOGS_DIRECTORY = PROJECT_ROOT / "logs"
DEFAULT_CONFIG_PATH = PROJECT_ROOT / "config" / "spatial_analysis.yaml"


@dataclass
class PlantingOpportunitiesResult:
    """Resultado del análisis geométrico de espacios potencialmente sembrables."""

    success: bool
    started_at: str
    finished_at: str | None
    inventory_gpkg: str
    boundary_gpkg: str
    inventory_layer: str
    boundary_layer: str
    target_density_plants_ha: float
    config_path: str
    exclusions_gpkg: str | None
    exclusions_layer: str | None
    output_directory: str | None = None
    voronoi_gpkg: str | None = None
    opportunity_zones_gpkg: str | None = None
    candidates_csv: str | None = None
    candidates_gpkg: str | None = None
    summary_csv: str | None = None
    report_path: str | None = None
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


def clamp(value: float, minimum: float, maximum: float) -> float:
    """Limita un valor al intervalo indicado."""

    return max(minimum, min(maximum, value))


def resolve_output_directory(
    inventory_gpkg: Path,
    target_density: float,
    output_dir: str | Path | None,
) -> Path:
    """Determina una carpeta independiente para el escenario de densidad."""

    if output_dir is not None:
        return Path(output_dir).expanduser().resolve(strict=False)

    density_label = str(int(round(target_density)))
    return inventory_gpkg.parent / f"oportunidades_siembra_{density_label}"


def load_opportunity_config(config_path: Path) -> dict[str, Any]:
    """Carga y valida la sección planting_opportunities del YAML."""

    if not config_path.is_file():
        raise FileNotFoundError(
            f"No existe el archivo de configuración: {config_path}"
        )

    with config_path.open("r", encoding="utf-8") as file:
        config = yaml.safe_load(file)

    if not isinstance(config, dict):
        raise ValueError("La configuración YAML no contiene un diccionario.")

    section = config.get("planting_opportunities", {})

    if not isinstance(section, dict):
        raise ValueError(
            "La sección planting_opportunities debe ser un diccionario."
        )

    defaults: dict[str, Any] = {
        "grid_cell_size_m": 0.35,
        "minimum_clearance_factor": 0.75,
        "candidate_spacing_factor": 0.85,
        "local_density_radius_factor": 2.50,
        "minimum_polygon_area_factor": 0.20,
        "boundary_risk_distance_factor": 0.50,
        "max_candidates": 10000,
        "high_spatial_score": 0.80,
        "medium_spatial_score": 0.60,
        "voronoi_high_concentration_ratio": 0.65,
        "voronoi_expected_upper_ratio": 1.35,
        "voronoi_open_ratio": 1.75,
        "voronoi_severe_open_ratio": 2.50,
    }

    merged = {**defaults, **section}

    float_keys = (
        "grid_cell_size_m",
        "minimum_clearance_factor",
        "candidate_spacing_factor",
        "local_density_radius_factor",
        "minimum_polygon_area_factor",
        "boundary_risk_distance_factor",
        "high_spatial_score",
        "medium_spatial_score",
        "voronoi_high_concentration_ratio",
        "voronoi_expected_upper_ratio",
        "voronoi_open_ratio",
        "voronoi_severe_open_ratio",
    )

    for key in float_keys:
        value = float(merged[key])
        if not math.isfinite(value) or value <= 0:
            raise ValueError(
                f"planting_opportunities.{key} debe ser positivo y finito."
            )
        merged[key] = value

    merged["max_candidates"] = int(merged["max_candidates"])
    if merged["max_candidates"] <= 0:
        raise ValueError(
            "planting_opportunities.max_candidates debe ser mayor que cero."
        )

    if not (
        0.0
        < merged["medium_spatial_score"]
        < merged["high_spatial_score"]
        <= 1.0
    ):
        raise ValueError(
            "Los umbrales de puntuación deben cumplir 0 < medio < alto <= 1."
        )

    voronoi_limits = [
        merged["voronoi_high_concentration_ratio"],
        merged["voronoi_expected_upper_ratio"],
        merged["voronoi_open_ratio"],
        merged["voronoi_severe_open_ratio"],
    ]

    if voronoi_limits != sorted(voronoi_limits):
        raise ValueError(
            "Los umbrales Voronoi deben estar ordenados de menor a mayor."
        )

    return merged


def validate_projected_metric_crs(crs_value: Any) -> CRS:
    """Comprueba que el CRS sea proyectado y utilice metros."""

    crs = CRS.from_user_input(crs_value)

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

    return crs


def read_inputs(
    inventory_path: Path,
    boundary_path: Path,
    inventory_layer: str,
    boundary_layer: str,
) -> tuple[gpd.GeoDataFrame, gpd.GeoDataFrame]:
    """Lee y valida el inventario y el límite."""

    inventory = gpd.read_file(
        inventory_path,
        layer=inventory_layer,
        engine="pyogrio",
    )

    boundary = gpd.read_file(
        boundary_path,
        layer=boundary_layer,
        engine="pyogrio",
    )

    if inventory.empty:
        raise ValueError("El inventario de plantas está vacío.")

    if boundary.empty:
        raise ValueError("La capa de límite está vacía.")

    if inventory.crs is None or boundary.crs is None:
        raise ValueError("El inventario y el límite deben tener CRS.")

    validate_projected_metric_crs(inventory.crs)

    if inventory.crs != boundary.crs:
        boundary = boundary.to_crs(inventory.crs)

    if inventory.geometry.geom_type.ne("Point").any():
        raise ValueError("El inventario debe contener únicamente puntos.")

    if inventory.geometry.is_empty.any() or inventory.geometry.isna().any():
        raise ValueError("El inventario contiene geometrías vacías.")

    if "detection_id" not in inventory.columns:
        inventory = inventory.copy()
        inventory["detection_id"] = [
            f"plant_{index + 1:08d}"
            for index in range(len(inventory))
        ]

    return inventory, boundary


def build_plantable_area(
    boundary: gpd.GeoDataFrame,
    exclusions_gpkg: Path | None,
    exclusions_layer: str | None,
) -> tuple[Any, int, float]:
    """Construye el área analizable y descuenta exclusiones opcionales."""

    plantable_area = boundary.geometry.union_all()

    if plantable_area.is_empty:
        raise ValueError("La geometría del límite está vacía.")

    original_area = float(plantable_area.area)
    exclusions_count = 0

    if exclusions_gpkg is not None:
        if not exclusions_gpkg.is_file():
            raise FileNotFoundError(
                f"No existe el GeoPackage de exclusiones: {exclusions_gpkg}"
            )

        if not exclusions_layer:
            raise ValueError(
                "Debe indicar --exclusions-layer cuando use exclusiones."
            )

        exclusions = gpd.read_file(
            exclusions_gpkg,
            layer=exclusions_layer,
            engine="pyogrio",
        )

        if exclusions.crs is None:
            raise ValueError("La capa de exclusiones no tiene CRS.")

        if exclusions.crs != boundary.crs:
            exclusions = exclusions.to_crs(boundary.crs)

        exclusions = exclusions.loc[
            exclusions.geometry.notna() & ~exclusions.geometry.is_empty
        ].copy()

        exclusions_count = int(len(exclusions))

        if not exclusions.empty:
            exclusion_geometry = exclusions.geometry.union_all()
            plantable_area = plantable_area.difference(exclusion_geometry)

    if plantable_area.is_empty or plantable_area.area <= 0:
        raise ValueError("El área plantable resultante está vacía.")

    excluded_area = original_area - float(plantable_area.area)

    return plantable_area, exclusions_count, excluded_area


def filter_inventory_to_area(
    inventory: gpd.GeoDataFrame,
    plantable_area: Any,
) -> tuple[gpd.GeoDataFrame, int]:
    """Mantiene plantas cubiertas por el área plantable."""

    mask = inventory.geometry.apply(plantable_area.covers)
    inside = inventory.loc[mask].copy().reset_index(drop=True)
    removed_count = int((~mask).sum())

    if len(inside) < 3:
        raise ValueError(
            "Se requieren al menos tres plantas dentro del área analizable."
        )

    return inside, removed_count


def calculate_target_parameters(
    target_density: float,
) -> dict[str, float]:
    """Calcula área objetivo y separación equivalente triangular."""

    if not math.isfinite(target_density) or target_density <= 0:
        raise ValueError("La densidad objetivo debe ser positiva y finita.")

    target_area_m2 = 10000.0 / target_density
    equivalent_radius_m = math.sqrt(target_area_m2 / math.pi)
    target_spacing_m = math.sqrt(
        2.0 * target_area_m2 / math.sqrt(3.0)
    )

    return {
        "target_density_plants_ha": float(target_density),
        "target_area_per_plant_m2": target_area_m2,
        "equivalent_radius_m": equivalent_radius_m,
        "target_spacing_m": target_spacing_m,
    }


def classify_voronoi_ratio(
    ratio: float,
    config: dict[str, Any],
) -> str:
    """Clasifica el territorio disponible alrededor de cada planta."""

    if ratio < config["voronoi_high_concentration_ratio"]:
        return "alta_concentracion"

    if ratio <= config["voronoi_expected_upper_ratio"]:
        return "ocupacion_esperada"

    if ratio <= config["voronoi_open_ratio"]:
        return "espacio_amplio"

    if ratio <= config["voronoi_severe_open_ratio"]:
        return "posible_vacio"

    return "vacio_severo"


def build_voronoi_layer(
    inventory: gpd.GeoDataFrame,
    plantable_area: Any,
    target: dict[str, float],
    config: dict[str, Any],
) -> gpd.GeoDataFrame:
    """Construye territorios Voronoi recortados por el área plantable."""

    source_points = inventory.geometry.tolist()
    multipoint = MultiPoint(source_points)

    try:
        voronoi_geometry = voronoi_polygons(
            multipoint,
            extend_to=plantable_area.envelope,
            ordered=True,
        )
        cells = list(get_parts(voronoi_geometry))
    except TypeError:
        voronoi_geometry = voronoi_polygons(
            multipoint,
            extend_to=plantable_area.envelope,
        )
        cells = list(get_parts(voronoi_geometry))

    records: list[dict[str, Any]] = []

    if len(cells) == len(inventory):
        assignments = list(enumerate(cells))
    else:
        cell_gdf = gpd.GeoDataFrame(
            {"cell_index": range(len(cells))},
            geometry=cells,
            crs=inventory.crs,
        )

        joined = gpd.sjoin(
            inventory[["detection_id", "geometry"]],
            cell_gdf,
            how="left",
            predicate="within",
        )

        assignments = []
        for plant_index, row in joined.iterrows():
            cell_index = row.get("cell_index")
            if pd.isna(cell_index):
                continue
            assignments.append((int(plant_index), cells[int(cell_index)]))

    for plant_index, cell in assignments:
        clipped = cell.intersection(plantable_area)

        if clipped.is_empty or clipped.area <= 0:
            continue

        plant_row = inventory.iloc[int(plant_index)]
        area_m2 = float(clipped.area)
        ratio = area_m2 / target["target_area_per_plant_m2"]
        distance_boundary = float(
            plantable_area.boundary.distance(plant_row.geometry)
        )

        records.append(
            {
                "detection_id": str(plant_row["detection_id"]),
                "voronoi_area_m2": round(area_m2, 6),
                "target_area_m2": round(
                    target["target_area_per_plant_m2"], 6
                ),
                "area_ratio_target": round(ratio, 6),
                "occupancy_class": classify_voronoi_ratio(ratio, config),
                "distance_boundary_m": round(distance_boundary, 6),
                "is_boundary_cell": bool(
                    distance_boundary
                    < config["boundary_risk_distance_factor"]
                    * target["target_spacing_m"]
                ),
                "geometry": clipped,
            }
        )

    if not records:
        raise RuntimeError("No fue posible construir los territorios Voronoi.")

    return gpd.GeoDataFrame(records, geometry="geometry", crs=inventory.crs)


def create_clearance_grid(
    inventory: gpd.GeoDataFrame,
    plantable_area: Any,
    target: dict[str, float],
    config: dict[str, Any],
) -> dict[str, Any]:
    """Genera una cuadrícula y calcula distancia a la planta más cercana."""

    cell_size = config["grid_cell_size_m"]
    min_x, min_y, max_x, max_y = plantable_area.bounds

    width = int(math.ceil((max_x - min_x) / cell_size))
    height = int(math.ceil((max_y - min_y) / cell_size))

    if width <= 0 or height <= 0:
        raise ValueError("La extensión del área plantable es inválida.")

    columns = np.arange(width, dtype=float)
    rows = np.arange(height, dtype=float)

    x_values = min_x + (columns + 0.5) * cell_size
    y_values = max_y - (rows + 0.5) * cell_size

    xx, yy = np.meshgrid(x_values, y_values)
    flat_x = xx.ravel()
    flat_y = yy.ravel()

    inside_flat = contains_xy(plantable_area, flat_x, flat_y)
    inside_coordinates = np.column_stack(
        (flat_x[inside_flat], flat_y[inside_flat])
    )

    plant_coordinates = np.column_stack(
        (inventory.geometry.x.to_numpy(), inventory.geometry.y.to_numpy())
    )

    tree = cKDTree(plant_coordinates)
    distances, nearest_indices = tree.query(inside_coordinates, k=1)

    minimum_clearance = (
        config["minimum_clearance_factor"] * target["target_spacing_m"]
    )

    open_inside = distances >= minimum_clearance
    open_coordinates = inside_coordinates[open_inside]
    open_distances = distances[open_inside]
    open_nearest_indices = nearest_indices[open_inside]

    open_mask_flat = np.zeros(flat_x.shape[0], dtype=np.uint8)
    inside_indices = np.flatnonzero(inside_flat)
    open_mask_flat[inside_indices[open_inside]] = 1
    open_mask = open_mask_flat.reshape(height, width)

    transform = rasterio.Affine(
        cell_size,
        0.0,
        min_x,
        0.0,
        -cell_size,
        max_y,
    )

    return {
        "cell_size_m": cell_size,
        "width": width,
        "height": height,
        "transform": transform,
        "open_mask": open_mask,
        "open_coordinates": open_coordinates,
        "open_distances": open_distances,
        "open_nearest_indices": open_nearest_indices,
        "minimum_clearance_m": minimum_clearance,
        "plant_tree": tree,
        "plant_coordinates": plant_coordinates,
    }


def polygonize_open_zones(
    grid: dict[str, Any],
    plantable_area: Any,
    target: dict[str, float],
    crs: Any,
    config: dict[str, Any],
) -> gpd.GeoDataFrame:
    """Convierte la máscara de espacio libre en polígonos de oportunidad."""

    minimum_area = (
        config["minimum_polygon_area_factor"]
        * target["target_area_per_plant_m2"]
    )

    records: list[dict[str, Any]] = []

    for geometry_mapping, value in shapes(
        grid["open_mask"],
        mask=grid["open_mask"].astype(bool),
        transform=grid["transform"],
    ):
        if int(value) != 1:
            continue

        polygon = shape(geometry_mapping).intersection(plantable_area)

        if polygon.is_empty or polygon.area < minimum_area:
            continue

        distance_boundary = float(
            plantable_area.boundary.distance(polygon.representative_point())
        )

        records.append(
            {
                "opportunity_id": f"opp_{len(records) + 1:06d}",
                "open_core_area_m2": round(float(polygon.area), 6),
                "minimum_area_m2": round(minimum_area, 6),
                "distance_boundary_m": round(distance_boundary, 6),
                "boundary_risk": bool(
                    distance_boundary
                    < config["boundary_risk_distance_factor"]
                    * target["target_spacing_m"]
                ),
                "land_use_status": "pendiente_revision_tecnica",
                "geometry": polygon,
            }
        )

    if not records:
        return gpd.GeoDataFrame(
            columns=[
                "opportunity_id",
                "open_core_area_m2",
                "minimum_area_m2",
                "distance_boundary_m",
                "boundary_risk",
                "land_use_status",
                "geometry",
            ],
            geometry="geometry",
            crs=crs,
        )

    return gpd.GeoDataFrame(records, geometry="geometry", crs=crs)


def select_candidate_points(
    grid: dict[str, Any],
    inventory: gpd.GeoDataFrame,
    plantable_area: Any,
    target: dict[str, float],
    config: dict[str, Any],
) -> gpd.GeoDataFrame:
    """Selecciona máximos espaciales separados para representar posibles sitios."""

    coordinates = grid["open_coordinates"]
    distances = grid["open_distances"]

    if len(coordinates) == 0:
        return gpd.GeoDataFrame(
            columns=["candidate_id", "geometry"],
            geometry="geometry",
            crs=inventory.crs,
        )

    selection_order = np.argsort(-distances, kind="stable")
    candidate_spacing = (
        config["candidate_spacing_factor"] * target["target_spacing_m"]
    )
    candidate_spacing_squared = candidate_spacing**2

    selected_coordinates: list[np.ndarray] = []
    selected_distances: list[float] = []

    for source_index in selection_order:
        coordinate = coordinates[int(source_index)]

        if selected_coordinates:
            selected_array = np.asarray(selected_coordinates)
            deltas = selected_array - coordinate
            squared = np.einsum("ij,ij->i", deltas, deltas)

            if float(squared.min()) < candidate_spacing_squared:
                continue

        selected_coordinates.append(coordinate)
        selected_distances.append(float(distances[int(source_index)]))

        if len(selected_coordinates) >= config["max_candidates"]:
            break

    local_radius = (
        config["local_density_radius_factor"] * target["target_spacing_m"]
    )

    records: list[dict[str, Any]] = []

    for candidate_number, (coordinate, nearest_distance) in enumerate(
        zip(selected_coordinates, selected_distances, strict=True),
        start=1,
    ):
        point = Point(float(coordinate[0]), float(coordinate[1]))
        distance_boundary = float(plantable_area.boundary.distance(point))

        local_geometry = point.buffer(local_radius).intersection(plantable_area)
        local_area = float(local_geometry.area)
        expected_count = local_area / target["target_area_per_plant_m2"]
        observed_count = len(
            grid["plant_tree"].query_ball_point(
                [point.x, point.y],
                r=local_radius,
            )
        )

        local_density_ratio = (
            observed_count / expected_count
            if expected_count > 0
            else 0.0
        )

        clearance_ratio = nearest_distance / target["target_spacing_m"]

        clearance_score = clamp(
            (
                clearance_ratio - config["minimum_clearance_factor"]
            )
            / max(1.20 - config["minimum_clearance_factor"], 0.01),
            0.0,
            1.0,
        )

        deficit_score = clamp(1.0 - local_density_ratio, 0.0, 1.0)

        boundary_score = clamp(
            distance_boundary
            / max(
                config["boundary_risk_distance_factor"]
                * target["target_spacing_m"],
                0.01,
            ),
            0.0,
            1.0,
        )

        spatial_score = clamp(
            0.45 * clearance_score
            + 0.40 * deficit_score
            + 0.15 * boundary_score,
            0.0,
            1.0,
        )

        if spatial_score >= config["high_spatial_score"]:
            score_class = "alta"
        elif spatial_score >= config["medium_spatial_score"]:
            score_class = "media"
        else:
            score_class = "baja"

        records.append(
            {
                "candidate_id": f"cand_{candidate_number:07d}",
                "coord_x": round(point.x, 6),
                "coord_y": round(point.y, 6),
                "target_density_ha": round(
                    target["target_density_plants_ha"], 4
                ),
                "target_area_m2": round(
                    target["target_area_per_plant_m2"], 6
                ),
                "target_spacing_m": round(target["target_spacing_m"], 6),
                "nearest_existing_m": round(nearest_distance, 6),
                "clearance_ratio": round(clearance_ratio, 6),
                "local_radius_m": round(local_radius, 6),
                "local_area_m2": round(local_area, 6),
                "local_existing_count": int(observed_count),
                "local_expected_count": round(expected_count, 6),
                "local_density_ratio": round(local_density_ratio, 6),
                "distance_boundary_m": round(distance_boundary, 6),
                "boundary_risk": bool(
                    distance_boundary
                    < config["boundary_risk_distance_factor"]
                    * target["target_spacing_m"]
                ),
                "spatial_score": round(spatial_score, 6),
                "spatial_score_class": score_class,
                "technical_status": "candidato_no_confirmado",
                "land_use_status": "pendiente_revision_tecnica",
                "management_action": (
                    "verificar si corresponde a resiembra, via, canal, "
                    "infraestructura u otro uso no cultivable"
                ),
                "geometry": point,
            }
        )

    return gpd.GeoDataFrame(records, geometry="geometry", crs=inventory.crs)


def assign_candidates_to_opportunities(
    candidates: gpd.GeoDataFrame,
    opportunities: gpd.GeoDataFrame,
) -> tuple[gpd.GeoDataFrame, gpd.GeoDataFrame]:
    """Relaciona candidatos con polígonos y agrega conteos por zona."""

    if candidates.empty or opportunities.empty:
        if not opportunities.empty:
            opportunities = opportunities.copy()
            opportunities["candidate_count"] = 0
        return candidates, opportunities

    joined = gpd.sjoin(
        candidates,
        opportunities[["opportunity_id", "geometry"]],
        how="left",
        predicate="within",
    ).drop(columns=["index_right"], errors="ignore")

    counts = (
        joined["opportunity_id"]
        .value_counts(dropna=True)
        .astype(int)
        .to_dict()
    )

    opportunities = opportunities.copy()
    opportunities["candidate_count"] = (
        opportunities["opportunity_id"].map(counts).fillna(0).astype(int)
    )

    return joined, opportunities


def write_csv_atomic(table: pd.DataFrame, output_path: Path) -> None:
    """Escribe un CSV mediante un archivo temporal."""

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
    """Verifica que la salida pueda abrirse nuevamente."""

    layers = pyogrio.list_layers(gpkg_path)
    verified = gpd.read_file(
        gpkg_path,
        layer=layer_name,
        engine="pyogrio",
    )

    if len(verified) != expected_rows:
        raise RuntimeError(
            "El número de elementos verificados no coincide con la salida."
        )

    if verified.crs is None:
        raise RuntimeError("El GeoPackage generado no tiene CRS.")

    return {
        "layers": layers.tolist(),
        "rows": int(len(verified)),
        "crs": verified.crs.to_string(),
        "geometry_types": sorted(
            verified.geometry.geom_type.unique().tolist()
        ),
    }


def save_report(
    result: PlantingOpportunitiesResult,
    output_path: Path,
) -> Path:
    """Guarda el informe JSON."""

    result.report_path = str(output_path)

    with output_path.open("w", encoding="utf-8") as file:
        json.dump(
            asdict(result),
            file,
            ensure_ascii=False,
            indent=4,
        )

    return output_path


def detect_planting_opportunities(
    inventory_gpkg: str | Path,
    boundary_gpkg: str | Path,
    target_density_plants_ha: float,
    inventory_layer: str = "plantas_banano_validas",
    boundary_layer: str = "limite_analisis",
    config_path: str | Path | None = None,
    exclusions_gpkg: str | Path | None = None,
    exclusions_layer: str | None = None,
    output_dir: str | Path | None = None,
) -> PlantingOpportunitiesResult:
    """Detecta espacios geométricos que podrían admitir plantas adicionales."""

    started_at = datetime.now().isoformat(timespec="seconds")
    start_time = time.perf_counter()

    inventory_path = Path(inventory_gpkg).expanduser().resolve(strict=False)
    boundary_path = Path(boundary_gpkg).expanduser().resolve(strict=False)
    normalized_config_path = (
        Path(config_path).expanduser().resolve(strict=False)
        if config_path is not None
        else DEFAULT_CONFIG_PATH.resolve(strict=False)
    )
    normalized_exclusions = (
        Path(exclusions_gpkg).expanduser().resolve(strict=False)
        if exclusions_gpkg is not None
        else None
    )

    result = PlantingOpportunitiesResult(
        success=False,
        started_at=started_at,
        finished_at=None,
        inventory_gpkg=str(inventory_path),
        boundary_gpkg=str(boundary_path),
        inventory_layer=inventory_layer,
        boundary_layer=boundary_layer,
        target_density_plants_ha=float(target_density_plants_ha),
        config_path=str(normalized_config_path),
        exclusions_gpkg=(
            str(normalized_exclusions)
            if normalized_exclusions is not None
            else None
        ),
        exclusions_layer=exclusions_layer,
    )

    output_directory = resolve_output_directory(
        inventory_gpkg=inventory_path,
        target_density=target_density_plants_ha,
        output_dir=output_dir,
    )
    result.output_directory = str(output_directory)

    voronoi_path = output_directory / "territorios_ocupacion_voronoi.gpkg"
    opportunities_path = output_directory / "zonas_oportunidad_siembra.gpkg"
    candidates_csv_path = output_directory / "candidatos_siembra.csv"
    candidates_gpkg_path = output_directory / "candidatos_siembra.gpkg"
    summary_csv_path = output_directory / "resumen_oportunidades_siembra.csv"
    report_path = output_directory / "oportunidades_siembra.json"

    if not inventory_path.is_file():
        result.errors.append("El inventario GeoPackage no existe.")

    if not boundary_path.is_file():
        result.errors.append("El GeoPackage del límite no existe.")

    if not normalized_config_path.is_file():
        result.errors.append("El archivo YAML de configuración no existe.")

    if not math.isfinite(target_density_plants_ha) or target_density_plants_ha <= 0:
        result.errors.append("La densidad objetivo debe ser mayor que cero.")

    existing_outputs = [
        path
        for path in (
            voronoi_path,
            opportunities_path,
            candidates_csv_path,
            candidates_gpkg_path,
            summary_csv_path,
            report_path,
        )
        if path.exists()
    ]

    if existing_outputs:
        result.errors.append(
            "No se sobrescribirán salidas existentes: "
            + ", ".join(str(path) for path in existing_outputs)
        )

    if result.errors:
        result.finished_at = datetime.now().isoformat(timespec="seconds")
        GLOBAL_LOGS_DIRECTORY.mkdir(parents=True, exist_ok=True)
        error_report = GLOBAL_LOGS_DIRECTORY / (
            "planting_opportunities_error_"
            + datetime.now().strftime("%Y%m%d_%H%M%S")
            + ".json"
        )
        save_report(result, error_report)
        return result

    output_directory.mkdir(parents=True, exist_ok=True)
    generated_paths: list[Path] = []

    try:
        config = load_opportunity_config(normalized_config_path)
        target = calculate_target_parameters(target_density_plants_ha)

        inventory, boundary = read_inputs(
            inventory_path=inventory_path,
            boundary_path=boundary_path,
            inventory_layer=inventory_layer,
            boundary_layer=boundary_layer,
        )

        plantable_area, exclusion_count, excluded_area = build_plantable_area(
            boundary=boundary,
            exclusions_gpkg=normalized_exclusions,
            exclusions_layer=exclusions_layer,
        )

        inventory, plants_outside = filter_inventory_to_area(
            inventory=inventory,
            plantable_area=plantable_area,
        )

        voronoi = build_voronoi_layer(
            inventory=inventory,
            plantable_area=plantable_area,
            target=target,
            config=config,
        )

        grid = create_clearance_grid(
            inventory=inventory,
            plantable_area=plantable_area,
            target=target,
            config=config,
        )

        opportunities = polygonize_open_zones(
            grid=grid,
            plantable_area=plantable_area,
            target=target,
            crs=inventory.crs,
            config=config,
        )

        candidates = select_candidate_points(
            grid=grid,
            inventory=inventory,
            plantable_area=plantable_area,
            target=target,
            config=config,
        )

        candidates, opportunities = assign_candidates_to_opportunities(
            candidates=candidates,
            opportunities=opportunities,
        )

        write_gpkg_atomic(
            geodataframe=voronoi,
            output_path=voronoi_path,
            layer_name="territorios_ocupacion",
        )
        generated_paths.append(voronoi_path)
        result.voronoi_gpkg = str(voronoi_path)

        if not opportunities.empty:
            write_gpkg_atomic(
                geodataframe=opportunities,
                output_path=opportunities_path,
                layer_name="zonas_oportunidad_siembra",
            )
            generated_paths.append(opportunities_path)
            result.opportunity_zones_gpkg = str(opportunities_path)

        candidates_without_geometry = pd.DataFrame(
            candidates.drop(columns="geometry", errors="ignore")
        )
        write_csv_atomic(candidates_without_geometry, candidates_csv_path)
        generated_paths.append(candidates_csv_path)
        result.candidates_csv = str(candidates_csv_path)

        if not candidates.empty:
            write_gpkg_atomic(
                geodataframe=candidates,
                output_path=candidates_gpkg_path,
                layer_name="candidatos_siembra",
            )
            generated_paths.append(candidates_gpkg_path)
            result.candidates_gpkg = str(candidates_gpkg_path)

        plantable_area_m2 = float(plantable_area.area)
        plantable_area_ha = plantable_area_m2 / 10000.0
        current_density = len(inventory) / plantable_area_ha
        theoretical_target_count = plantable_area_m2 / target["target_area_per_plant_m2"]
        global_difference = theoretical_target_count - len(inventory)

        class_counts = (
            candidates["spatial_score_class"].value_counts().to_dict()
            if not candidates.empty
            else {}
        )

        voronoi_counts = voronoi["occupancy_class"].value_counts().to_dict()

        summary_record = {
            "fecha_proceso": datetime.now().isoformat(timespec="seconds"),
            "target_density_plants_ha": round(target_density_plants_ha, 4),
            "target_area_per_plant_m2": round(
                target["target_area_per_plant_m2"], 6
            ),
            "target_spacing_equivalent_m": round(
                target["target_spacing_m"], 6
            ),
            "plantable_area_m2": round(plantable_area_m2, 4),
            "plantable_area_ha": round(plantable_area_ha, 6),
            "existing_plants": int(len(inventory)),
            "current_density_plants_ha": round(current_density, 4),
            "theoretical_target_plants": round(theoretical_target_count, 2),
            "global_target_difference": round(global_difference, 2),
            "opportunity_polygons": int(len(opportunities)),
            "candidate_positions": int(len(candidates)),
            "candidates_high": int(class_counts.get("alta", 0)),
            "candidates_medium": int(class_counts.get("media", 0)),
            "candidates_low": int(class_counts.get("baja", 0)),
            "exclusion_features": exclusion_count,
            "excluded_area_m2": round(excluded_area, 4),
            "technical_status": "candidatos_no_confirmados",
        }

        write_csv_atomic(pd.DataFrame([summary_record]), summary_csv_path)
        generated_paths.append(summary_csv_path)
        result.summary_csv = str(summary_csv_path)

        verifications: dict[str, Any] = {
            "voronoi": verify_gpkg(
                voronoi_path,
                "territorios_ocupacion",
                len(voronoi),
            )
        }

        if not opportunities.empty:
            verifications["opportunity_zones"] = verify_gpkg(
                opportunities_path,
                "zonas_oportunidad_siembra",
                len(opportunities),
            )

        if not candidates.empty:
            verifications["candidates"] = verify_gpkg(
                candidates_gpkg_path,
                "candidatos_siembra",
                len(candidates),
            )

        elapsed_seconds = round(time.perf_counter() - start_time, 3)

        result.metadata = {
            "target": {
                key: round(value, 6)
                for key, value in target.items()
            },
            "area": {
                "plantable_m2": round(plantable_area_m2, 4),
                "plantable_ha": round(plantable_area_ha, 6),
                "excluded_m2": round(excluded_area, 4),
            },
            "inventory": {
                "plants_used": int(len(inventory)),
                "plants_outside_plantable_area": plants_outside,
                "current_density_plants_ha": round(current_density, 4),
            },
            "global_scenario": {
                "theoretical_target_plants": round(theoretical_target_count, 2),
                "difference_target_minus_existing": round(global_difference, 2),
                "candidate_positions_detected": int(len(candidates)),
                "note": (
                    "La diferencia global y los candidatos no equivalen a una "
                    "recomendación automática de resiembra."
                ),
            },
            "opportunities": {
                "polygons": int(len(opportunities)),
                "candidates": int(len(candidates)),
                "score_classes": {
                    str(key): int(value)
                    for key, value in class_counts.items()
                },
            },
            "voronoi": {
                "cells": int(len(voronoi)),
                "occupancy_classes": {
                    str(key): int(value)
                    for key, value in voronoi_counts.items()
                },
            },
            "grid": {
                "cell_size_m": grid["cell_size_m"],
                "width": grid["width"],
                "height": grid["height"],
                "minimum_clearance_m": round(
                    grid["minimum_clearance_m"], 6
                ),
                "candidate_spacing_m": round(
                    config["candidate_spacing_factor"]
                    * target["target_spacing_m"],
                    6,
                ),
            },
            "exclusions": {
                "features": exclusion_count,
                "provided": normalized_exclusions is not None,
            },
            "verification": verifications,
            "elapsed_seconds": elapsed_seconds,
        }

        result.warnings.append(
            "Los puntos generados son oportunidades geométricas de siembra, "
            "no plantas faltantes confirmadas."
        )

        if normalized_exclusions is None:
            result.warnings.append(
                "No se proporcionaron capas de vías, canales o infraestructura. "
                "El técnico debe clasificar el uso real de cada zona."
            )

        if global_difference <= 0:
            result.warnings.append(
                "La densidad global ya alcanza o supera el objetivo, pero pueden "
                "existir vacíos locales compensados por zonas de alta concentración."
            )

        result.success = True

    except Exception as error:
        result.errors.append(
            "No fue posible detectar oportunidades de siembra: "
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


def print_planting_opportunities_summary(
    result: PlantingOpportunitiesResult,
) -> None:
    """Muestra un resumen en PowerShell."""

    print("=" * 72)
    print("ANÁLISIS DE OPORTUNIDADES GEOMÉTRICAS DE SIEMBRA")
    print("=" * 72)
    print(f"Inventario: {result.inventory_gpkg}")
    print(f"Límite: {result.boundary_gpkg}")
    print(
        "Densidad objetivo: "
        f"{result.target_density_plants_ha} plantas/ha"
    )
    print(
        "Estado: "
        f"{'COMPLETADO' if result.success else 'ERROR'}"
    )

    if result.metadata:
        target = result.metadata["target"]
        inventory = result.metadata["inventory"]
        opportunities = result.metadata["opportunities"]

        print(
            "Área objetivo por planta: "
            f"{target['target_area_per_plant_m2']} m²"
        )
        print(
            "Separación equivalente: "
            f"{target['target_spacing_m']} m"
        )
        print(
            "Plantas analizadas: "
            f"{inventory['plants_used']}"
        )
        print(
            "Densidad actual: "
            f"{inventory['current_density_plants_ha']} plantas/ha"
        )
        print(
            "Polígonos de oportunidad: "
            f"{opportunities['polygons']}"
        )
        print(
            "Candidatos geométricos: "
            f"{opportunities['candidates']}"
        )

    if result.voronoi_gpkg:
        print(f"Territorios Voronoi: {result.voronoi_gpkg}")

    if result.opportunity_zones_gpkg:
        print(
            "Zonas de oportunidad: "
            f"{result.opportunity_zones_gpkg}"
        )

    if result.candidates_gpkg:
        print(f"Candidatos: {result.candidates_gpkg}")

    if result.summary_csv:
        print(f"Resumen: {result.summary_csv}")

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


def run_planting_opportunities(
    inventory_gpkg: str | Path,
    boundary_gpkg: str | Path,
    target_density_plants_ha: float,
    inventory_layer: str = "plantas_banano_validas",
    boundary_layer: str = "limite_analisis",
    config_path: str | Path | None = None,
    exclusions_gpkg: str | Path | None = None,
    exclusions_layer: str | None = None,
    output_dir: str | Path | None = None,
) -> int:
    """Ejecuta el análisis desde main.py."""

    result = detect_planting_opportunities(
        inventory_gpkg=inventory_gpkg,
        boundary_gpkg=boundary_gpkg,
        target_density_plants_ha=target_density_plants_ha,
        inventory_layer=inventory_layer,
        boundary_layer=boundary_layer,
        config_path=config_path,
        exclusions_gpkg=exclusions_gpkg,
        exclusions_layer=exclusions_layer,
        output_dir=output_dir,
    )

    print_planting_opportunities_summary(result)
    return 0 if result.success else 1
