from __future__ import annotations

import csv
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
from rasterio.features import geometry_mask, shapes
from rasterio.transform import from_origin
from scipy.signal import fftconvolve
from shapely.geometry import shape


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONFIG_PATH = PROJECT_ROOT / "config" / "spatial_analysis.yaml"
GLOBAL_LOGS_DIRECTORY = PROJECT_ROOT / "logs"

NODATA_FLOAT = -9999.0
NODATA_CLASS = 0

CLASS_LABELS: dict[int, str] = {
    1: "deficit_severo",
    2: "deficit_moderado",
    3: "densidad_esperada",
    4: "densidad_elevada",
    5: "densidad_muy_elevada",
    6: "borde_no_evaluable",
}

DEFAULT_KDE_MAP_CONFIG: dict[str, Any] = {
    "fallback_radius_m": 6.0,
    "use_edge_correction": True,
    "minimum_kernel_coverage_ratio": 0.50,
    "minimum_zone_area_m2": 4.0,
    "write_raw_density": True,
    "write_kernel_coverage": True,
}


@dataclass
class KdeDensityResult:
    """Resultado de la generación del mapa continuo de densidad KDE."""

    success: bool
    started_at: str
    finished_at: str | None
    inventory_gpkg: str
    boundary_gpkg: str
    target_density_plants_ha: float
    spatial_report_json: str | None
    output_directory: str | None = None
    corrected_density_raster: str | None = None
    raw_density_raster: str | None = None
    relative_density_raster: str | None = None
    class_raster: str | None = None
    kernel_coverage_raster: str | None = None
    zones_gpkg: str | None = None
    deficit_zones_gpkg: str | None = None
    high_density_zones_gpkg: str | None = None
    summary_csv: str | None = None
    report_path: str | None = None
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


def density_label(value: float) -> str:
    """Convierte la densidad en una etiqueta segura para carpetas."""

    if float(value).is_integer():
        return str(int(value))

    return str(value).replace(".", "p")


def resolve_output_directory(
    inventory_gpkg: Path,
    target_density_plants_ha: float,
    output_dir: str | Path | None,
) -> Path:
    """Determina la carpeta de salida."""

    if output_dir is not None:
        return Path(output_dir).expanduser().resolve(strict=False)

    label = density_label(target_density_plants_ha)

    if inventory_gpkg.parent.name == "05_gis":
        return inventory_gpkg.parent / f"mapa_calor_kde_{label}"

    return inventory_gpkg.parent / f"mapa_calor_kde_{label}"


def deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    """Combina diccionarios anidados sin modificar los originales."""

    merged = dict(base)

    for key, value in override.items():
        if (
            key in merged
            and isinstance(merged[key], dict)
            and isinstance(value, dict)
        ):
            merged[key] = deep_merge(merged[key], value)
        else:
            merged[key] = value

    return merged


def load_kde_config(
    config_path: str | Path | None,
) -> tuple[Path, dict[str, Any]]:
    """Carga y valida la configuración KDE."""

    normalized_path = (
        Path(config_path).expanduser().resolve(strict=False)
        if config_path is not None
        else DEFAULT_CONFIG_PATH
    )

    if not normalized_path.is_file():
        raise FileNotFoundError(
            f"No existe el archivo de configuración: {normalized_path}"
        )

    with normalized_path.open("r", encoding="utf-8") as file:
        full_config = yaml.safe_load(file) or {}

    if "kde" not in full_config:
        raise ValueError("La configuración no contiene la sección 'kde'.")

    if "hexagons" not in full_config:
        raise ValueError("La configuración no contiene la sección 'hexagons'.")

    kde_config = dict(full_config["kde"])
    hex_config = dict(full_config["hexagons"])
    map_config = deep_merge(
        DEFAULT_KDE_MAP_CONFIG,
        full_config.get("kde_map", {}),
    )

    required_kde = {
        "min_radius_m",
        "max_radius_m",
        "pixel_size_m",
        "kernel",
    }

    missing_kde = sorted(required_kde - set(kde_config))

    if missing_kde:
        raise ValueError(
            "Faltan parámetros en kde: " + ", ".join(missing_kde)
        )

    required_thresholds = {
        "deficit_severe_ratio",
        "deficit_moderate_ratio",
        "expected_upper_ratio",
        "elevated_upper_ratio",
    }

    missing_thresholds = sorted(required_thresholds - set(hex_config))

    if missing_thresholds:
        raise ValueError(
            "Faltan umbrales en hexagons: "
            + ", ".join(missing_thresholds)
        )

    for key in (
        "min_radius_m",
        "max_radius_m",
        "pixel_size_m",
    ):
        kde_config[key] = float(kde_config[key])

    if kde_config["min_radius_m"] <= 0:
        raise ValueError("kde.min_radius_m debe ser mayor que cero.")

    if kde_config["max_radius_m"] < kde_config["min_radius_m"]:
        raise ValueError(
            "kde.max_radius_m no puede ser menor que kde.min_radius_m."
        )

    if kde_config["pixel_size_m"] <= 0:
        raise ValueError("kde.pixel_size_m debe ser mayor que cero.")

    kde_config["kernel"] = str(kde_config["kernel"]).strip().lower()

    for key in required_thresholds:
        hex_config[key] = float(hex_config[key])

    threshold_values = [
        hex_config["deficit_severe_ratio"],
        hex_config["deficit_moderate_ratio"],
        hex_config["expected_upper_ratio"],
        hex_config["elevated_upper_ratio"],
    ]

    if not (
        0 < threshold_values[0]
        < threshold_values[1]
        < threshold_values[2]
        < threshold_values[3]
    ):
        raise ValueError(
            "Los umbrales de densidad deben ser crecientes y mayores que cero."
        )

    map_config["fallback_radius_m"] = float(
        map_config["fallback_radius_m"]
    )
    map_config["minimum_kernel_coverage_ratio"] = float(
        map_config["minimum_kernel_coverage_ratio"]
    )
    map_config["minimum_zone_area_m2"] = float(
        map_config["minimum_zone_area_m2"]
    )
    map_config["use_edge_correction"] = bool(
        map_config["use_edge_correction"]
    )
    map_config["write_raw_density"] = bool(
        map_config["write_raw_density"]
    )
    map_config["write_kernel_coverage"] = bool(
        map_config["write_kernel_coverage"]
    )

    if map_config["fallback_radius_m"] <= 0:
        raise ValueError("kde_map.fallback_radius_m debe ser mayor que cero.")

    if not 0 < map_config["minimum_kernel_coverage_ratio"] <= 1:
        raise ValueError(
            "kde_map.minimum_kernel_coverage_ratio debe estar entre 0 y 1."
        )

    if map_config["minimum_zone_area_m2"] < 0:
        raise ValueError(
            "kde_map.minimum_zone_area_m2 no puede ser negativo."
        )

    return normalized_path, {
        "kde": kde_config,
        "hexagons": hex_config,
        "kde_map": map_config,
    }


def validate_target_density(target_density_plants_ha: float) -> None:
    """Valida la densidad objetivo."""

    if (
        not math.isfinite(target_density_plants_ha)
        or target_density_plants_ha <= 0
    ):
        raise ValueError(
            "La densidad objetivo debe ser un número finito mayor que cero."
        )


def ensure_layer_exists(gpkg_path: Path, layer_name: str) -> None:
    """Comprueba que una capa exista en el GeoPackage."""

    layers = pyogrio.list_layers(gpkg_path)
    available = {str(row[0]) for row in layers}

    if layer_name not in available:
        raise ValueError(
            f"La capa '{layer_name}' no existe en {gpkg_path}. "
            f"Capas disponibles: {sorted(available)}"
        )


def load_inputs(
    inventory_gpkg: Path,
    boundary_gpkg: Path,
    inventory_layer: str,
    boundary_layer: str,
) -> tuple[gpd.GeoDataFrame, gpd.GeoDataFrame, CRS]:
    """Carga y valida el inventario y el límite."""

    if not inventory_gpkg.is_file():
        raise FileNotFoundError(
            f"No existe el inventario: {inventory_gpkg}"
        )

    if not boundary_gpkg.is_file():
        raise FileNotFoundError(
            f"No existe el límite: {boundary_gpkg}"
        )

    ensure_layer_exists(inventory_gpkg, inventory_layer)
    ensure_layer_exists(boundary_gpkg, boundary_layer)

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
        raise ValueError("El inventario de plantas está vacío.")

    if boundary.empty:
        raise ValueError("La capa de límite está vacía.")

    if inventory.crs is None or boundary.crs is None:
        raise ValueError("Las capas de entrada deben tener CRS.")

    if inventory.crs != boundary.crs:
        boundary = boundary.to_crs(inventory.crs)

    crs = CRS.from_user_input(inventory.crs)

    if not crs.is_projected:
        raise ValueError("El análisis KDE requiere un CRS proyectado.")

    units = [
        axis.unit_name.lower()
        for axis in crs.axis_info
        if axis.unit_name
    ]

    if not units or not all(
        "metre" in unit or "meter" in unit
        for unit in units
    ):
        raise ValueError("El CRS debe utilizar metros.")

    if inventory.geometry.isna().any() or inventory.geometry.is_empty.any():
        raise ValueError("El inventario contiene geometrías vacías.")

    if inventory.geometry.geom_type.ne("Point").any():
        raise ValueError("El inventario debe contener geometrías Point.")

    if boundary.geometry.isna().any() or boundary.geometry.is_empty.any():
        raise ValueError("El límite contiene geometrías vacías.")

    if not boundary.geometry.is_valid.all():
        boundary = boundary.copy()
        boundary["geometry"] = boundary.geometry.make_valid()

    boundary_union = boundary.geometry.union_all()

    if boundary_union.is_empty:
        raise ValueError("No fue posible construir el límite unificado.")

    inside_mask = inventory.geometry.apply(boundary_union.covers)
    outside_count = int((~inside_mask).sum())

    if outside_count > 0:
        inventory = inventory.loc[inside_mask].copy()

    if inventory.empty:
        raise ValueError("No existen plantas dentro del límite.")

    return inventory, boundary, crs


def auto_detect_spatial_report(inventory_gpkg: Path) -> Path | None:
    """Busca el informe espacial junto al inventario validado."""

    candidates = [
        inventory_gpkg.parent
        / "analisis_espacial"
        / "analisis_patron_espacial.json",
        inventory_gpkg.parent
        / "analisis_patron_espacial.json",
    ]

    for candidate in candidates:
        if candidate.is_file():
            return candidate

    return None


def read_report_parameter(
    report_path: Path,
    parameter_name: str,
) -> float | None:
    """Lee un parámetro KDE desde el informe espacial."""

    with report_path.open("r", encoding="utf-8") as file:
        data = json.load(file)

    metadata = data.get("metadata", {})
    recommended = metadata.get("recommended_parameters", {})
    kde = recommended.get("kde", {})

    value = kde.get(parameter_name)

    if value is None:
        return None

    numeric_value = float(value)

    if not math.isfinite(numeric_value):
        return None

    return numeric_value


def resolve_radius_and_pixel_size(
    inventory_gpkg: Path,
    spatial_report_json: str | Path | None,
    manual_radius_m: float | None,
    manual_pixel_size_m: float | None,
    config: dict[str, Any],
) -> tuple[float, float, Path | None, list[str], dict[str, str]]:
    """Resuelve radio y tamaño de píxel, priorizando valores manuales."""

    warnings: list[str] = []
    source = {
        "radius": "",
        "pixel_size": "",
    }

    report_path: Path | None

    if spatial_report_json is not None:
        report_path = Path(spatial_report_json).expanduser().resolve(
            strict=False
        )

        if not report_path.is_file():
            raise FileNotFoundError(
                f"No existe el informe espacial: {report_path}"
            )
    else:
        report_path = auto_detect_spatial_report(inventory_gpkg)

    kde_config = config["kde"]
    map_config = config["kde_map"]

    if manual_radius_m is not None:
        radius_m = float(manual_radius_m)
        source["radius"] = "manual"
    elif report_path is not None:
        report_radius = read_report_parameter(
            report_path,
            "recommended_radius_m",
        )

        if report_radius is not None:
            radius_m = report_radius
            source["radius"] = "spatial_report"
        else:
            radius_m = float(map_config["fallback_radius_m"])
            source["radius"] = "configuration_fallback"
            warnings.append(
                "El informe espacial no contiene el radio KDE recomendado. "
                "Se utilizó el valor de respaldo de la configuración."
            )
    else:
        radius_m = float(map_config["fallback_radius_m"])
        source["radius"] = "configuration_fallback"
        warnings.append(
            "No se encontró el informe espacial. Se utilizó el radio KDE "
            "de respaldo configurado."
        )

    if manual_pixel_size_m is not None:
        pixel_size_m = float(manual_pixel_size_m)
        source["pixel_size"] = "manual"
    elif report_path is not None:
        report_pixel = read_report_parameter(
            report_path,
            "pixel_size_m",
        )

        if report_pixel is not None:
            pixel_size_m = report_pixel
            source["pixel_size"] = "spatial_report"
        else:
            pixel_size_m = float(kde_config["pixel_size_m"])
            source["pixel_size"] = "configuration"
    else:
        pixel_size_m = float(kde_config["pixel_size_m"])
        source["pixel_size"] = "configuration"

    if not math.isfinite(radius_m) or radius_m <= 0:
        raise ValueError("El radio KDE debe ser mayor que cero.")

    if not math.isfinite(pixel_size_m) or pixel_size_m <= 0:
        raise ValueError("El tamaño de píxel debe ser mayor que cero.")

    configured_min = float(kde_config["min_radius_m"])
    configured_max = float(kde_config["max_radius_m"])

    if radius_m < configured_min or radius_m > configured_max:
        warnings.append(
            "El radio KDE utilizado se encuentra fuera del rango de "
            f"referencia configurado ({configured_min}–{configured_max} m)."
        )

    if pixel_size_m > radius_m / 3.0:
        warnings.append(
            "El tamaño de píxel es grande respecto del radio KDE. "
            "La superficie puede verse demasiado escalonada."
        )

    return (
        radius_m,
        pixel_size_m,
        report_path,
        warnings,
        source,
    )


def build_analysis_grid(
    boundary_geometry: Any,
    radius_m: float,
    pixel_size_m: float,
) -> tuple[rasterio.Affine, int, int]:
    """Construye una cuadrícula con margen equivalente al radio KDE."""

    min_x, min_y, max_x, max_y = boundary_geometry.bounds

    padded_min_x = min_x - radius_m
    padded_min_y = min_y - radius_m
    padded_max_x = max_x + radius_m
    padded_max_y = max_y + radius_m

    width = int(
        math.ceil(
            (padded_max_x - padded_min_x)
            / pixel_size_m
        )
    )

    height = int(
        math.ceil(
            (padded_max_y - padded_min_y)
            / pixel_size_m
        )
    )

    if width <= 0 or height <= 0:
        raise ValueError("La cuadrícula KDE tiene dimensiones inválidas.")

    transform = from_origin(
        padded_min_x,
        padded_max_y,
        pixel_size_m,
        pixel_size_m,
    )

    return transform, width, height


def build_boundary_mask(
    boundary_geometry: Any,
    transform: rasterio.Affine,
    width: int,
    height: int,
) -> np.ndarray:
    """Crea una máscara booleana del límite."""

    mask = geometry_mask(
        [boundary_geometry],
        out_shape=(height, width),
        transform=transform,
        invert=True,
        all_touched=False,
    )

    if not mask.any():
        raise ValueError("La máscara del límite quedó vacía.")

    return mask


def rasterize_point_counts(
    inventory: gpd.GeoDataFrame,
    transform: rasterio.Affine,
    width: int,
    height: int,
) -> np.ndarray:
    """Convierte los centros de plantas en una cuadrícula de conteos."""

    inverse = ~transform
    x_values = inventory.geometry.x.to_numpy(dtype=float)
    y_values = inventory.geometry.y.to_numpy(dtype=float)

    columns_float, rows_float = inverse * (x_values, y_values)
    columns = np.floor(columns_float).astype(int)
    rows = np.floor(rows_float).astype(int)

    valid = (
        (columns >= 0)
        & (columns < width)
        & (rows >= 0)
        & (rows < height)
    )

    if int(valid.sum()) != len(inventory):
        raise RuntimeError(
            "Una o más plantas quedaron fuera de la cuadrícula KDE."
        )

    counts = np.zeros((height, width), dtype=np.float64)
    np.add.at(counts, (rows, columns), 1.0)

    return counts


def build_kernel(
    radius_m: float,
    pixel_size_m: float,
    kernel_name: str,
) -> np.ndarray:
    """Construye un kernel bidimensional normalizado."""

    radius_pixels = int(math.ceil(radius_m / pixel_size_m))

    axis = (
        np.arange(-radius_pixels, radius_pixels + 1, dtype=float)
        * pixel_size_m
    )

    x_grid, y_grid = np.meshgrid(axis, axis)
    distance = np.sqrt(x_grid**2 + y_grid**2)
    normalized_distance = distance / radius_m
    inside = normalized_distance <= 1.0

    normalized_name = kernel_name.strip().lower()

    if normalized_name in {"quartic", "biweight", "cuartico", "cuártico"}:
        kernel = np.zeros_like(distance, dtype=np.float64)
        kernel[inside] = (
            1.0 - normalized_distance[inside] ** 2
        ) ** 2

    elif normalized_name in {"gaussian", "gaussiano"}:
        sigma = radius_m / 3.0
        kernel = np.exp(
            -0.5 * (distance / sigma) ** 2
        )
        kernel[~inside] = 0.0

    else:
        raise ValueError(
            "Kernel no compatible. Utilice quartic/biweight o gaussian."
        )

    kernel_sum = float(kernel.sum())

    if not math.isfinite(kernel_sum) or kernel_sum <= 0:
        raise ValueError("No fue posible construir el kernel KDE.")

    kernel /= kernel_sum

    return kernel


def calculate_kde_surfaces(
    point_counts: np.ndarray,
    boundary_mask: np.ndarray,
    kernel: np.ndarray,
    pixel_size_m: float,
    use_edge_correction: bool,
    minimum_kernel_coverage_ratio: float,
) -> dict[str, np.ndarray]:
    """Calcula densidad cruda, cobertura y densidad corregida."""

    distributed_mass = fftconvolve(
        point_counts,
        kernel,
        mode="same",
    )

    kernel_coverage = fftconvolve(
        boundary_mask.astype(np.float64),
        kernel,
        mode="same",
    )

    kernel_coverage = np.clip(
        kernel_coverage,
        0.0,
        1.0,
    )

    pixel_area_m2 = pixel_size_m**2
    raw_density_ha = (
        distributed_mass
        / pixel_area_m2
        * 10000.0
    )

    corrected_density_ha = raw_density_ha.copy()

    if use_edge_correction:
        correctable = (
            boundary_mask
            & (
                kernel_coverage
                >= minimum_kernel_coverage_ratio
            )
        )

        corrected_density_ha[:] = np.nan
        corrected_density_ha[correctable] = (
            raw_density_ha[correctable]
            / kernel_coverage[correctable]
        )

    else:
        corrected_density_ha[~boundary_mask] = np.nan

    raw_density_ha[~boundary_mask] = np.nan
    kernel_coverage[~boundary_mask] = np.nan

    return {
        "raw_density_ha": raw_density_ha,
        "corrected_density_ha": corrected_density_ha,
        "kernel_coverage": kernel_coverage,
    }


def classify_density(
    corrected_density_ha: np.ndarray,
    boundary_mask: np.ndarray,
    kernel_coverage: np.ndarray,
    target_density_plants_ha: float,
    minimum_kernel_coverage_ratio: float,
    thresholds: dict[str, float],
) -> tuple[np.ndarray, np.ndarray]:
    """Clasifica la densidad relativa respecto del objetivo."""

    relative = np.full(
        corrected_density_ha.shape,
        np.nan,
        dtype=np.float64,
    )

    evaluable = (
        boundary_mask
        & np.isfinite(corrected_density_ha)
        & np.isfinite(kernel_coverage)
        & (
            kernel_coverage
            >= minimum_kernel_coverage_ratio
        )
    )

    relative[evaluable] = (
        corrected_density_ha[evaluable]
        / target_density_plants_ha
    )

    classes = np.full(
        corrected_density_ha.shape,
        NODATA_CLASS,
        dtype=np.uint8,
    )

    boundary_not_evaluable = boundary_mask & ~evaluable
    classes[boundary_not_evaluable] = 6

    severe = (
        evaluable
        & (
            relative
            < thresholds["deficit_severe_ratio"]
        )
    )

    moderate = (
        evaluable
        & (
            relative
            >= thresholds["deficit_severe_ratio"]
        )
        & (
            relative
            < thresholds["deficit_moderate_ratio"]
        )
    )

    expected = (
        evaluable
        & (
            relative
            >= thresholds["deficit_moderate_ratio"]
        )
        & (
            relative
            <= thresholds["expected_upper_ratio"]
        )
    )

    elevated = (
        evaluable
        & (
            relative
            > thresholds["expected_upper_ratio"]
        )
        & (
            relative
            <= thresholds["elevated_upper_ratio"]
        )
    )

    very_elevated = (
        evaluable
        & (
            relative
            > thresholds["elevated_upper_ratio"]
        )
    )

    classes[severe] = 1
    classes[moderate] = 2
    classes[expected] = 3
    classes[elevated] = 4
    classes[very_elevated] = 5

    return relative, classes


def build_float_profile(
    width: int,
    height: int,
    transform: rasterio.Affine,
    crs: Any,
) -> dict[str, Any]:
    """Construye el perfil de los rásteres flotantes."""

    return {
        "driver": "GTiff",
        "width": width,
        "height": height,
        "count": 1,
        "dtype": "float32",
        "crs": crs,
        "transform": transform,
        "nodata": NODATA_FLOAT,
        "compress": "DEFLATE",
        "predictor": 3,
        "BIGTIFF": "IF_SAFER",
    }


def write_float_raster_atomic(
    array: np.ndarray,
    output_path: Path,
    profile: dict[str, Any],
    tags: dict[str, str],
) -> None:
    """Escribe un GeoTIFF float32 mediante archivo temporal."""

    temporary_path = output_path.with_suffix(".partial.tif")
    output_array = np.where(
        np.isfinite(array),
        array,
        NODATA_FLOAT,
    ).astype(np.float32)

    try:
        with rasterio.open(
            temporary_path,
            "w",
            **profile,
        ) as destination:
            destination.write(output_array, 1)
            destination.update_tags(**tags)

        temporary_path.replace(output_path)

    finally:
        if temporary_path.exists():
            temporary_path.unlink()


def write_class_raster_atomic(
    classes: np.ndarray,
    output_path: Path,
    width: int,
    height: int,
    transform: rasterio.Affine,
    crs: Any,
    tags: dict[str, str],
) -> None:
    """Escribe el ráster categórico."""

    temporary_path = output_path.with_suffix(".partial.tif")

    profile = {
        "driver": "GTiff",
        "width": width,
        "height": height,
        "count": 1,
        "dtype": "uint8",
        "crs": crs,
        "transform": transform,
        "nodata": NODATA_CLASS,
        "compress": "DEFLATE",
        "predictor": 2,
        "BIGTIFF": "IF_SAFER",
    }

    try:
        with rasterio.open(
            temporary_path,
            "w",
            **profile,
        ) as destination:
            destination.write(classes.astype(np.uint8), 1)
            destination.update_tags(**tags)

        temporary_path.replace(output_path)

    finally:
        if temporary_path.exists():
            temporary_path.unlink()


def build_zone_layer(
    class_raster: np.ndarray,
    transform: rasterio.Affine,
    crs: Any,
    target_density_plants_ha: float,
    thresholds: dict[str, float],
    minimum_zone_area_m2: float,
) -> gpd.GeoDataFrame:
    """Vectoriza y disuelve las clases de densidad KDE."""

    records: list[dict[str, Any]] = []
    valid_mask = class_raster > 0

    for geometry_mapping, value in shapes(
        class_raster.astype(np.int16),
        mask=valid_mask,
        transform=transform,
    ):
        class_code = int(value)

        if class_code not in CLASS_LABELS:
            continue

        geometry = shape(geometry_mapping)

        if geometry.is_empty:
            continue

        records.append(
            {
                "class_code": class_code,
                "density_class": CLASS_LABELS[class_code],
                "target_density_ha": target_density_plants_ha,
                "geometry": geometry,
            }
        )

    if not records:
        return gpd.GeoDataFrame(
            columns=[
                "zone_id",
                "class_code",
                "density_class",
                "target_density_ha",
                "zone_area_m2",
                "management_interpretation",
                "geometry",
            ],
            geometry="geometry",
            crs=crs,
        )

    zones = gpd.GeoDataFrame(
        records,
        geometry="geometry",
        crs=crs,
    )

    dissolved = zones.dissolve(
        by=[
            "class_code",
            "density_class",
            "target_density_ha",
        ],
        as_index=False,
    )

    dissolved = dissolved.explode(
        index_parts=False,
        ignore_index=True,
    )

    dissolved["zone_area_m2"] = dissolved.geometry.area

    keep_mask = (
        dissolved["zone_area_m2"]
        >= minimum_zone_area_m2
    ) | dissolved["class_code"].eq(6)

    dissolved = dissolved.loc[keep_mask].copy()
    dissolved = dissolved.sort_values(
        by=["class_code", "zone_area_m2"],
        ascending=[True, False],
        kind="stable",
    ).reset_index(drop=True)

    dissolved["zone_id"] = [
        f"kde_zone_{index:06d}"
        for index in range(1, len(dissolved) + 1)
    ]

    interpretations = {
        1: "prioridad_para_revisar_deficit_local",
        2: "revisar_posible_deficit",
        3: "densidad_cercana_al_objetivo",
        4: "revisar_posible_alta_densidad",
        5: "prioridad_para_revisar_alta_densidad",
        6: "interpretacion_limitada_por_efecto_de_borde",
    }

    dissolved["management_interpretation"] = (
        dissolved["class_code"].map(interpretations)
    )

    lower_bounds = {
        1: 0.0,
        2: thresholds["deficit_severe_ratio"],
        3: thresholds["deficit_moderate_ratio"],
        4: thresholds["expected_upper_ratio"],
        5: thresholds["elevated_upper_ratio"],
        6: np.nan,
    }

    upper_bounds = {
        1: thresholds["deficit_severe_ratio"],
        2: thresholds["deficit_moderate_ratio"],
        3: thresholds["expected_upper_ratio"],
        4: thresholds["elevated_upper_ratio"],
        5: np.nan,
        6: np.nan,
    }

    dissolved["ratio_lower"] = dissolved["class_code"].map(
        lower_bounds
    )
    dissolved["ratio_upper"] = dissolved["class_code"].map(
        upper_bounds
    )

    return dissolved[
        [
            "zone_id",
            "class_code",
            "density_class",
            "target_density_ha",
            "ratio_lower",
            "ratio_upper",
            "zone_area_m2",
            "management_interpretation",
            "geometry",
        ]
    ]


def write_gpkg_atomic(
    geodataframe: gpd.GeoDataFrame,
    output_path: Path,
    layer_name: str,
) -> None:
    """Escribe un GeoPackage sin dejar archivos parciales."""

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


def write_csv_atomic(
    table: pd.DataFrame,
    output_path: Path,
) -> None:
    """Escribe un CSV mediante archivo temporal."""

    temporary_path = output_path.with_suffix(".partial.csv")

    try:
        table.to_csv(
            temporary_path,
            index=False,
            encoding="utf-8-sig",
            float_format="%.8f",
            quoting=csv.QUOTE_MINIMAL,
        )

        temporary_path.replace(output_path)

    finally:
        if temporary_path.exists():
            temporary_path.unlink()


def verify_raster(
    raster_path: Path,
    expected_crs: Any,
    expected_width: int,
    expected_height: int,
) -> dict[str, Any]:
    """Abre nuevamente un GeoTIFF y valida su estructura."""

    with rasterio.open(raster_path) as source:
        if source.width != expected_width or source.height != expected_height:
            raise RuntimeError(
                "Las dimensiones del GeoTIFF no coinciden con la cuadrícula."
            )

        if source.crs != expected_crs:
            raise RuntimeError("El CRS del GeoTIFF no coincide con el esperado.")

        return {
            "width": int(source.width),
            "height": int(source.height),
            "crs": source.crs.to_string() if source.crs else None,
            "epsg": source.crs.to_epsg() if source.crs else None,
            "resolution": [
                abs(float(source.res[0])),
                abs(float(source.res[1])),
            ],
            "nodata": source.nodata,
            "dtype": source.dtypes[0],
            "bounds": {
                "min_x": float(source.bounds.left),
                "min_y": float(source.bounds.bottom),
                "max_x": float(source.bounds.right),
                "max_y": float(source.bounds.top),
            },
        }


def save_report(
    result: KdeDensityResult,
    output_path: Path,
) -> Path:
    """Guarda el informe JSON."""

    output_path.parent.mkdir(parents=True, exist_ok=True)
    result.report_path = str(output_path)

    with output_path.open("w", encoding="utf-8") as file:
        json.dump(
            asdict(result),
            file,
            ensure_ascii=False,
            indent=4,
        )

    return output_path


def generate_kde_density_map(
    inventory_gpkg: str | Path,
    boundary_gpkg: str | Path,
    target_density_plants_ha: float,
    inventory_layer: str = "plantas_banano_validas",
    boundary_layer: str = "limite_analisis",
    spatial_report_json: str | Path | None = None,
    config_path: str | Path | None = None,
    radius_m: float | None = None,
    pixel_size_m: float | None = None,
    output_dir: str | Path | None = None,
) -> KdeDensityResult:
    """Genera el mapa de calor KDE y sus zonas vectoriales."""

    started_at = datetime.now().isoformat(timespec="seconds")
    start_time = time.perf_counter()

    normalized_inventory = Path(inventory_gpkg).expanduser().resolve(
        strict=False
    )
    normalized_boundary = Path(boundary_gpkg).expanduser().resolve(
        strict=False
    )

    normalized_report = (
        str(
            Path(spatial_report_json).expanduser().resolve(
                strict=False
            )
        )
        if spatial_report_json is not None
        else None
    )

    result = KdeDensityResult(
        success=False,
        started_at=started_at,
        finished_at=None,
        inventory_gpkg=str(normalized_inventory),
        boundary_gpkg=str(normalized_boundary),
        target_density_plants_ha=float(target_density_plants_ha),
        spatial_report_json=normalized_report,
    )

    output_directory = resolve_output_directory(
        normalized_inventory,
        target_density_plants_ha,
        output_dir,
    )
    result.output_directory = str(output_directory)

    corrected_raster_path = (
        output_directory / "densidad_kde_corregida_plantas_ha.tif"
    )
    raw_raster_path = (
        output_directory / "densidad_kde_cruda_plantas_ha.tif"
    )
    relative_raster_path = (
        output_directory / "densidad_kde_relativa.tif"
    )
    class_raster_path = (
        output_directory / "clases_densidad_kde.tif"
    )
    coverage_raster_path = (
        output_directory / "cobertura_kernel_kde.tif"
    )
    zones_gpkg_path = (
        output_directory / "zonas_densidad_kde.gpkg"
    )
    deficit_gpkg_path = (
        output_directory / "zonas_deficit_kde.gpkg"
    )
    high_gpkg_path = (
        output_directory / "zonas_alta_densidad_kde.gpkg"
    )
    summary_csv_path = (
        output_directory / "resumen_mapa_calor_kde.csv"
    )
    report_path = (
        output_directory / "mapa_calor_kde.json"
    )

    generated_paths: list[Path] = []

    try:
        validate_target_density(target_density_plants_ha)

        config_file, config = load_kde_config(config_path)

        (
            resolved_radius_m,
            resolved_pixel_size_m,
            report_file,
            parameter_warnings,
            parameter_sources,
        ) = resolve_radius_and_pixel_size(
            inventory_gpkg=normalized_inventory,
            spatial_report_json=spatial_report_json,
            manual_radius_m=radius_m,
            manual_pixel_size_m=pixel_size_m,
            config=config,
        )

        result.warnings.extend(parameter_warnings)
        result.spatial_report_json = (
            str(report_file)
            if report_file is not None
            else None
        )

        expected_outputs = [
            corrected_raster_path,
            relative_raster_path,
            class_raster_path,
            zones_gpkg_path,
            summary_csv_path,
            report_path,
        ]

        if config["kde_map"]["write_raw_density"]:
            expected_outputs.append(raw_raster_path)

        if config["kde_map"]["write_kernel_coverage"]:
            expected_outputs.append(coverage_raster_path)

        existing_outputs = [
            path for path in expected_outputs if path.exists()
        ]

        if existing_outputs:
            raise FileExistsError(
                "No se sobrescribirán salidas existentes: "
                + ", ".join(str(path) for path in existing_outputs)
            )

        output_directory.mkdir(parents=True, exist_ok=True)

        inventory, boundary, crs = load_inputs(
            inventory_gpkg=normalized_inventory,
            boundary_gpkg=normalized_boundary,
            inventory_layer=inventory_layer,
            boundary_layer=boundary_layer,
        )

        boundary_geometry = boundary.geometry.union_all()
        boundary_area_m2 = float(boundary_geometry.area)

        if not math.isfinite(boundary_area_m2) or boundary_area_m2 <= 0:
            raise ValueError("El área del límite es inválida.")

        transform, width, height = build_analysis_grid(
            boundary_geometry=boundary_geometry,
            radius_m=resolved_radius_m,
            pixel_size_m=resolved_pixel_size_m,
        )

        boundary_mask = build_boundary_mask(
            boundary_geometry=boundary_geometry,
            transform=transform,
            width=width,
            height=height,
        )

        point_counts = rasterize_point_counts(
            inventory=inventory,
            transform=transform,
            width=width,
            height=height,
        )

        kernel = build_kernel(
            radius_m=resolved_radius_m,
            pixel_size_m=resolved_pixel_size_m,
            kernel_name=config["kde"]["kernel"],
        )

        surfaces = calculate_kde_surfaces(
            point_counts=point_counts,
            boundary_mask=boundary_mask,
            kernel=kernel,
            pixel_size_m=resolved_pixel_size_m,
            use_edge_correction=config["kde_map"][
                "use_edge_correction"
            ],
            minimum_kernel_coverage_ratio=config["kde_map"][
                "minimum_kernel_coverage_ratio"
            ],
        )

        relative_density, class_raster = classify_density(
            corrected_density_ha=surfaces["corrected_density_ha"],
            boundary_mask=boundary_mask,
            kernel_coverage=surfaces["kernel_coverage"],
            target_density_plants_ha=target_density_plants_ha,
            minimum_kernel_coverage_ratio=config["kde_map"][
                "minimum_kernel_coverage_ratio"
            ],
            thresholds=config["hexagons"],
        )

        common_tags = {
            "analysis": "continuous_kde_density",
            "target_density_plants_ha": str(target_density_plants_ha),
            "radius_m": str(resolved_radius_m),
            "pixel_size_m": str(resolved_pixel_size_m),
            "kernel": str(config["kde"]["kernel"]),
            "edge_correction": str(
                config["kde_map"]["use_edge_correction"]
            ),
            "technical_status": "requires_field_interpretation",
        }

        float_profile = build_float_profile(
            width=width,
            height=height,
            transform=transform,
            crs=inventory.crs,
        )

        write_float_raster_atomic(
            array=surfaces["corrected_density_ha"],
            output_path=corrected_raster_path,
            profile=float_profile,
            tags={
                **common_tags,
                "units": "plants_per_hectare",
                "surface": "edge_corrected",
            },
        )
        generated_paths.append(corrected_raster_path)
        result.corrected_density_raster = str(corrected_raster_path)

        if config["kde_map"]["write_raw_density"]:
            write_float_raster_atomic(
                array=surfaces["raw_density_ha"],
                output_path=raw_raster_path,
                profile=float_profile,
                tags={
                    **common_tags,
                    "units": "plants_per_hectare",
                    "surface": "raw_uncorrected",
                },
            )
            generated_paths.append(raw_raster_path)
            result.raw_density_raster = str(raw_raster_path)

        write_float_raster_atomic(
            array=relative_density,
            output_path=relative_raster_path,
            profile=float_profile,
            tags={
                **common_tags,
                "units": "ratio_to_target_density",
            },
        )
        generated_paths.append(relative_raster_path)
        result.relative_density_raster = str(relative_raster_path)

        if config["kde_map"]["write_kernel_coverage"]:
            write_float_raster_atomic(
                array=surfaces["kernel_coverage"],
                output_path=coverage_raster_path,
                profile=float_profile,
                tags={
                    **common_tags,
                    "units": "fraction",
                },
            )
            generated_paths.append(coverage_raster_path)
            result.kernel_coverage_raster = str(coverage_raster_path)

        write_class_raster_atomic(
            classes=class_raster,
            output_path=class_raster_path,
            width=width,
            height=height,
            transform=transform,
            crs=inventory.crs,
            tags={
                **common_tags,
                "class_1": CLASS_LABELS[1],
                "class_2": CLASS_LABELS[2],
                "class_3": CLASS_LABELS[3],
                "class_4": CLASS_LABELS[4],
                "class_5": CLASS_LABELS[5],
                "class_6": CLASS_LABELS[6],
            },
        )
        generated_paths.append(class_raster_path)
        result.class_raster = str(class_raster_path)

        zones = build_zone_layer(
            class_raster=class_raster,
            transform=transform,
            crs=inventory.crs,
            target_density_plants_ha=target_density_plants_ha,
            thresholds=config["hexagons"],
            minimum_zone_area_m2=config["kde_map"][
                "minimum_zone_area_m2"
            ],
        )

        if zones.empty:
            raise RuntimeError(
                "No fue posible construir zonas vectoriales KDE."
            )

        write_gpkg_atomic(
            zones,
            zones_gpkg_path,
            "zonas_densidad_kde",
        )
        generated_paths.append(zones_gpkg_path)
        result.zones_gpkg = str(zones_gpkg_path)

        deficit_zones = zones.loc[
            zones["class_code"].isin([1, 2])
        ].copy()

        if not deficit_zones.empty:
            write_gpkg_atomic(
                deficit_zones,
                deficit_gpkg_path,
                "zonas_deficit_kde",
            )
            generated_paths.append(deficit_gpkg_path)
            result.deficit_zones_gpkg = str(deficit_gpkg_path)

        high_zones = zones.loc[
            zones["class_code"].isin([4, 5])
        ].copy()

        if not high_zones.empty:
            write_gpkg_atomic(
                high_zones,
                high_gpkg_path,
                "zonas_alta_densidad_kde",
            )
            generated_paths.append(high_gpkg_path)
            result.high_density_zones_gpkg = str(high_gpkg_path)

        evaluable_mask = np.isin(class_raster, [1, 2, 3, 4, 5])
        corrected_values = surfaces["corrected_density_ha"][evaluable_mask]
        relative_values = relative_density[evaluable_mask]
        pixel_area_m2 = resolved_pixel_size_m**2

        class_area_m2 = {
            CLASS_LABELS[class_code]: round(
                float((class_raster == class_code).sum())
                * pixel_area_m2,
                4,
            )
            for class_code in CLASS_LABELS
        }

        summary_record = {
            "fecha_proceso": datetime.now().isoformat(timespec="seconds"),
            "epsg": crs.to_epsg(),
            "plantas_inventario": int(len(inventory)),
            "area_limite_m2": round(boundary_area_m2, 4),
            "area_limite_ha": round(boundary_area_m2 / 10000.0, 6),
            "densidad_global_plantas_ha": round(
                len(inventory) / (boundary_area_m2 / 10000.0),
                4,
            ),
            "densidad_objetivo_plantas_ha": round(
                target_density_plants_ha,
                4,
            ),
            "radio_kde_m": round(resolved_radius_m, 4),
            "pixel_kde_m": round(resolved_pixel_size_m, 4),
            "kernel": config["kde"]["kernel"],
            "correccion_borde": config["kde_map"][
                "use_edge_correction"
            ],
            "cobertura_kernel_minima": config["kde_map"][
                "minimum_kernel_coverage_ratio"
            ],
            "densidad_kde_minima": (
                round(float(np.nanmin(corrected_values)), 4)
                if corrected_values.size
                else None
            ),
            "densidad_kde_media": (
                round(float(np.nanmean(corrected_values)), 4)
                if corrected_values.size
                else None
            ),
            "densidad_kde_mediana": (
                round(float(np.nanmedian(corrected_values)), 4)
                if corrected_values.size
                else None
            ),
            "densidad_kde_maxima": (
                round(float(np.nanmax(corrected_values)), 4)
                if corrected_values.size
                else None
            ),
            "ratio_objetivo_medio": (
                round(float(np.nanmean(relative_values)), 6)
                if relative_values.size
                else None
            ),
            "area_deficit_severo_m2": class_area_m2[
                "deficit_severo"
            ],
            "area_deficit_moderado_m2": class_area_m2[
                "deficit_moderado"
            ],
            "area_densidad_esperada_m2": class_area_m2[
                "densidad_esperada"
            ],
            "area_densidad_elevada_m2": class_area_m2[
                "densidad_elevada"
            ],
            "area_densidad_muy_elevada_m2": class_area_m2[
                "densidad_muy_elevada"
            ],
            "area_borde_no_evaluable_m2": class_area_m2[
                "borde_no_evaluable"
            ],
        }

        write_csv_atomic(
            pd.DataFrame([summary_record]),
            summary_csv_path,
        )
        generated_paths.append(summary_csv_path)
        result.summary_csv = str(summary_csv_path)

        raster_verification = verify_raster(
            corrected_raster_path,
            inventory.crs,
            width,
            height,
        )

        elapsed_seconds = round(
            time.perf_counter() - start_time,
            3,
        )

        result.metadata = {
            "configuration_file": str(config_file),
            "inventory_layer": inventory_layer,
            "boundary_layer": boundary_layer,
            "plant_count": int(len(inventory)),
            "boundary_area_m2": round(boundary_area_m2, 4),
            "boundary_area_ha": round(boundary_area_m2 / 10000.0, 6),
            "global_density_plants_ha": round(
                len(inventory) / (boundary_area_m2 / 10000.0),
                4,
            ),
            "target_density_plants_ha": target_density_plants_ha,
            "kde_parameters": {
                "radius_m": round(resolved_radius_m, 6),
                "radius_source": parameter_sources["radius"],
                "pixel_size_m": round(resolved_pixel_size_m, 6),
                "pixel_size_source": parameter_sources["pixel_size"],
                "kernel": config["kde"]["kernel"],
                "edge_correction": config["kde_map"][
                    "use_edge_correction"
                ],
                "minimum_kernel_coverage_ratio": config["kde_map"][
                    "minimum_kernel_coverage_ratio"
                ],
            },
            "classification_thresholds": {
                "deficit_severe_ratio": config["hexagons"][
                    "deficit_severe_ratio"
                ],
                "deficit_moderate_ratio": config["hexagons"][
                    "deficit_moderate_ratio"
                ],
                "expected_upper_ratio": config["hexagons"][
                    "expected_upper_ratio"
                ],
                "elevated_upper_ratio": config["hexagons"][
                    "elevated_upper_ratio"
                ],
            },
            "class_area_m2": class_area_m2,
            "zones_total": int(len(zones)),
            "deficit_zones": int(len(deficit_zones)),
            "high_density_zones": int(len(high_zones)),
            "raster_verification": raster_verification,
            "elapsed_seconds": elapsed_seconds,
            "interpretation": {
                "map_role": "complementary_continuous_density_surface",
                "deficit_not_equal_confirmed_replanting": True,
                "high_density_not_equal_confirmed_leaf_overlap": True,
                "technical_field_review_required": True,
            },
        }

        result.warnings.append(
            "El mapa KDE representa una tendencia continua de densidad. "
            "No confirma por sí solo necesidades de resiembra."
        )
        result.warnings.append(
            "Las zonas de alta densidad representan concentración espacial, "
            "no una medición directa del traslape foliar."
        )

        result.success = True

    except Exception as error:
        result.errors.append(
            "No fue posible generar el mapa KDE: "
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

    if output_directory.exists():
        final_report_path = report_path
    else:
        GLOBAL_LOGS_DIRECTORY.mkdir(parents=True, exist_ok=True)
        final_report_path = (
            GLOBAL_LOGS_DIRECTORY
            / (
                "kde_density_error_"
                + datetime.now().strftime("%Y%m%d_%H%M%S")
                + ".json"
            )
        )

    save_report(result, final_report_path)

    return result


def print_kde_density_summary(result: KdeDensityResult) -> None:
    """Muestra el resumen en la terminal."""

    print("=" * 72)
    print("MAPA CONTINUO DE DENSIDAD KDE")
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
        parameters = result.metadata["kde_parameters"]
        print(
            "Plantas analizadas: "
            f"{result.metadata['plant_count']}"
        )
        print(
            "Densidad global: "
            f"{result.metadata['global_density_plants_ha']} plantas/ha"
        )
        print(
            "Radio KDE: "
            f"{parameters['radius_m']} m "
            f"({parameters['radius_source']})"
        )
        print(
            "Tamaño de píxel: "
            f"{parameters['pixel_size_m']} m"
        )
        print(
            "Corrección de borde: "
            f"{parameters['edge_correction']}"
        )
        print(
            "Zonas de déficit: "
            f"{result.metadata['deficit_zones']}"
        )
        print(
            "Zonas de alta densidad: "
            f"{result.metadata['high_density_zones']}"
        )
        print(
            "Tiempo: "
            f"{result.metadata['elapsed_seconds']} segundos"
        )

    if result.corrected_density_raster:
        print(
            "Densidad KDE corregida: "
            f"{result.corrected_density_raster}"
        )

    if result.relative_density_raster:
        print(
            "Densidad relativa: "
            f"{result.relative_density_raster}"
        )

    if result.zones_gpkg:
        print(f"Zonas KDE: {result.zones_gpkg}")

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


def run_kde_density_map(
    inventory_gpkg: str | Path,
    boundary_gpkg: str | Path,
    target_density_plants_ha: float,
    inventory_layer: str = "plantas_banano_validas",
    boundary_layer: str = "limite_analisis",
    spatial_report_json: str | Path | None = None,
    config_path: str | Path | None = None,
    radius_m: float | None = None,
    pixel_size_m: float | None = None,
    output_dir: str | Path | None = None,
) -> int:
    """Ejecuta el mapa KDE desde main.py."""

    result = generate_kde_density_map(
        inventory_gpkg=inventory_gpkg,
        boundary_gpkg=boundary_gpkg,
        target_density_plants_ha=target_density_plants_ha,
        inventory_layer=inventory_layer,
        boundary_layer=boundary_layer,
        spatial_report_json=spatial_report_json,
        config_path=config_path,
        radius_m=radius_m,
        pixel_size_m=pixel_size_m,
        output_dir=output_dir,
    )

    print_kde_density_summary(result)

    return 0 if result.success else 1
