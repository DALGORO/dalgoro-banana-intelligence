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
import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import rasterio
import yaml
from matplotlib.colors import BoundaryNorm, ListedColormap
from matplotlib.lines import Line2D
from matplotlib.patches import Patch
from rasterio.enums import Resampling
from pyproj import CRS


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONFIG_PATH = PROJECT_ROOT / "config" / "cartography.yaml"
DEFAULT_AUTHOR = "Ing. Darwin A. González Romero"


@dataclass
class CartographicPackageResult:
    """Resultado estructurado del paquete cartográfico."""

    success: bool
    started_at: str
    finished_at: str | None
    run_directory: str
    target_density_plants_ha: float
    farm_name: str
    producer: str
    author: str
    output_directory: str | None = None
    maps: list[dict[str, Any]] = field(default_factory=list)
    manifest_path: str | None = None
    index_csv: str | None = None
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


def density_label(value: float) -> str:
    """Convierte una densidad en una etiqueta segura para carpetas."""

    numeric = float(value)

    if numeric.is_integer():
        return str(int(numeric))

    return str(numeric).replace(".", "_")


def load_config(config_path: str | Path | None) -> tuple[Path, dict[str, Any]]:
    """Carga la configuración cartográfica."""

    resolved_path = (
        Path(config_path).expanduser().resolve(strict=False)
        if config_path is not None
        else DEFAULT_CONFIG_PATH
    )

    if not resolved_path.is_file():
        raise FileNotFoundError(
            f"No existe el archivo de configuración cartográfica: {resolved_path}"
        )

    with resolved_path.open("r", encoding="utf-8") as file:
        loaded = yaml.safe_load(file) or {}

    if "cartography" not in loaded:
        raise ValueError(
            "La configuración debe contener la sección 'cartography'."
        )

    return resolved_path, loaded["cartography"]


def find_latest(base_directory: Path, patterns: list[str]) -> Path | None:
    """Busca el archivo más reciente que coincida con uno de los patrones."""

    candidates: list[Path] = []

    for pattern in patterns:
        candidates.extend(
            path for path in base_directory.glob(pattern) if path.is_file()
        )

    if not candidates:
        return None

    return max(candidates, key=lambda path: path.stat().st_mtime)


def discover_inputs(
    run_directory: Path,
    target_density_plants_ha: float,
) -> dict[str, Path | None]:
    """Localiza automáticamente las salidas de las fases anteriores."""

    density_text = density_label(target_density_plants_ha)
    gis_directory = run_directory / "05_gis"

    return {
        "raster": find_latest(
            run_directory,
            [
                "01_recorte/**/*_recortada.tif",
                "01_recorte/**/*.tif",
            ],
        ),
        "inventory": gis_directory / "inventario_banano_validado.gpkg",
        "boundary": gis_directory / "limite_analisis.gpkg",
        "statistics_csv": gis_directory / "estadisticas_banano.csv",
        "hex_density": (
            gis_directory
            / f"densidad_hexagonal_objetivo_{density_text}"
            / "densidad_hexagonal.gpkg"
        ),
        "opportunities": (
            gis_directory
            / f"oportunidades_siembra_{density_text}"
            / "zonas_oportunidad_siembra.gpkg"
        ),
        "priority_candidates": (
            gis_directory
            / f"prioridad_operativa_{density_text}"
            / "candidatos_siembra_priorizados.gpkg"
        ),
        "priority_zones": (
            gis_directory
            / f"prioridad_operativa_{density_text}"
            / "zonas_prioridad_operativa.gpkg"
        ),
        "kde_raster": (
            gis_directory
            / f"mapa_calor_kde_{density_text}"
            / "densidad_kde_corregida_plantas_ha.tif"
        ),
        "kde_zones": (
            gis_directory
            / f"mapa_calor_kde_{density_text}"
            / "zonas_densidad_kde.gpkg"
        ),
    }


def validate_discovered_inputs(paths: dict[str, Path | None]) -> list[str]:
    """Valida las entradas necesarias para generar todos los mapas."""

    required = {
        "raster": "ortofoto recortada",
        "inventory": "inventario validado",
        "boundary": "límite de análisis",
        "hex_density": "densidad hexagonal del escenario",
        "priority_candidates": "candidatos priorizados",
        "priority_zones": "zonas de prioridad operativa",
        "kde_raster": "ráster KDE corregido",
    }

    errors: list[str] = []

    for key, description in required.items():
        path = paths.get(key)

        if path is None or not path.is_file():
            errors.append(
                f"No se encontró {description}: {path or 'ruta no resuelta'}"
            )

    return errors


def load_layer(
    gpkg_path: Path,
    layer_name: str,
    target_crs: Any | None = None,
) -> gpd.GeoDataFrame:
    """Carga una capa y, cuando corresponde, la reproyecta."""

    layer = gpd.read_file(
        gpkg_path,
        layer=layer_name,
        engine="pyogrio",
    )

    if layer.crs is None:
        raise ValueError(
            f"La capa '{layer_name}' no tiene CRS: {gpkg_path}"
        )

    if target_crs is not None and layer.crs != target_crs:
        layer = layer.to_crs(target_crs)

    return layer


def read_raster_preview(
    raster_path: Path,
    max_preview_pixels: int,
    low_percentile: float,
    high_percentile: float,
) -> tuple[np.ndarray, tuple[float, float, float, float], Any]:
    """Lee una vista reducida y realzada de la ortofoto."""

    with rasterio.open(raster_path) as source:
        if source.crs is None:
            raise ValueError("La ortofoto no tiene CRS.")

        scale = max(
            source.width / max_preview_pixels,
            source.height / max_preview_pixels,
            1.0,
        )

        output_width = max(1, int(round(source.width / scale)))
        output_height = max(1, int(round(source.height / scale)))

        if source.count >= 3:
            indexes = [1, 2, 3]
        else:
            indexes = [1]

        raster = source.read(
            indexes=indexes,
            out_shape=(len(indexes), output_height, output_width),
            resampling=Resampling.bilinear,
            masked=True,
        )

        if len(indexes) == 1:
            raster = np.ma.vstack([raster, raster, raster])

        rgb = np.moveaxis(raster.filled(np.nan), 0, -1).astype(np.float32)

        stretched = np.zeros_like(rgb, dtype=np.float32)

        for band_index in range(3):
            band = rgb[:, :, band_index]
            valid = np.isfinite(band)

            if not valid.any():
                continue

            low_value, high_value = np.nanpercentile(
                band[valid],
                [low_percentile, high_percentile],
            )

            if high_value <= low_value:
                high_value = low_value + 1.0

            stretched[:, :, band_index] = np.clip(
                (band - low_value) / (high_value - low_value),
                0.0,
                1.0,
            )

        valid_mask = source.dataset_mask(
            out_shape=(output_height, output_width),
            resampling=Resampling.nearest,
        )

        alpha = np.where(valid_mask > 0, 1.0, 0.0).astype(np.float32)
        rgba = np.dstack([stretched, alpha])

        bounds = source.bounds
        extent = (
            float(bounds.left),
            float(bounds.right),
            float(bounds.bottom),
            float(bounds.top),
        )

        return rgba, extent, source.crs


def read_kde_raster(
    raster_path: Path,
) -> tuple[np.ma.MaskedArray, tuple[float, float, float, float], Any]:
    """Lee el ráster KDE principal."""

    with rasterio.open(raster_path) as source:
        if source.crs is None:
            raise ValueError("El ráster KDE no tiene CRS.")

        array = source.read(1, masked=True)
        bounds = source.bounds

        extent = (
            float(bounds.left),
            float(bounds.right),
            float(bounds.bottom),
            float(bounds.top),
        )

        return array, extent, source.crs


def calculate_map_bounds(
    boundary: gpd.GeoDataFrame,
    margin_ratio: float,
) -> tuple[float, float, float, float]:
    """Calcula la extensión de visualización con margen."""

    min_x, min_y, max_x, max_y = boundary.total_bounds
    width = max_x - min_x
    height = max_y - min_y
    margin = max(width, height) * margin_ratio

    return (
        float(min_x - margin),
        float(max_x + margin),
        float(min_y - margin),
        float(max_y + margin),
    )


def nice_scale_length(map_width: float) -> float:
    """Selecciona una longitud legible para la barra de escala."""

    target = max(map_width * 0.18, 1.0)
    exponent = math.floor(math.log10(target))
    base = target / (10**exponent)

    if base < 2:
        nice_base = 1
    elif base < 5:
        nice_base = 2
    else:
        nice_base = 5

    return float(nice_base * (10**exponent))


def add_north_arrow(ax: plt.Axes) -> None:
    """Agrega una flecha norte sencilla."""

    ax.annotate(
        "N",
        xy=(0.94, 0.93),
        xytext=(0.94, 0.82),
        xycoords="axes fraction",
        ha="center",
        va="center",
        fontsize=12,
        fontweight="bold",
        arrowprops={
            "facecolor": "black",
            "edgecolor": "black",
            "width": 3,
            "headwidth": 11,
        },
        zorder=100,
    )


def add_scale_bar(
    ax: plt.Axes,
    bounds: tuple[float, float, float, float],
) -> None:
    """Agrega una barra de escala en metros."""

    min_x, max_x, min_y, max_y = bounds
    width = max_x - min_x
    height = max_y - min_y
    length = nice_scale_length(width)

    x_start = min_x + width * 0.07
    y_position = min_y + height * 0.06

    ax.plot(
        [x_start, x_start + length],
        [y_position, y_position],
        color="black",
        linewidth=3,
        solid_capstyle="butt",
        zorder=100,
    )

    ax.plot(
        [x_start, x_start],
        [y_position - height * 0.006, y_position + height * 0.006],
        color="black",
        linewidth=1.5,
        zorder=100,
    )

    ax.plot(
        [x_start + length, x_start + length],
        [y_position - height * 0.006, y_position + height * 0.006],
        color="black",
        linewidth=1.5,
        zorder=100,
    )

    label = f"{int(length)} m" if length >= 1 else f"{length:.1f} m"

    ax.text(
        x_start + length / 2,
        y_position + height * 0.012,
        label,
        ha="center",
        va="bottom",
        fontsize=8,
        color="black",
        zorder=100,
    )


def add_footer(
    figure: plt.Figure,
    author: str,
    target_density_plants_ha: float,
    disclaimer: str,
) -> None:
    """Agrega autoría, escenario y advertencia técnica."""

    figure.text(
        0.01,
        0.012,
        (
            f"Elaborado por: {author} — Todos los derechos reservados. "
            f"Escenario: {target_density_plants_ha:g} plantas/ha."
        ),
        ha="left",
        va="bottom",
        fontsize=7,
    )

    figure.text(
        0.99,
        0.012,
        disclaimer,
        ha="right",
        va="bottom",
        fontsize=7,
    )


def create_base_figure(
    raster_rgba: np.ndarray,
    raster_extent: tuple[float, float, float, float],
    boundary: gpd.GeoDataFrame,
    map_bounds: tuple[float, float, float, float],
    title: str,
    subtitle: str,
    config: dict[str, Any],
) -> tuple[plt.Figure, plt.Axes]:
    """Crea la figura base sobre la ortofoto."""

    figure_size = config.get("figure_size_inches", [11.69, 8.27])

    figure, axis = plt.subplots(
        figsize=(float(figure_size[0]), float(figure_size[1]))
    )

    axis.imshow(
        raster_rgba,
        extent=raster_extent,
        origin="upper",
        zorder=1,
    )

    boundary.boundary.plot(
        ax=axis,
        color=config.get("boundary_color", "#111111"),
        linewidth=float(config.get("boundary_linewidth", 1.2)),
        zorder=20,
    )

    axis.set_xlim(map_bounds[0], map_bounds[1])
    axis.set_ylim(map_bounds[2], map_bounds[3])
    axis.set_aspect("equal")
    axis.set_xlabel("Coordenada Este (m)")
    axis.set_ylabel("Coordenada Norte (m)")
    axis.grid(False)

    figure.suptitle(title, fontsize=16, fontweight="bold", y=0.975)
    axis.set_title(subtitle, fontsize=10, pad=8)

    add_north_arrow(axis)
    add_scale_bar(axis, map_bounds)

    return figure, axis


def save_figure_atomic(
    figure: plt.Figure,
    output_path: Path,
    dpi: int,
) -> None:
    """Guarda un mapa sin dejar archivos incompletos."""

    temporary_path = output_path.with_name(
        output_path.stem + ".partial" + output_path.suffix
    )

    try:
        figure.savefig(
            temporary_path,
            dpi=dpi,
            bbox_inches="tight",
            facecolor="white",
        )
        temporary_path.replace(output_path)
    finally:
        plt.close(figure)

        if temporary_path.exists():
            temporary_path.unlink()


def categorical_polygon_plot(
    axis: plt.Axes,
    layer: gpd.GeoDataFrame,
    field_name: str,
    color_mapping: dict[str, str],
    alpha: float,
    edge_color: str,
    line_width: float,
    zorder: int,
) -> list[Patch]:
    """Dibuja polígonos por categorías y retorna la leyenda."""

    legend_items: list[Patch] = []

    for category, color in color_mapping.items():
        subset = layer.loc[layer[field_name].astype(str) == category]

        if subset.empty:
            continue

        subset.plot(
            ax=axis,
            color=color,
            alpha=alpha,
            edgecolor=edge_color,
            linewidth=line_width,
            zorder=zorder,
        )

        legend_items.append(
            Patch(
                facecolor=color,
                edgecolor=edge_color,
                alpha=alpha,
                label=category.replace("_", " ").title(),
            )
        )

    return legend_items


def categorical_point_plot(
    axis: plt.Axes,
    layer: gpd.GeoDataFrame,
    field_name: str,
    color_mapping: dict[str, str],
    marker_size: float,
    zorder: int,
) -> list[Line2D]:
    """Dibuja puntos por categoría."""

    legend_items: list[Line2D] = []

    for category, color in color_mapping.items():
        subset = layer.loc[layer[field_name].astype(str) == category]

        if subset.empty:
            continue

        subset.plot(
            ax=axis,
            color=color,
            markersize=marker_size,
            marker="o",
            edgecolor="black",
            linewidth=0.35,
            zorder=zorder,
        )

        legend_items.append(
            Line2D(
                [0],
                [0],
                marker="o",
                color="none",
                markerfacecolor=color,
                markeredgecolor="black",
                markersize=max(5.0, math.sqrt(marker_size)),
                label=category.replace("_", " ").title(),
            )
        )

    return legend_items


def load_statistics(statistics_csv: Path | None) -> dict[str, Any]:
    """Carga el resumen estadístico cuando está disponible."""

    if statistics_csv is None or not statistics_csv.is_file():
        return {}

    table = pd.read_csv(statistics_csv, encoding="utf-8-sig")

    if table.empty:
        return {}

    return table.iloc[0].to_dict()


def build_subtitle(
    farm_name: str,
    producer: str,
    statistics: dict[str, Any],
    target_density_plants_ha: float,
) -> str:
    """Construye el subtítulo común de los mapas."""

    pieces = [f"Finca: {farm_name}"]

    if producer.strip():
        pieces.append(f"Productor: {producer}")

    plant_count = statistics.get("plantas_dentro_limite")
    area_ha = statistics.get("area_ha")

    if pd.notna(plant_count):
        pieces.append(f"Inventario: {int(float(plant_count))} plantas")

    if pd.notna(area_ha):
        pieces.append(f"Área: {float(area_ha):.3f} ha")

    pieces.append(f"Objetivo: {target_density_plants_ha:g} plantas/ha")

    return " | ".join(pieces)


def write_index_csv(
    maps: list[dict[str, Any]],
    output_path: Path,
) -> None:
    """Guarda el índice del paquete cartográfico."""

    fields = [
        "order",
        "map_id",
        "title",
        "filename",
        "purpose",
    ]

    with output_path.open("w", newline="", encoding="utf-8-sig") as file:
        writer = csv.DictWriter(file, fieldnames=fields)
        writer.writeheader()

        for item in maps:
            writer.writerow({field: item.get(field) for field in fields})


def save_manifest(
    result: CartographicPackageResult,
    output_path: Path,
) -> None:
    """Guarda el manifiesto JSON."""

    result.manifest_path = str(output_path)

    with output_path.open("w", encoding="utf-8") as file:
        json.dump(
            asdict(result),
            file,
            ensure_ascii=False,
            indent=4,
        )


def generate_cartographic_package(
    run_directory: str | Path,
    target_density_plants_ha: float,
    farm_name: str,
    producer: str = "",
    author: str = DEFAULT_AUTHOR,
    config_path: str | Path | None = None,
    output_dir: str | Path | None = None,
) -> CartographicPackageResult:
    """Genera el paquete cartográfico final del escenario seleccionado."""

    started_at = datetime.now().isoformat(timespec="seconds")
    start_time = time.perf_counter()

    normalized_run_directory = Path(run_directory).expanduser().resolve(
        strict=False
    )

    result = CartographicPackageResult(
        success=False,
        started_at=started_at,
        finished_at=None,
        run_directory=str(normalized_run_directory),
        target_density_plants_ha=float(target_density_plants_ha),
        farm_name=str(farm_name).strip() or normalized_run_directory.name,
        producer=str(producer).strip(),
        author=str(author).strip() or DEFAULT_AUTHOR,
    )

    if not normalized_run_directory.is_dir():
        result.errors.append("La carpeta de ejecución no existe.")

    if not math.isfinite(float(target_density_plants_ha)) or (
        float(target_density_plants_ha) <= 0
    ):
        result.errors.append("La densidad objetivo debe ser mayor que cero.")

    density_text = density_label(target_density_plants_ha)

    output_directory = (
        Path(output_dir).expanduser().resolve(strict=False)
        if output_dir is not None
        else normalized_run_directory
        / "06_mapas"
        / f"paquete_cartografico_{density_text}"
    )

    result.output_directory = str(output_directory)

    if output_directory.exists() and any(output_directory.iterdir()):
        result.errors.append(
            "La carpeta de salida ya contiene archivos y no será sobrescrita: "
            f"{output_directory}"
        )

    if result.errors:
        result.finished_at = datetime.now().isoformat(timespec="seconds")
        return result

    generated_paths: list[Path] = []

    try:
        resolved_config_path, cartography_config = load_config(config_path)
        discovered = discover_inputs(
            normalized_run_directory,
            float(target_density_plants_ha),
        )

        result.errors.extend(validate_discovered_inputs(discovered))

        if result.errors:
            raise FileNotFoundError(
                "No están disponibles todas las salidas requeridas de las fases anteriores."
            )

        output_directory.mkdir(parents=True, exist_ok=True)

        raster_rgba, raster_extent, raster_crs = read_raster_preview(
            raster_path=discovered["raster"],  # type: ignore[arg-type]
            max_preview_pixels=int(
                cartography_config.get("max_preview_pixels", 2600)
            ),
            low_percentile=float(
                cartography_config.get("raster_low_percentile", 2.0)
            ),
            high_percentile=float(
                cartography_config.get("raster_high_percentile", 98.0)
            ),
        )

        boundary = load_layer(
            discovered["boundary"],  # type: ignore[arg-type]
            "limite_analisis",
        )

        if CRS.from_user_input(boundary.crs) != CRS.from_user_input(raster_crs):
            raise ValueError(
                "El CRS de la ortofoto y el límite no coincide. "
                "No se generarán mapas potencialmente desplazados."
            )

        inventory = load_layer(
            discovered["inventory"],  # type: ignore[arg-type]
            "plantas_banano_validas",
            target_crs=boundary.crs,
        )

        hex_density = load_layer(
            discovered["hex_density"],  # type: ignore[arg-type]
            "densidad_hexagonal",
            target_crs=boundary.crs,
        )

        priority_candidates = load_layer(
            discovered["priority_candidates"],  # type: ignore[arg-type]
            "candidatos_siembra_priorizados",
            target_crs=boundary.crs,
        )

        priority_zones = load_layer(
            discovered["priority_zones"],  # type: ignore[arg-type]
            "zonas_prioridad_operativa",
            target_crs=boundary.crs,
        )

        opportunities = None

        if discovered["opportunities"] is not None and discovered[
            "opportunities"
        ].is_file():
            opportunities = load_layer(
                discovered["opportunities"],
                "zonas_oportunidad_siembra",
                target_crs=boundary.crs,
            )
        else:
            result.warnings.append(
                "No se encontró la capa de zonas de oportunidad. "
                "El mapa de oportunidades utilizará solamente candidatos priorizados."
            )

        kde_array, kde_extent, kde_crs = read_kde_raster(
            discovered["kde_raster"]  # type: ignore[arg-type]
        )

        if CRS.from_user_input(kde_crs) != CRS.from_user_input(boundary.crs):
            raise ValueError(
                "El CRS del KDE y el límite no coincide."
            )

        kde_zones = None

        if discovered["kde_zones"] is not None and discovered[
            "kde_zones"
        ].is_file():
            kde_zones = load_layer(
                discovered["kde_zones"],
                "zonas_densidad_kde",
                target_crs=boundary.crs,
            )

        statistics = load_statistics(discovered["statistics_csv"])
        subtitle = build_subtitle(
            result.farm_name,
            result.producer,
            statistics,
            float(target_density_plants_ha),
        )

        map_bounds = calculate_map_bounds(
            boundary,
            float(cartography_config.get("map_margin_ratio", 0.035)),
        )

        dpi = int(cartography_config.get("dpi", 220))
        maps: list[dict[str, Any]] = []

        # 1. Inventario
        figure, axis = create_base_figure(
            raster_rgba,
            raster_extent,
            boundary,
            map_bounds,
            "Mapa de inventario de plantas de banano",
            subtitle,
            cartography_config,
        )

        inventory.plot(
            ax=axis,
            color=cartography_config.get("inventory_point_color", "#00A651"),
            markersize=float(
                cartography_config.get("inventory_point_size", 6.0)
            ),
            edgecolor="black",
            linewidth=0.15,
            zorder=30,
        )

        axis.legend(
            handles=[
                Line2D(
                    [0],
                    [0],
                    marker="o",
                    color="none",
                    markerfacecolor=cartography_config.get(
                        "inventory_point_color", "#00A651"
                    ),
                    markeredgecolor="black",
                    markersize=6,
                    label="Planta detectada y validada",
                )
            ],
            loc="upper left",
            framealpha=0.9,
        )

        add_footer(
            figure,
            result.author,
            float(target_density_plants_ha),
            "Inventario automatizado; requiere control técnico de calidad.",
        )

        map_path = output_directory / "01_mapa_inventario.png"
        save_figure_atomic(figure, map_path, dpi)
        generated_paths.append(map_path)
        maps.append(
            {
                "order": 1,
                "map_id": "inventory",
                "title": "Mapa de inventario",
                "filename": map_path.name,
                "purpose": "Ubicación de plantas detectadas, deduplicadas y validadas.",
                "path": str(map_path),
            }
        )

        # 2. Densidad hexagonal
        figure, axis = create_base_figure(
            raster_rgba,
            raster_extent,
            boundary,
            map_bounds,
            "Mapa operativo de densidad por hexágonos",
            subtitle,
            cartography_config,
        )

        density_colors = cartography_config.get(
            "density_class_colors",
            {
                "deficit_severo": "#B2182B",
                "deficit_moderado": "#EF8A62",
                "densidad_esperada": "#66BD63",
                "densidad_elevada": "#3288BD",
                "densidad_muy_elevada": "#762A83",
                "borde_no_evaluable": "#BDBDBD",
            },
        )

        legend_items = categorical_polygon_plot(
            axis,
            hex_density,
            "density_class",
            density_colors,
            alpha=float(cartography_config.get("polygon_alpha", 0.52)),
            edge_color="#3A3A3A",
            line_width=0.25,
            zorder=25,
        )

        if legend_items:
            axis.legend(handles=legend_items, loc="upper left", framealpha=0.9)

        add_footer(
            figure,
            result.author,
            float(target_density_plants_ha),
            "Las clases comparan densidad local con el objetivo del productor.",
        )

        map_path = output_directory / "02_mapa_densidad_hexagonal.png"
        save_figure_atomic(figure, map_path, dpi)
        generated_paths.append(map_path)
        maps.append(
            {
                "order": 2,
                "map_id": "hex_density",
                "title": "Densidad por hexágonos",
                "filename": map_path.name,
                "purpose": "Gestión por unidades de 100 m² y detección de déficit o concentración.",
                "path": str(map_path),
            }
        )

        # 3. KDE
        figure, axis = create_base_figure(
            raster_rgba,
            raster_extent,
            boundary,
            map_bounds,
            "Mapa continuo de densidad KDE",
            subtitle,
            cartography_config,
        )

        target = float(target_density_plants_ha)
        valid_kde = kde_array.compressed()
        observed_max = float(valid_kde.max()) if valid_kde.size else target * 1.5
        upper_limit = max(observed_max, target * 1.5)

        kde_boundaries = [
            0.0,
            target * 0.70,
            target * 0.90,
            target * 1.10,
            target * 1.25,
            upper_limit + 1e-6,
        ]

        kde_colors = [
            density_colors["deficit_severo"],
            density_colors["deficit_moderado"],
            density_colors["densidad_esperada"],
            density_colors["densidad_elevada"],
            density_colors["densidad_muy_elevada"],
        ]

        colormap = ListedColormap(kde_colors)
        normalization = BoundaryNorm(kde_boundaries, colormap.N)

        axis.imshow(
            kde_array,
            extent=kde_extent,
            origin="upper",
            cmap=colormap,
            norm=normalization,
            alpha=float(cartography_config.get("kde_alpha", 0.58)),
            zorder=22,
        )

        kde_legend = [
            Patch(
                facecolor=color,
                edgecolor="#333333",
                alpha=float(cartography_config.get("kde_alpha", 0.58)),
                label=label,
            )
            for color, label in zip(
                kde_colors,
                [
                    "Déficit severo (<70 %)",
                    "Déficit moderado (70–90 %)",
                    "Densidad esperada (90–110 %)",
                    "Densidad elevada (110–125 %)",
                    "Densidad muy elevada (>125 %)",
                ],
                strict=True,
            )
        ]

        axis.legend(handles=kde_legend, loc="upper left", framealpha=0.9)

        add_footer(
            figure,
            result.author,
            float(target_density_plants_ha),
            "KDE corregido por borde; representa tendencia, no resiembra confirmada.",
        )

        map_path = output_directory / "03_mapa_densidad_kde.png"
        save_figure_atomic(figure, map_path, dpi)
        generated_paths.append(map_path)
        maps.append(
            {
                "order": 3,
                "map_id": "kde_density",
                "title": "Densidad continua KDE",
                "filename": map_path.name,
                "purpose": "Visualización continua de tendencias de déficit y concentración.",
                "path": str(map_path),
            }
        )

        # 4. Oportunidades geométricas
        figure, axis = create_base_figure(
            raster_rgba,
            raster_extent,
            boundary,
            map_bounds,
            "Oportunidades geométricas de siembra",
            subtitle,
            cartography_config,
        )

        handles: list[Any] = []

        if opportunities is not None and not opportunities.empty:
            opportunities.boundary.plot(
                ax=axis,
                color=cartography_config.get(
                    "opportunity_outline_color", "#F46D43"
                ),
                linewidth=0.8,
                linestyle="--",
                zorder=24,
            )
            handles.append(
                Line2D(
                    [0],
                    [0],
                    color=cartography_config.get(
                        "opportunity_outline_color", "#F46D43"
                    ),
                    linestyle="--",
                    linewidth=1.5,
                    label="Zona geométrica de oportunidad",
                )
            )

        priority_colors = cartography_config.get(
            "priority_class_colors",
            {
                "prioridad_alta": "#D73027",
                "prioridad_media": "#FDAE61",
                "prioridad_baja": "#FEE08B",
                "revision_borde_no_evaluable": "#969696",
                "descartado_por_exclusion": "#000000",
            },
        )

        handles.extend(
            categorical_point_plot(
                axis,
                priority_candidates,
                "operational_priority_class",
                priority_colors,
                marker_size=float(
                    cartography_config.get("candidate_point_size", 20.0)
                ),
                zorder=35,
            )
        )

        if handles:
            axis.legend(handles=handles, loc="upper left", framealpha=0.9)

        add_footer(
            figure,
            result.author,
            float(target_density_plants_ha),
            "Candidatos geométricos sujetos a inspección de vías, canales e infraestructura.",
        )

        map_path = output_directory / "04_mapa_oportunidades_siembra.png"
        save_figure_atomic(figure, map_path, dpi)
        generated_paths.append(map_path)
        maps.append(
            {
                "order": 4,
                "map_id": "planting_opportunities",
                "title": "Oportunidades de siembra",
                "filename": map_path.name,
                "purpose": "Ubicación de espacios geométricos y candidatos para inspección técnica.",
                "path": str(map_path),
            }
        )

        # 5. Prioridad operativa
        figure, axis = create_base_figure(
            raster_rgba,
            raster_extent,
            boundary,
            map_bounds,
            "Priorización operativa para inspección de campo",
            subtitle,
            cartography_config,
        )

        zone_colors = cartography_config.get(
            "operational_zone_colors",
            {
                "prioridad_alta": "#D73027",
                "prioridad_media": "#FDAE61",
                "prioridad_baja": "#FEE08B",
                "borde_no_evaluable": "#BDBDBD",
                "sin_candidatos": "#D9EF8B",
            },
        )

        zone_legend = categorical_polygon_plot(
            axis,
            priority_zones,
            "operational_zone_class",
            zone_colors,
            alpha=float(cartography_config.get("priority_zone_alpha", 0.42)),
            edge_color="#3A3A3A",
            line_width=0.25,
            zorder=24,
        )

        point_legend = categorical_point_plot(
            axis,
            priority_candidates,
            "operational_priority_class",
            priority_colors,
            marker_size=float(
                cartography_config.get("candidate_point_size", 20.0)
            ),
            zorder=35,
        )

        axis.legend(
            handles=[*zone_legend, *point_legend],
            loc="upper left",
            framealpha=0.9,
        )

        add_footer(
            figure,
            result.author,
            float(target_density_plants_ha),
            "La prioridad organiza la inspección; la decisión final corresponde al técnico.",
        )

        map_path = output_directory / "05_mapa_prioridad_operativa.png"
        save_figure_atomic(figure, map_path, dpi)
        generated_paths.append(map_path)
        maps.append(
            {
                "order": 5,
                "map_id": "operational_priority",
                "title": "Prioridad operativa",
                "filename": map_path.name,
                "purpose": "Organización de inspecciones según déficit, espacio y seguridad de borde.",
                "path": str(map_path),
            }
        )

        # 6. Riesgo de concentración espacial elevada
        figure, axis = create_base_figure(
            raster_rgba,
            raster_extent,
            boundary,
            map_bounds,
            "Riesgo de concentración espacial elevada",
            subtitle,
            cartography_config,
        )

        high_hex = hex_density.loc[
            hex_density["density_class"].astype(str).isin(
                ["densidad_elevada", "densidad_muy_elevada"]
            )
        ].copy()

        high_handles: list[Any] = []

        if not high_hex.empty:
            high_handles.extend(
                categorical_polygon_plot(
                    axis,
                    high_hex,
                    "density_class",
                    density_colors,
                    alpha=float(
                        cartography_config.get("high_density_alpha", 0.52)
                    ),
                    edge_color="#3A3A3A",
                    line_width=0.3,
                    zorder=25,
                )
            )

        if kde_zones is not None and "density_class" in kde_zones.columns:
            high_kde = kde_zones.loc[
                kde_zones["density_class"].astype(str).isin(
                    ["densidad_elevada", "densidad_muy_elevada"]
                )
            ].copy()

            if not high_kde.empty:
                high_kde.boundary.plot(
                    ax=axis,
                    color="#542788",
                    linewidth=0.9,
                    zorder=28,
                )
                high_handles.append(
                    Line2D(
                        [0],
                        [0],
                        color="#542788",
                        linewidth=1.5,
                        label="Contorno KDE de alta densidad",
                    )
                )

        inventory.plot(
            ax=axis,
            color="#1B7837",
            markersize=3.5,
            zorder=32,
        )

        high_handles.append(
            Line2D(
                [0],
                [0],
                marker="o",
                color="none",
                markerfacecolor="#1B7837",
                markersize=5,
                label="Planta inventariada",
            )
        )

        if high_handles:
            axis.legend(handles=high_handles, loc="upper left", framealpha=0.9)

        add_footer(
            figure,
            result.author,
            float(target_density_plants_ha),
            "Indica concentración espacial; no confirma traslape foliar.",
        )

        map_path = output_directory / "06_mapa_riesgo_alta_densidad.png"
        save_figure_atomic(figure, map_path, dpi)
        generated_paths.append(map_path)
        maps.append(
            {
                "order": 6,
                "map_id": "high_density_risk",
                "title": "Riesgo de alta densidad",
                "filename": map_path.name,
                "purpose": "Identificación de sectores con concentración espacial superior al objetivo.",
                "path": str(map_path),
            }
        )

        index_path = output_directory / "indice_mapas.csv"
        write_index_csv(maps, index_path)
        generated_paths.append(index_path)

        result.maps = maps
        result.index_csv = str(index_path)

        elapsed_seconds = round(time.perf_counter() - start_time, 3)

        result.metadata = {
            "config_path": str(resolved_config_path),
            "discovered_inputs": {
                key: str(value) if value is not None else None
                for key, value in discovered.items()
            },
            "map_count": len(maps),
            "dpi": dpi,
            "crs": boundary.crs.to_string(),
            "epsg": boundary.crs.to_epsg(),
            "inventory_plants": int(len(inventory)),
            "hexagons": int(len(hex_density)),
            "priority_candidates": int(len(priority_candidates)),
            "priority_zones": int(len(priority_zones)),
            "elapsed_seconds": elapsed_seconds,
            "qgis_required": False,
        }

        result.success = True

    except Exception as error:
        result.errors.append(
            "No fue posible generar el paquete cartográfico: "
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
        manifest_path = output_directory / "manifiesto_paquete_cartografico.json"
        save_manifest(result, manifest_path)

    return result


def print_cartographic_package_summary(
    result: CartographicPackageResult,
) -> None:
    """Muestra el resumen del proceso."""

    print("=" * 72)
    print("GENERACIÓN DEL PAQUETE CARTOGRÁFICO FINAL")
    print("=" * 72)
    print(f"Ejecución: {result.run_directory}")
    print(f"Finca: {result.farm_name}")
    print(
        "Densidad objetivo: "
        f"{result.target_density_plants_ha:g} plantas/ha"
    )
    print(
        "Estado: "
        f"{'COMPLETADO' if result.success else 'ERROR'}"
    )

    if result.metadata:
        print(f"Mapas generados: {result.metadata['map_count']}")
        print(f"CRS: {result.metadata['crs']}")
        print(f"Tiempo: {result.metadata['elapsed_seconds']} segundos")

    for map_item in result.maps:
        print(f"  - {map_item['title']}: {map_item['path']}")

    if result.index_csv:
        print(f"Índice: {result.index_csv}")

    if result.errors:
        print("\nERRORES:")
        for error in result.errors:
            print(f"  - {error}")

    if result.warnings:
        print("\nADVERTENCIAS:")
        for warning in result.warnings:
            print(f"  - {warning}")

    if result.manifest_path:
        print(f"\nManifiesto: {result.manifest_path}")

    print("=" * 72)


def run_cartographic_package(
    run_directory: str | Path,
    target_density_plants_ha: float,
    farm_name: str,
    producer: str = "",
    author: str = DEFAULT_AUTHOR,
    config_path: str | Path | None = None,
    output_dir: str | Path | None = None,
) -> int:
    """Ejecuta el paquete cartográfico desde main.py."""

    result = generate_cartographic_package(
        run_directory=run_directory,
        target_density_plants_ha=target_density_plants_ha,
        farm_name=farm_name,
        producer=producer,
        author=author,
        config_path=config_path,
        output_dir=output_dir,
    )

    print_cartographic_package_summary(result)

    return 0 if result.success else 1
