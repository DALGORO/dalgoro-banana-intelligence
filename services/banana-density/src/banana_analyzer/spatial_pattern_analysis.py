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
from shapely.geometry import LineString


PROJECT_ROOT = Path(__file__).resolve().parents[2]
GLOBAL_LOGS_DIRECTORY = PROJECT_ROOT / "logs"
DEFAULT_CONFIG_PATH = PROJECT_ROOT / "config" / "spatial_analysis.yaml"


@dataclass
class SpatialPatternResult:
    """Resultado del análisis geométrico del patrón de siembra."""

    success: bool
    started_at: str
    finished_at: str | None
    inventory_gpkg: str
    boundary_gpkg: str
    inventory_layer: str
    boundary_layer: str
    config_path: str
    output_directory: str | None = None
    points_gpkg: str | None = None
    neighbors_gpkg: str | None = None
    orientation_gpkg: str | None = None
    summary_csv: str | None = None
    report_path: str | None = None
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


def clamp(value: float, minimum: float, maximum: float) -> float:
    """Limita un valor al intervalo indicado."""

    return max(minimum, min(maximum, value))


def angular_difference_deg(
    first_angle: np.ndarray | float,
    second_angle: float,
) -> np.ndarray:
    """Calcula diferencia angular axial entre 0 y 90 grados."""

    first = np.asarray(first_angle, dtype=float)
    return np.abs((first - second_angle + 90.0) % 180.0 - 90.0)


def load_config(config_path: Path) -> dict[str, Any]:
    """Carga y valida la configuración del análisis espacial."""

    if not config_path.is_file():
        raise FileNotFoundError(
            f"No existe el archivo de configuración: {config_path}"
        )

    with config_path.open("r", encoding="utf-8") as file:
        config = yaml.safe_load(file)

    if not isinstance(config, dict):
        raise ValueError("La configuración YAML no contiene un diccionario.")

    required_sections = {
        "kde",
        "hexagons",
        "gaps",
        "proximity",
        "orientation",
        "edge_filter",
        "voronoi",
    }

    missing_sections = sorted(required_sections - set(config))

    if missing_sections:
        raise ValueError(
            "Faltan secciones en la configuración: "
            + ", ".join(missing_sections)
        )

    numeric_values = {
        "kde.factor": config["kde"]["factor"],
        "kde.min_radius_m": config["kde"]["min_radius_m"],
        "kde.max_radius_m": config["kde"]["max_radius_m"],
        "kde.pixel_size_m": config["kde"]["pixel_size_m"],
        "hexagons.area_m2": config["hexagons"]["area_m2"],
        "gaps.factor": config["gaps"]["factor"],
        "proximity.factor": config["proximity"]["factor"],
        "orientation.angle_tolerance_deg": (
            config["orientation"]["angle_tolerance_deg"]
        ),
        "edge_filter.nearest_median_multiplier": (
            config["edge_filter"]["nearest_median_multiplier"]
        ),
        "edge_filter.min_margin_m": config["edge_filter"]["min_margin_m"],
        "edge_filter.max_margin_m": config["edge_filter"]["max_margin_m"],
    }

    for name, value in numeric_values.items():
        if not math.isfinite(float(value)):
            raise ValueError(f"El parámetro {name} debe ser finito.")

    if float(config["kde"]["factor"]) <= 0:
        raise ValueError("kde.factor debe ser mayor que cero.")

    if float(config["kde"]["min_radius_m"]) <= 0:
        raise ValueError("kde.min_radius_m debe ser mayor que cero.")

    if (
        float(config["kde"]["max_radius_m"])
        < float(config["kde"]["min_radius_m"])
    ):
        raise ValueError(
            "kde.max_radius_m no puede ser menor que kde.min_radius_m."
        )

    if float(config["hexagons"]["area_m2"]) <= 0:
        raise ValueError("hexagons.area_m2 debe ser mayor que cero.")

    if float(config["gaps"]["factor"]) <= 1.0:
        raise ValueError("gaps.factor debe ser mayor que 1.")

    proximity_factor = float(config["proximity"]["factor"])

    if not 0.0 < proximity_factor < 1.0:
        raise ValueError("proximity.factor debe estar entre 0 y 1.")

    angle_tolerance = float(
        config["orientation"]["angle_tolerance_deg"]
    )

    if not 1.0 <= angle_tolerance <= 45.0:
        raise ValueError(
            "orientation.angle_tolerance_deg debe estar entre 1 y 45."
        )

    return config


def resolve_output_directory(
    inventory_gpkg: Path,
    output_dir: str | Path | None,
) -> Path:
    """Determina la carpeta del análisis espacial."""

    if output_dir is not None:
        return Path(output_dir).expanduser().resolve(strict=False)

    return inventory_gpkg.parent / "analisis_espacial"


def read_inputs(
    inventory_gpkg: Path,
    boundary_gpkg: Path,
    inventory_layer: str,
    boundary_layer: str,
) -> tuple[gpd.GeoDataFrame, gpd.GeoDataFrame]:
    """Lee y valida las capas de inventario y límite."""

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

    if len(inventory) < 3:
        raise ValueError(
            "Se requieren al menos tres plantas para analizar el patrón."
        )

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

    if "detection_id" not in inventory.columns:
        raise ValueError("La capa de inventario no contiene detection_id.")

    inventory = inventory.copy()
    inventory["detection_id"] = (
        inventory["detection_id"].astype(str).str.strip()
    )

    if inventory["detection_id"].eq("").any():
        raise ValueError("Existen detection_id vacíos.")

    if inventory["detection_id"].duplicated().any():
        raise ValueError("Existen detection_id duplicados.")

    return inventory, boundary


def calculate_nearest_neighbors(
    coordinates: np.ndarray,
) -> tuple[cKDTree, np.ndarray, np.ndarray]:
    """Calcula el vecino más cercano de cada planta."""

    tree = cKDTree(coordinates)
    distances, indices = tree.query(coordinates, k=2)

    nearest_distances = distances[:, 1]
    nearest_indices = indices[:, 1]

    if not np.isfinite(nearest_distances).all():
        raise ValueError("No fue posible calcular todos los vecinos.")

    return tree, nearest_distances, nearest_indices


def describe_values(values: np.ndarray) -> dict[str, float | int | None]:
    """Calcula estadísticas descriptivas."""

    clean = np.asarray(values, dtype=float)
    clean = clean[np.isfinite(clean)]

    if clean.size == 0:
        return {
            "count": 0,
            "minimum": None,
            "p25": None,
            "median": None,
            "mean": None,
            "p75": None,
            "p90": None,
            "maximum": None,
            "standard_deviation": None,
        }

    return {
        "count": int(clean.size),
        "minimum": round(float(np.min(clean)), 6),
        "p25": round(float(np.percentile(clean, 25)), 6),
        "median": round(float(np.median(clean)), 6),
        "mean": round(float(np.mean(clean)), 6),
        "p75": round(float(np.percentile(clean, 75)), 6),
        "p90": round(float(np.percentile(clean, 90)), 6),
        "maximum": round(float(np.max(clean)), 6),
        "standard_deviation": round(float(np.std(clean, ddof=0)), 6),
    }


def select_interior_points(
    inventory: gpd.GeoDataFrame,
    boundary: gpd.GeoDataFrame,
    nearest_median: float,
    config: dict[str, Any],
) -> tuple[np.ndarray, np.ndarray, float, str | None]:
    """Selecciona puntos alejados del borde para calibración."""

    boundary_geometry = boundary.geometry.union_all()
    distance_to_boundary = inventory.geometry.distance(
        boundary_geometry.boundary
    ).to_numpy(dtype=float)

    edge_config = config["edge_filter"]
    edge_margin_m = clamp(
        float(edge_config["nearest_median_multiplier"]) * nearest_median,
        float(edge_config["min_margin_m"]),
        float(edge_config["max_margin_m"]),
    )

    interior_mask = distance_to_boundary >= edge_margin_m

    minimum_interior = max(
        int(edge_config["minimum_interior_points"]),
        int(
            math.ceil(
                len(inventory)
                * float(edge_config["minimum_interior_fraction"])
            )
        ),
    )

    warning = None

    if int(interior_mask.sum()) < minimum_interior:
        interior_mask = np.ones(len(inventory), dtype=bool)
        warning = (
            "La franja interior dejó pocos puntos. "
            "La calibración utilizó toda la plantación."
        )

    return interior_mask, distance_to_boundary, edge_margin_m, warning


def estimate_dominant_orientation(
    coordinates: np.ndarray,
    nearest_indices: np.ndarray,
    nearest_distances: np.ndarray,
    interior_mask: np.ndarray,
    config: dict[str, Any],
) -> tuple[float, float]:
    """Estima la orientación dominante del patrón."""

    selected_indices = np.flatnonzero(interior_mask)
    vectors = (
        coordinates[nearest_indices[selected_indices]]
        - coordinates[selected_indices]
    )

    angles = np.mod(
        np.degrees(np.arctan2(vectors[:, 1], vectors[:, 0])),
        180.0,
    )

    weights = 1.0 / np.maximum(
        nearest_distances[selected_indices],
        1e-6,
    )

    histogram, _ = np.histogram(
        angles,
        bins=np.arange(0.0, 181.0, 1.0),
        weights=weights,
    )

    half_window = int(
        config["orientation"]["smoothing_half_window_deg"]
    )

    smoothed = np.zeros_like(histogram, dtype=float)

    for offset in range(-half_window, half_window + 1):
        smoothed += np.roll(histogram, offset)

    peak_angle = float(np.argmax(smoothed)) + 0.5
    refinement_tolerance = float(
        config["orientation"]["refinement_tolerance_deg"]
    )

    close_mask = (
        angular_difference_deg(angles, peak_angle)
        <= refinement_tolerance
    )

    if not close_mask.any():
        return peak_angle % 180.0, 0.0

    selected_angles = angles[close_mask]
    selected_weights = weights[close_mask]
    doubled = np.radians(2.0 * selected_angles)

    sine_sum = float(
        np.sum(selected_weights * np.sin(doubled))
    )

    cosine_sum = float(
        np.sum(selected_weights * np.cos(doubled))
    )

    refined_angle = (
        0.5 * np.degrees(np.arctan2(sine_sum, cosine_sum))
    ) % 180.0

    support_percent = (
        float(selected_weights.sum() / weights.sum() * 100.0)
        if weights.sum() > 0
        else 0.0
    )

    return round(refined_angle, 6), round(support_percent, 4)


def collect_axis_spacings(
    tree: cKDTree,
    coordinates: np.ndarray,
    interior_mask: np.ndarray,
    orientation_deg: float,
    nearest_median: float,
    config: dict[str, Any],
) -> tuple[np.ndarray, np.ndarray]:
    """Obtiene distancias alineadas y perpendiculares más próximas."""

    point_count = len(coordinates)
    neighbor_count = min(
        int(config["orientation"]["nearest_neighbors_to_query"]),
        point_count,
    )

    distances, indices = tree.query(coordinates, k=neighbor_count)
    angle_tolerance = float(
        config["orientation"]["angle_tolerance_deg"]
    )

    maximum_distance = min(max(4.0 * nearest_median, 8.0), 20.0)
    aligned_distances: list[float] = []
    perpendicular_distances: list[float] = []

    for point_index in np.flatnonzero(interior_mask):
        best_aligned = math.inf
        best_perpendicular = math.inf

        for position in range(1, neighbor_count):
            neighbor_index = int(indices[point_index, position])
            distance_m = float(distances[point_index, position])

            if (
                neighbor_index == point_index
                or not interior_mask[neighbor_index]
                or not math.isfinite(distance_m)
                or distance_m <= 0.0
                or distance_m > maximum_distance
            ):
                continue

            vector = coordinates[neighbor_index] - coordinates[point_index]
            angle_deg = (
                math.degrees(
                    math.atan2(float(vector[1]), float(vector[0]))
                )
                % 180.0
            )

            difference = float(
                angular_difference_deg(angle_deg, orientation_deg)
            )

            if difference <= angle_tolerance:
                best_aligned = min(best_aligned, distance_m)

            if abs(90.0 - difference) <= angle_tolerance:
                best_perpendicular = min(best_perpendicular, distance_m)

        if math.isfinite(best_aligned):
            aligned_distances.append(best_aligned)

        if math.isfinite(best_perpendicular):
            perpendicular_distances.append(best_perpendicular)

    return (
        np.asarray(aligned_distances, dtype=float),
        np.asarray(perpendicular_distances, dtype=float),
    )


def robust_spacing_median(values: np.ndarray) -> float | None:
    """Calcula una mediana recortando extremos."""

    clean = np.asarray(values, dtype=float)
    clean = clean[np.isfinite(clean) & (clean > 0.0)]

    if clean.size == 0:
        return None

    if clean.size >= 20:
        lower = np.percentile(clean, 5)
        upper = np.percentile(clean, 95)
        clean = clean[(clean >= lower) & (clean <= upper)]

    if clean.size == 0:
        return None

    return float(np.median(clean))


def choose_row_orientation(
    tree: cKDTree,
    coordinates: np.ndarray,
    interior_mask: np.ndarray,
    dominant_orientation_deg: float,
    nearest_median: float,
    config: dict[str, Any],
) -> tuple[float, np.ndarray, np.ndarray, str]:
    """Escoge como eje de fila el de menor espaciamiento típico."""

    first_aligned, first_cross = collect_axis_spacings(
        tree=tree,
        coordinates=coordinates,
        interior_mask=interior_mask,
        orientation_deg=dominant_orientation_deg,
        nearest_median=nearest_median,
        config=config,
    )

    first_aligned_median = robust_spacing_median(first_aligned)
    first_cross_median = robust_spacing_median(first_cross)

    if (
        first_aligned_median is not None
        and first_cross_median is not None
        and first_aligned_median > first_cross_median
    ):
        swapped_orientation = (dominant_orientation_deg + 90.0) % 180.0

        second_aligned, second_cross = collect_axis_spacings(
            tree=tree,
            coordinates=coordinates,
            interior_mask=interior_mask,
            orientation_deg=swapped_orientation,
            nearest_median=nearest_median,
            config=config,
        )

        return (
            round(swapped_orientation, 6),
            second_aligned,
            second_cross,
            "orthogonal_axis_selected_because_spacing_was_smaller",
        )

    return (
        dominant_orientation_deg,
        first_aligned,
        first_cross,
        "dominant_nearest_neighbor_axis",
    )


def classify_proximity(
    ratios: np.ndarray,
    config: dict[str, Any],
) -> np.ndarray:
    """Clasifica la proximidad relativa usando d50."""

    proximity_config = config["proximity"]
    strong_ratio = float(proximity_config["strong_ratio"])
    high_ratio = float(proximity_config["high_ratio"])
    open_ratio = float(proximity_config["open_ratio"])

    labels = np.full(
        ratios.shape,
        "espaciamiento_tipico",
        dtype=object,
    )

    labels[ratios < strong_ratio] = "aglomeracion_fuerte"
    labels[
        (ratios >= strong_ratio) & (ratios < high_ratio)
    ] = "proximidad_alta"
    labels[ratios > open_ratio] = "posible_espacio_abierto"

    return labels


def build_enriched_points(
    inventory: gpd.GeoDataFrame,
    nearest_indices: np.ndarray,
    nearest_distances: np.ndarray,
    nearest_median: float,
    distance_to_boundary: np.ndarray,
    interior_mask: np.ndarray,
    config: dict[str, Any],
) -> gpd.GeoDataFrame:
    """Añade indicadores espaciales a cada planta."""

    enriched = inventory.copy()
    detection_ids = inventory["detection_id"].astype(str).to_numpy()
    ratios = nearest_distances / nearest_median

    enriched["nn_detection_id"] = detection_ids[nearest_indices]
    enriched["nn_distance_m"] = np.round(nearest_distances, 6)
    enriched["nn_ratio_d50"] = np.round(ratios, 6)
    enriched["proximity_class"] = classify_proximity(ratios, config)
    enriched["distance_boundary_m"] = np.round(
        distance_to_boundary,
        6,
    )
    enriched["used_for_calibration"] = interior_mask

    return enriched


def build_neighbor_lines(
    inventory: gpd.GeoDataFrame,
    nearest_indices: np.ndarray,
    nearest_distances: np.ndarray,
    nearest_median: float,
    config: dict[str, Any],
) -> gpd.GeoDataFrame:
    """Construye enlaces únicos hacia vecinos cercanos."""

    records: list[dict[str, Any]] = []
    geometries: list[LineString] = []
    detection_ids = inventory["detection_id"].astype(str).to_numpy()
    seen_pairs: set[tuple[str, str]] = set()

    for index, neighbor_index in enumerate(nearest_indices):
        first_id = detection_ids[index]
        second_id = detection_ids[neighbor_index]
        pair = tuple(sorted((first_id, second_id)))

        if pair in seen_pairs:
            continue

        seen_pairs.add(pair)
        distance_m = float(nearest_distances[index])
        ratio = distance_m / nearest_median

        records.append(
            {
                "detection_id_a": first_id,
                "detection_id_b": second_id,
                "distance_m": round(distance_m, 6),
                "ratio_d50": round(ratio, 6),
                "proximity_class": classify_proximity(
                    np.asarray([ratio], dtype=float),
                    config,
                )[0],
            }
        )

        geometries.append(
            LineString(
                [
                    inventory.geometry.iloc[index],
                    inventory.geometry.iloc[neighbor_index],
                ]
            )
        )

    return gpd.GeoDataFrame(
        records,
        geometry=geometries,
        crs=inventory.crs,
    )


def build_orientation_line(
    boundary: gpd.GeoDataFrame,
    orientation_deg: float,
    within_row_spacing_m: float | None,
    between_row_spacing_m: float | None,
    kde_radius_m: float,
) -> gpd.GeoDataFrame:
    """Crea una línea cartográfica con la orientación estimada."""

    boundary_geometry = boundary.geometry.union_all()
    centroid = boundary_geometry.centroid
    min_x, min_y, max_x, max_y = boundary_geometry.bounds

    half_length = max(
        math.hypot(max_x - min_x, max_y - min_y) / 2.0,
        1.0,
    )

    angle_radians = math.radians(orientation_deg)
    offset_x = math.cos(angle_radians) * half_length
    offset_y = math.sin(angle_radians) * half_length

    line = LineString(
        [
            (centroid.x - offset_x, centroid.y - offset_y),
            (centroid.x + offset_x, centroid.y + offset_y),
        ]
    )

    return gpd.GeoDataFrame(
        [
            {
                "orientation_deg": orientation_deg,
                "within_row_spacing_m": within_row_spacing_m,
                "between_row_spacing_m": between_row_spacing_m,
                "recommended_kde_radius_m": kde_radius_m,
            }
        ],
        geometry=[line],
        crs=boundary.crs,
    )


def write_csv_atomic(table: pd.DataFrame, output_path: Path) -> None:
    """Escribe un CSV mediante archivo temporal."""

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
    """Verifica nuevamente una salida GeoPackage."""

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

    return {
        "layers": layers.tolist(),
        "rows": int(len(verified)),
        "crs": verified.crs.to_string(),
        "geometry_types": sorted(
            verified.geometry.geom_type.unique().tolist()
        ),
    }


def save_report(
    result: SpatialPatternResult,
    report_path: Path,
) -> Path:
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


def analyze_spatial_pattern(
    inventory_gpkg: str | Path,
    boundary_gpkg: str | Path,
    inventory_layer: str = "plantas_banano_validas",
    boundary_layer: str = "limite_analisis",
    config_path: str | Path | None = None,
    output_dir: str | Path | None = None,
) -> SpatialPatternResult:
    """Analiza distancias, alineación y parámetros cartográficos."""

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

    result = SpatialPatternResult(
        success=False,
        started_at=started_at,
        finished_at=None,
        inventory_gpkg=str(normalized_inventory_gpkg),
        boundary_gpkg=str(normalized_boundary_gpkg),
        inventory_layer=inventory_layer,
        boundary_layer=boundary_layer,
        config_path=str(normalized_config_path),
    )

    output_directory = resolve_output_directory(
        inventory_gpkg=normalized_inventory_gpkg,
        output_dir=output_dir,
    )
    result.output_directory = str(output_directory)

    points_gpkg_path = output_directory / "patron_espacial_puntos.gpkg"
    neighbors_gpkg_path = output_directory / "vecinos_mas_cercanos.gpkg"
    orientation_gpkg_path = output_directory / "orientacion_filas.gpkg"
    summary_csv_path = output_directory / "analisis_patron_espacial.csv"
    report_path = output_directory / "analisis_patron_espacial.json"

    expected_outputs = (
        points_gpkg_path,
        neighbors_gpkg_path,
        orientation_gpkg_path,
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
            "spatial_pattern_error_"
            + datetime.now().strftime("%Y%m%d_%H%M%S")
            + ".json"
        )
        save_report(result, error_report)
        return result

    output_directory.mkdir(parents=True, exist_ok=True)
    generated_paths: list[Path] = []

    try:
        config = load_config(normalized_config_path)

        inventory, boundary = read_inputs(
            inventory_gpkg=normalized_inventory_gpkg,
            boundary_gpkg=normalized_boundary_gpkg,
            inventory_layer=inventory_layer,
            boundary_layer=boundary_layer,
        )

        coordinates = np.column_stack(
            (
                inventory.geometry.x.to_numpy(dtype=float),
                inventory.geometry.y.to_numpy(dtype=float),
            )
        )

        tree, nearest_distances, nearest_indices = (
            calculate_nearest_neighbors(coordinates)
        )

        if np.any(nearest_distances <= 0.0):
            result.warnings.append(
                "Se encontraron centros coincidentes o casi coincidentes."
            )

        nearest_stats_all = describe_values(nearest_distances)
        nearest_median = float(nearest_stats_all["median"])

        if nearest_median <= 0.0:
            raise ValueError(
                "La mediana del vecino más cercano debe ser mayor que cero."
            )

        (
            interior_mask,
            distance_to_boundary,
            edge_margin_m,
            interior_warning,
        ) = select_interior_points(
            inventory=inventory,
            boundary=boundary,
            nearest_median=nearest_median,
            config=config,
        )

        if interior_warning:
            result.warnings.append(interior_warning)

        nearest_stats_interior = describe_values(
            nearest_distances[interior_mask]
        )

        (
            dominant_orientation_deg,
            orientation_support_percent,
        ) = estimate_dominant_orientation(
            coordinates=coordinates,
            nearest_indices=nearest_indices,
            nearest_distances=nearest_distances,
            interior_mask=interior_mask,
            config=config,
        )

        (
            row_orientation_deg,
            within_row_distances,
            between_row_distances,
            orientation_method,
        ) = choose_row_orientation(
            tree=tree,
            coordinates=coordinates,
            interior_mask=interior_mask,
            dominant_orientation_deg=dominant_orientation_deg,
            nearest_median=nearest_median,
            config=config,
        )

        within_row_spacing_m = robust_spacing_median(within_row_distances)
        between_row_spacing_m = robust_spacing_median(between_row_distances)

        minimum_spacing_samples = max(
            10,
            int(math.ceil(interior_mask.sum() * 0.05)),
        )

        if len(within_row_distances) < minimum_spacing_samples:
            result.warnings.append(
                "El espaciamiento dentro de fila tiene pocas observaciones."
            )

        if len(between_row_distances) < minimum_spacing_samples:
            result.warnings.append(
                "El espaciamiento entre filas tiene pocas observaciones."
            )

        if within_row_spacing_m is None:
            within_row_spacing_m = nearest_median
            result.warnings.append(
                "Se usó d50 como espaciamiento provisional dentro de fila."
            )

        kde_config = config["kde"]
        kde_radius_m = clamp(
            float(kde_config["factor"]) * nearest_median,
            float(kde_config["min_radius_m"]),
            float(kde_config["max_radius_m"]),
        )

        gap_threshold_m = (
            float(config["gaps"]["factor"])
            * within_row_spacing_m
        )

        high_proximity_threshold_m = (
            float(config["proximity"]["factor"])
            * nearest_median
        )

        enriched_points = build_enriched_points(
            inventory=inventory,
            nearest_indices=nearest_indices,
            nearest_distances=nearest_distances,
            nearest_median=nearest_median,
            distance_to_boundary=distance_to_boundary,
            interior_mask=interior_mask,
            config=config,
        )

        neighbor_lines = build_neighbor_lines(
            inventory=inventory,
            nearest_indices=nearest_indices,
            nearest_distances=nearest_distances,
            nearest_median=nearest_median,
            config=config,
        )

        orientation_line = build_orientation_line(
            boundary=boundary,
            orientation_deg=row_orientation_deg,
            within_row_spacing_m=within_row_spacing_m,
            between_row_spacing_m=between_row_spacing_m,
            kde_radius_m=kde_radius_m,
        )

        write_gpkg_atomic(
            enriched_points,
            points_gpkg_path,
            "plantas_analizadas",
        )
        generated_paths.append(points_gpkg_path)

        write_gpkg_atomic(
            neighbor_lines,
            neighbors_gpkg_path,
            "vecinos_mas_cercanos",
        )
        generated_paths.append(neighbors_gpkg_path)

        write_gpkg_atomic(
            orientation_line,
            orientation_gpkg_path,
            "orientacion_estimada_filas",
        )
        generated_paths.append(orientation_gpkg_path)

        summary_record = {
            "fecha_proceso": datetime.now().isoformat(timespec="seconds"),
            "epsg": inventory.crs.to_epsg(),
            "plantas_analizadas": int(len(inventory)),
            "plantas_calibracion_interior": int(interior_mask.sum()),
            "margen_borde_m": round(edge_margin_m, 4),
            "vecino_mediana_m": round(nearest_median, 4),
            "vecino_p25_m": nearest_stats_all["p25"],
            "vecino_p75_m": nearest_stats_all["p75"],
            "orientacion_fila_grados": round(row_orientation_deg, 4),
            "soporte_orientacion_porcentaje": orientation_support_percent,
            "espaciamiento_en_fila_m": round(within_row_spacing_m, 4),
            "espaciamiento_entre_filas_m": (
                round(between_row_spacing_m, 4)
                if between_row_spacing_m is not None
                else None
            ),
            "radio_kde_recomendado_m": round(kde_radius_m, 4),
            "pixel_kde_m": float(kde_config["pixel_size_m"]),
            "area_hexagono_m2": round(
                float(config["hexagons"]["area_m2"]),
                4,
            ),
            "umbral_hueco_probable_m": round(gap_threshold_m, 4),
            "umbral_alta_proximidad_m": round(
                high_proximity_threshold_m,
                4,
            ),
        }

        write_csv_atomic(pd.DataFrame([summary_record]), summary_csv_path)
        generated_paths.append(summary_csv_path)

        elapsed_seconds = round(time.perf_counter() - start_time, 3)

        result.points_gpkg = str(points_gpkg_path)
        result.neighbors_gpkg = str(neighbors_gpkg_path)
        result.orientation_gpkg = str(orientation_gpkg_path)
        result.summary_csv = str(summary_csv_path)

        result.metadata = {
            "inventory": {
                "plants": int(len(inventory)),
                "epsg": inventory.crs.to_epsg(),
                "crs": inventory.crs.to_string(),
            },
            "calibration": {
                "interior_plants": int(interior_mask.sum()),
                "edge_margin_m": round(edge_margin_m, 6),
                "used_all_points": bool(interior_mask.all()),
            },
            "nearest_neighbor_all": nearest_stats_all,
            "nearest_neighbor_interior": nearest_stats_interior,
            "orientation": {
                "dominant_alignment_deg": dominant_orientation_deg,
                "estimated_row_orientation_deg": row_orientation_deg,
                "support_percent": orientation_support_percent,
                "method": orientation_method,
                "angle_reference": (
                    "degrees_counterclockwise_from_positive_x_axis"
                ),
                "angle_tolerance_deg": float(
                    config["orientation"]["angle_tolerance_deg"]
                ),
            },
            "spacing": {
                "within_row_m": round(within_row_spacing_m, 6),
                "between_rows_m": (
                    round(between_row_spacing_m, 6)
                    if between_row_spacing_m is not None
                    else None
                ),
                "within_row_samples": int(len(within_row_distances)),
                "between_row_samples": int(len(between_row_distances)),
            },
            "recommended_parameters": {
                "kde": {
                    "factor": float(kde_config["factor"]),
                    "minimum_radius_m": float(kde_config["min_radius_m"]),
                    "maximum_radius_m": float(kde_config["max_radius_m"]),
                    "recommended_radius_m": round(kde_radius_m, 6),
                    "pixel_size_m": float(kde_config["pixel_size_m"]),
                    "kernel": str(kde_config["kernel"]),
                },
                "hexagons": {
                    "area_m2": float(config["hexagons"]["area_m2"]),
                    "area_hectares": round(
                        float(config["hexagons"]["area_m2"]) / 10000.0,
                        6,
                    ),
                },
                "gaps": {
                    "factor": float(config["gaps"]["factor"]),
                    "probable_gap_distance_m": round(
                        gap_threshold_m,
                        6,
                    ),
                    "status": "candidate_for_field_verification",
                },
                "high_proximity": {
                    "factor": float(config["proximity"]["factor"]),
                    "distance_threshold_m": round(
                        high_proximity_threshold_m,
                        6,
                    ),
                },
                "voronoi": {
                    "possible_open_area_ratio": float(
                        config["voronoi"]["possible_open_area_ratio"]
                    ),
                    "severe_open_area_ratio": float(
                        config["voronoi"]["severe_open_area_ratio"]
                    ),
                    "high_competition_ratio": float(
                        config["voronoi"]["high_competition_ratio"]
                    ),
                },
            },
            "verification": {
                "points": verify_gpkg(
                    points_gpkg_path,
                    "plantas_analizadas",
                    len(enriched_points),
                ),
                "neighbors": verify_gpkg(
                    neighbors_gpkg_path,
                    "vecinos_mas_cercanos",
                    len(neighbor_lines),
                ),
                "orientation": verify_gpkg(
                    orientation_gpkg_path,
                    "orientacion_estimada_filas",
                    1,
                ),
            },
            "elapsed_seconds": elapsed_seconds,
        }

        result.warnings.append(
            "La orientación y los espaciamientos son estimaciones "
            "geométricas y deben revisarse sobre la ortofoto."
        )

        result.success = True

    except Exception as error:
        result.errors.append(
            "No fue posible analizar el patrón espacial: "
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


def print_spatial_pattern_summary(result: SpatialPatternResult) -> None:
    """Muestra un resumen en terminal."""

    print("=" * 72)
    print("ANÁLISIS DEL PATRÓN ESPACIAL DE SIEMBRA")
    print("=" * 72)
    print(f"Inventario: {result.inventory_gpkg}")
    print(f"Límite: {result.boundary_gpkg}")
    print(
        "Estado: "
        f"{'COMPLETADO' if result.success else 'ERROR'}"
    )

    if result.metadata:
        nearest = result.metadata["nearest_neighbor_all"]
        spacing = result.metadata["spacing"]
        orientation = result.metadata["orientation"]
        recommended = result.metadata["recommended_parameters"]

        print(
            "Plantas analizadas: "
            f"{result.metadata['inventory']['plants']}"
        )
        print(
            "Mediana vecino más cercano: "
            f"{nearest['median']} m"
        )
        print(
            "Orientación estimada de filas: "
            f"{orientation['estimated_row_orientation_deg']}°"
        )
        print(
            "Espaciamiento dentro de fila: "
            f"{spacing['within_row_m']} m"
        )
        print(
            "Espaciamiento entre filas: "
            f"{spacing['between_rows_m']} m"
        )
        print(
            "Radio KDE recomendado: "
            f"{recommended['kde']['recommended_radius_m']} m"
        )
        print(
            "Umbral de hueco probable: "
            f"{recommended['gaps']['probable_gap_distance_m']} m"
        )
        print(
            "Umbral de alta proximidad: "
            f"{recommended['high_proximity']['distance_threshold_m']} m"
        )
        print(
            "Tiempo: "
            f"{result.metadata['elapsed_seconds']} segundos"
        )

    if result.points_gpkg:
        print(f"Puntos analizados: {result.points_gpkg}")

    if result.neighbors_gpkg:
        print(f"Enlaces de vecinos: {result.neighbors_gpkg}")

    if result.orientation_gpkg:
        print(f"Orientación de filas: {result.orientation_gpkg}")

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


def run_spatial_pattern_analysis(
    inventory_gpkg: str | Path,
    boundary_gpkg: str | Path,
    inventory_layer: str = "plantas_banano_validas",
    boundary_layer: str = "limite_analisis",
    config_path: str | Path | None = None,
    output_dir: str | Path | None = None,
) -> int:
    """Ejecuta el análisis desde main.py."""

    result = analyze_spatial_pattern(
        inventory_gpkg=inventory_gpkg,
        boundary_gpkg=boundary_gpkg,
        inventory_layer=inventory_layer,
        boundary_layer=boundary_layer,
        config_path=config_path,
        output_dir=output_dir,
    )

    print_spatial_pattern_summary(result)
    return 0 if result.success else 1
