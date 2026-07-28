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


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONFIG_PATH = PROJECT_ROOT / "config" / "spatial_analysis.yaml"
GLOBAL_LOGS_DIRECTORY = PROJECT_ROOT / "logs"

REQUIRED_HEX_COLUMNS = {
    "hex_id",
    "plant_count",
    "clipped_area_m2",
    "coverage_ratio",
    "plants_per_ha",
    "reference_plants_ha",
    "density_ratio",
    "density_class",
    "is_evaluable",
}

REQUIRED_CANDIDATE_COLUMNS = {
    "candidate_id",
    "opportunity_id",
    "target_density_ha",
    "target_area_m2",
    "target_spacing_m",
    "nearest_existing_m",
    "local_density_ratio",
    "distance_boundary_m",
    "boundary_risk",
    "spatial_score",
    "spatial_score_class",
}

REQUIRED_OPPORTUNITY_COLUMNS = {
    "opportunity_id",
    "open_core_area_m2",
    "distance_boundary_m",
    "boundary_risk",
}

DEFAULT_PRIORITY_CONFIG: dict[str, Any] = {
    "weights": {
        "candidate_spatial_score": 0.45,
        "hex_density_deficit": 0.35,
        "opportunity_area": 0.10,
        "boundary_safety": 0.10,
    },
    "high_priority_score": 0.75,
    "medium_priority_score": 0.55,
    "full_density_deficit_ratio": 0.50,
    "minimum_actionable_density_ratio": 0.90,
    "opportunity_area_full_score_factor": 2.00,
    "maximum_reference_difference_percent": 1.00,
    "use_only_evaluable_hexagons": True,
}


@dataclass
class OperationalPriorityResult:
    """Resultado de la priorización de oportunidades de siembra."""

    success: bool
    started_at: str
    finished_at: str | None
    hex_density_gpkg: str
    candidates_gpkg: str
    opportunities_gpkg: str
    target_density_plants_ha: float
    output_directory: str | None = None
    prioritized_candidates_csv: str | None = None
    prioritized_candidates_gpkg: str | None = None
    priority_zones_gpkg: str | None = None
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
    candidates_gpkg: Path,
    target_density_plants_ha: float,
    output_dir: str | Path | None,
) -> Path:
    """Determina la carpeta de salida sin depender de una ruta fija."""

    if output_dir is not None:
        return Path(output_dir).expanduser().resolve(strict=False)

    label = density_label(target_density_plants_ha)
    candidate_parent = candidates_gpkg.parent

    if candidate_parent.name.startswith("oportunidades_siembra_"):
        return candidate_parent.parent / f"prioridad_operativa_{label}"

    return candidate_parent / f"prioridad_operativa_{label}"


def deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    """Combina diccionarios anidados sin alterar los valores originales."""

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


def load_priority_config(
    config_path: str | Path | None,
) -> tuple[Path, dict[str, Any]]:
    """Carga y valida la configuración operativa."""

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

    configured = full_config.get("operational_priority", {})
    merged = deep_merge(DEFAULT_PRIORITY_CONFIG, configured)

    weights = merged.get("weights", {})
    required_weights = set(DEFAULT_PRIORITY_CONFIG["weights"])
    missing_weights = sorted(required_weights - set(weights))

    if missing_weights:
        raise ValueError(
            "Faltan ponderaciones en operational_priority.weights: "
            + ", ".join(missing_weights)
        )

    weight_values = {
        key: float(weights[key])
        for key in required_weights
    }

    if any(not math.isfinite(value) or value < 0 for value in weight_values.values()):
        raise ValueError(
            "Las ponderaciones deben ser números finitos y no negativos."
        )

    weight_sum = sum(weight_values.values())

    if weight_sum <= 0:
        raise ValueError("La suma de ponderaciones debe ser mayor que cero.")

    merged["weights"] = {
        key: value / weight_sum
        for key, value in weight_values.items()
    }

    for key in (
        "high_priority_score",
        "medium_priority_score",
        "full_density_deficit_ratio",
        "minimum_actionable_density_ratio",
        "opportunity_area_full_score_factor",
        "maximum_reference_difference_percent",
    ):
        value = float(merged[key])

        if not math.isfinite(value):
            raise ValueError(f"El parámetro {key} debe ser finito.")

        merged[key] = value

    if not 0 <= merged["medium_priority_score"] <= 1:
        raise ValueError("medium_priority_score debe estar entre 0 y 1.")

    if not 0 <= merged["high_priority_score"] <= 1:
        raise ValueError("high_priority_score debe estar entre 0 y 1.")

    if merged["medium_priority_score"] >= merged["high_priority_score"]:
        raise ValueError(
            "medium_priority_score debe ser menor que high_priority_score."
        )

    if not 0 < merged["full_density_deficit_ratio"] < 1:
        raise ValueError(
            "full_density_deficit_ratio debe ser mayor que 0 y menor que 1."
        )

    if not 0 < merged["minimum_actionable_density_ratio"] <= 1:
        raise ValueError(
            "minimum_actionable_density_ratio debe estar entre 0 y 1."
        )

    if merged["opportunity_area_full_score_factor"] <= 0:
        raise ValueError(
            "opportunity_area_full_score_factor debe ser mayor que cero."
        )

    if merged["maximum_reference_difference_percent"] < 0:
        raise ValueError(
            "maximum_reference_difference_percent no puede ser negativo."
        )

    merged["use_only_evaluable_hexagons"] = bool(
        merged["use_only_evaluable_hexagons"]
    )

    return normalized_path, merged


def validate_layer_columns(
    layer: gpd.GeoDataFrame,
    required_columns: set[str],
    label: str,
) -> None:
    """Comprueba las columnas y geometrías mínimas de una capa."""

    missing = sorted(required_columns - set(layer.columns))

    if missing:
        raise ValueError(
            f"La capa {label} no contiene las columnas: " + ", ".join(missing)
        )

    if layer.empty:
        raise ValueError(f"La capa {label} está vacía.")

    if layer.crs is None:
        raise ValueError(f"La capa {label} no tiene CRS.")

    crs = CRS.from_user_input(layer.crs)

    if not crs.is_projected:
        raise ValueError(f"La capa {label} debe utilizar un CRS proyectado.")

    unit_names = [
        axis.unit_name.lower()
        for axis in crs.axis_info
        if axis.unit_name
    ]

    if not unit_names or not all(
        "metre" in unit_name or "meter" in unit_name
        for unit_name in unit_names
    ):
        raise ValueError(f"La capa {label} debe utilizar metros.")

    if layer.geometry.isna().any() or layer.geometry.is_empty.any():
        raise ValueError(f"La capa {label} contiene geometrías vacías.")

    if not layer.geometry.is_valid.all():
        raise ValueError(f"La capa {label} contiene geometrías inválidas.")


def normalize_bool_series(series: pd.Series) -> pd.Series:
    """Normaliza valores booleanos provenientes de CSV o GeoPackage."""

    if pd.api.types.is_bool_dtype(series):
        return series.fillna(False).astype(bool)

    normalized = (
        series.astype("string")
        .str.strip()
        .str.lower()
        .map(
            {
                "true": True,
                "1": True,
                "yes": True,
                "si": True,
                "sí": True,
                "false": False,
                "0": False,
                "no": False,
            }
        )
    )

    return normalized.fillna(False).astype(bool)


def normalize_numeric_columns(
    table: gpd.GeoDataFrame,
    columns: list[str],
    label: str,
) -> gpd.GeoDataFrame:
    """Convierte columnas a número y rechaza valores inválidos."""

    normalized = table.copy()

    for column in columns:
        normalized[column] = pd.to_numeric(
            normalized[column],
            errors="coerce",
        )

        invalid = normalized[column].isna() | ~np.isfinite(normalized[column])

        if invalid.any():
            positions = [int(index) for index in normalized.index[invalid][:20]]
            raise ValueError(
                f"La capa {label} contiene valores no numéricos o no finitos "
                f"en {column}. Índices: {positions}."
            )

    return normalized


def read_inputs(
    hex_density_gpkg: Path,
    candidates_gpkg: Path,
    opportunities_gpkg: Path,
    hex_layer: str,
    candidates_layer: str,
    opportunities_layer: str,
) -> tuple[gpd.GeoDataFrame, gpd.GeoDataFrame, gpd.GeoDataFrame]:
    """Lee y normaliza las tres capas principales."""

    hexagons = gpd.read_file(
        hex_density_gpkg,
        layer=hex_layer,
        engine="pyogrio",
    )

    candidates = gpd.read_file(
        candidates_gpkg,
        layer=candidates_layer,
        engine="pyogrio",
    )

    opportunities = gpd.read_file(
        opportunities_gpkg,
        layer=opportunities_layer,
        engine="pyogrio",
    )

    validate_layer_columns(hexagons, REQUIRED_HEX_COLUMNS, "hexágonos")
    validate_layer_columns(candidates, REQUIRED_CANDIDATE_COLUMNS, "candidatos")
    validate_layer_columns(
        opportunities,
        REQUIRED_OPPORTUNITY_COLUMNS,
        "oportunidades",
    )

    hexagons = normalize_numeric_columns(
        hexagons,
        [
            "plant_count",
            "clipped_area_m2",
            "coverage_ratio",
            "plants_per_ha",
            "reference_plants_ha",
            "density_ratio",
        ],
        "hexágonos",
    )

    candidates = normalize_numeric_columns(
        candidates,
        [
            "target_density_ha",
            "target_area_m2",
            "target_spacing_m",
            "nearest_existing_m",
            "local_density_ratio",
            "distance_boundary_m",
            "spatial_score",
        ],
        "candidatos",
    )

    opportunities = normalize_numeric_columns(
        opportunities,
        [
            "open_core_area_m2",
            "distance_boundary_m",
        ],
        "oportunidades",
    )

    hexagons["is_evaluable"] = normalize_bool_series(hexagons["is_evaluable"])
    candidates["boundary_risk"] = normalize_bool_series(
        candidates["boundary_risk"]
    )
    opportunities["boundary_risk"] = normalize_bool_series(
        opportunities["boundary_risk"]
    )

    if candidates.crs != hexagons.crs:
        candidates = candidates.to_crs(hexagons.crs)

    if opportunities.crs != hexagons.crs:
        opportunities = opportunities.to_crs(hexagons.crs)

    return hexagons, candidates, opportunities


def validate_target_density_consistency(
    hexagons: gpd.GeoDataFrame,
    candidates: gpd.GeoDataFrame,
    target_density_plants_ha: float,
    maximum_difference_percent: float,
) -> dict[str, float]:
    """Comprueba que todas las capas se generaron para el mismo escenario."""

    if (
        not math.isfinite(target_density_plants_ha)
        or target_density_plants_ha <= 0
    ):
        raise ValueError("La densidad objetivo debe ser mayor que cero.")

    candidate_values = sorted(
        {
            round(float(value), 6)
            for value in candidates["target_density_ha"].dropna()
        }
    )

    if len(candidate_values) != 1:
        raise ValueError(
            "La capa de candidatos debe contener una única densidad objetivo. "
            f"Valores: {candidate_values}."
        )

    candidate_density = candidate_values[0]
    hex_reference_values = sorted(
        {
            round(float(value), 6)
            for value in hexagons["reference_plants_ha"].dropna()
        }
    )

    if len(hex_reference_values) != 1:
        raise ValueError(
            "La capa hexagonal debe contener una única densidad de referencia. "
            f"Valores: {hex_reference_values}."
        )

    hex_reference_density = hex_reference_values[0]

    def percent_difference(value: float) -> float:
        return abs(value - target_density_plants_ha) / target_density_plants_ha * 100.0

    candidate_difference = percent_difference(candidate_density)
    hex_difference = percent_difference(hex_reference_density)

    if candidate_difference > maximum_difference_percent:
        raise ValueError(
            "La densidad de los candidatos no coincide con la densidad objetivo. "
            f"Candidatos: {candidate_density}; solicitada: "
            f"{target_density_plants_ha}."
        )

    if hex_difference > maximum_difference_percent:
        raise ValueError(
            "La densidad de referencia del mapa hexagonal no coincide con el "
            "escenario del productor. Genere nuevamente el mapa hexagonal con "
            f"--reference-density {target_density_plants_ha}. "
            f"Referencia actual: {hex_reference_density}."
        )

    return {
        "requested_target_density": float(target_density_plants_ha),
        "candidate_target_density": float(candidate_density),
        "hex_reference_density": float(hex_reference_density),
        "candidate_difference_percent": round(candidate_difference, 6),
        "hex_difference_percent": round(hex_difference, 6),
    }


def read_exclusions(
    exclusions_gpkg: str | Path | None,
    exclusions_layer: str | None,
    target_crs: Any,
) -> tuple[gpd.GeoDataFrame | None, Any | None]:
    """Lee una capa opcional de vías, canales o infraestructura."""

    if exclusions_gpkg is None and exclusions_layer is None:
        return None, None

    if exclusions_gpkg is None or not exclusions_layer:
        raise ValueError(
            "Debe proporcionar juntos --exclusions-gpkg y --exclusions-layer."
        )

    exclusions_path = Path(exclusions_gpkg).expanduser().resolve(strict=False)

    if not exclusions_path.is_file():
        raise FileNotFoundError(
            f"No existe el GeoPackage de exclusiones: {exclusions_path}"
        )

    exclusions = gpd.read_file(
        exclusions_path,
        layer=exclusions_layer,
        engine="pyogrio",
    )

    if exclusions.empty:
        raise ValueError("La capa de exclusiones está vacía.")

    if exclusions.crs is None:
        raise ValueError("La capa de exclusiones no tiene CRS.")

    if exclusions.crs != target_crs:
        exclusions = exclusions.to_crs(target_crs)

    if exclusions.geometry.isna().any() or exclusions.geometry.is_empty.any():
        raise ValueError("La capa de exclusiones contiene geometrías vacías.")

    if not exclusions.geometry.is_valid.all():
        exclusions = exclusions.copy()
        exclusions["geometry"] = exclusions.geometry.make_valid()

    exclusion_union = exclusions.geometry.union_all()

    if exclusion_union.is_empty:
        raise ValueError("La unión de exclusiones está vacía.")

    return exclusions, exclusion_union


def assign_hexagon_context(
    candidates: gpd.GeoDataFrame,
    hexagons: gpd.GeoDataFrame,
) -> gpd.GeoDataFrame:
    """Asigna a cada candidato el contexto del hexágono que lo contiene."""

    hex_fields = [
        "hex_id",
        "plant_count",
        "clipped_area_m2",
        "coverage_ratio",
        "plants_per_ha",
        "reference_plants_ha",
        "density_ratio",
        "density_class",
        "is_evaluable",
        "management_action",
        "priority_level",
    ]

    hex_fields = [field for field in hex_fields if field in hexagons.columns]

    joined = gpd.sjoin(
        candidates,
        hexagons[[*hex_fields, "geometry"]],
        how="left",
        predicate="intersects",
    )

    joined["_evaluable_sort"] = (
        joined.get("is_evaluable", False)
        .fillna(False)
        .astype(bool)
        .astype(int)
    )

    joined["_coverage_sort"] = pd.to_numeric(
        joined.get("coverage_ratio", 0.0),
        errors="coerce",
    ).fillna(0.0)

    joined = (
        joined.sort_values(
            by=[
                "candidate_id",
                "_evaluable_sort",
                "_coverage_sort",
                "hex_id",
            ],
            ascending=[True, False, False, True],
            kind="stable",
        )
        .drop_duplicates(subset="candidate_id", keep="first")
        .drop(
            columns=[
                "index_right",
                "_evaluable_sort",
                "_coverage_sort",
            ],
            errors="ignore",
        )
        .reset_index(drop=True)
    )

    return gpd.GeoDataFrame(joined, geometry="geometry", crs=candidates.crs)


def attach_opportunity_context(
    candidates: gpd.GeoDataFrame,
    opportunities: gpd.GeoDataFrame,
) -> gpd.GeoDataFrame:
    """Incorpora área y riesgo del polígono de oportunidad."""

    opportunity_table = pd.DataFrame(
        opportunities.drop(columns="geometry", errors="ignore")
    )

    selected_columns = [
        column
        for column in (
            "opportunity_id",
            "open_core_area_m2",
            "distance_boundary_m",
            "boundary_risk",
            "candidate_count",
            "land_use_status",
        )
        if column in opportunity_table.columns
    ]

    opportunity_table = opportunity_table[selected_columns].copy()

    rename_map = {
        "distance_boundary_m": "opportunity_distance_boundary_m",
        "boundary_risk": "opportunity_boundary_risk",
        "land_use_status": "opportunity_land_use_status",
    }

    opportunity_table = opportunity_table.rename(columns=rename_map)

    merged = candidates.merge(
        opportunity_table,
        how="left",
        on="opportunity_id",
        validate="many_to_one",
    )

    return gpd.GeoDataFrame(merged, geometry="geometry", crs=candidates.crs)


def clamp_array(values: pd.Series | np.ndarray, minimum: float, maximum: float) -> np.ndarray:
    """Limita un arreglo numérico a un intervalo."""

    return np.clip(np.asarray(values, dtype=float), minimum, maximum)


def calculate_candidate_priorities(
    candidates: gpd.GeoDataFrame,
    config: dict[str, Any],
    exclusion_union: Any | None,
) -> gpd.GeoDataFrame:
    """Calcula el puntaje operativo y conserva la decisión técnica pendiente."""

    prioritized = candidates.copy()
    weights = config["weights"]

    spatial_component = clamp_array(prioritized["spatial_score"], 0.0, 1.0)

    density_ratio = pd.to_numeric(
        prioritized["density_ratio"],
        errors="coerce",
    )

    local_density_ratio = pd.to_numeric(
        prioritized["local_density_ratio"],
        errors="coerce",
    ).fillna(1.0)

    deficit_denominator = max(
        1.0 - config["full_density_deficit_ratio"],
        0.01,
    )

    density_component = clamp_array(
        (1.0 - density_ratio.fillna(1.0)) / deficit_denominator,
        0.0,
        1.0,
    )

    open_area = pd.to_numeric(
        prioritized["open_core_area_m2"],
        errors="coerce",
    ).fillna(0.0)

    target_area = pd.to_numeric(
        prioritized["target_area_m2"],
        errors="coerce",
    ).replace(0.0, np.nan)

    opportunity_component = clamp_array(
        open_area
        / (
            target_area
            * config["opportunity_area_full_score_factor"]
        ),
        0.0,
        1.0,
    )

    boundary_component = clamp_array(
        pd.to_numeric(
            prioritized["distance_boundary_m"],
            errors="coerce",
        ).fillna(0.0)
        / pd.to_numeric(
            prioritized["target_spacing_m"],
            errors="coerce",
        ).replace(0.0, np.nan).fillna(1.0),
        0.0,
        1.0,
    )

    score = (
        weights["candidate_spatial_score"] * spatial_component
        + weights["hex_density_deficit"] * density_component
        + weights["opportunity_area"] * opportunity_component
        + weights["boundary_safety"] * boundary_component
    )

    score = clamp_array(score, 0.0, 1.0)

    prioritized["priority_component_spatial"] = np.round(spatial_component, 6)
    prioritized["priority_component_density"] = np.round(density_component, 6)
    prioritized["priority_component_opportunity"] = np.round(
        opportunity_component,
        6,
    )
    prioritized["priority_component_boundary"] = np.round(
        boundary_component,
        6,
    )
    prioritized["operational_priority_score"] = np.round(score, 6)

    if exclusion_union is None:
        excluded_mask = np.zeros(len(prioritized), dtype=bool)
    else:
        excluded_mask = prioritized.geometry.apply(exclusion_union.covers).to_numpy(
            dtype=bool
        )

    prioritized["excluded_by_layer"] = excluded_mask
    prioritized["exclusion_status"] = np.where(
        excluded_mask,
        "dentro_de_via_canal_infraestructura_o_exclusion",
        "sin_exclusion_cartografica",
    )

    evaluable = (
        prioritized["is_evaluable"].fillna(False).astype(bool)
        if "is_evaluable" in prioritized.columns
        else pd.Series(False, index=prioritized.index)
    )

    candidate_boundary_risk = normalize_bool_series(prioritized["boundary_risk"])
    opportunity_boundary_risk = (
        normalize_bool_series(prioritized["opportunity_boundary_risk"])
        if "opportunity_boundary_risk" in prioritized.columns
        else pd.Series(False, index=prioritized.index)
    )

    combined_boundary_risk = candidate_boundary_risk | opportunity_boundary_risk
    prioritized["combined_boundary_risk"] = combined_boundary_risk

    actionable_density = (
        density_ratio.fillna(1.0) < config["minimum_actionable_density_ratio"]
    ) | (
        local_density_ratio < config["minimum_actionable_density_ratio"]
    )

    classes: list[str] = []
    actions: list[str] = []

    for index, row in prioritized.iterrows():
        row_score = float(row["operational_priority_score"])
        row_excluded = bool(row["excluded_by_layer"])
        row_evaluable = bool(evaluable.loc[index])
        row_boundary_risk = bool(combined_boundary_risk.loc[index])
        row_actionable = bool(actionable_density.loc[index])
        density_class = str(row.get("density_class", ""))

        if row_excluded:
            priority_class = "descartado_por_exclusion"
            action = "no_proponer_resiembra_en_exclusion_cartografica"

        elif config["use_only_evaluable_hexagons"] and not row_evaluable:
            priority_class = "revision_borde_no_evaluable"
            action = "revisar_manualmente_por_efecto_de_borde"

        elif (
            row_score >= config["high_priority_score"]
            and row_actionable
            and density_class in {"deficit_severo", "deficit_moderado"}
            and not row_boundary_risk
        ):
            priority_class = "prioridad_alta"
            action = "inspeccion_de_campo_prioridad_alta"

        elif row_score >= config["medium_priority_score"] and row_actionable:
            priority_class = "prioridad_media"
            action = "inspeccion_de_campo_prioridad_media"

        else:
            priority_class = "prioridad_baja"
            action = "revision_complementaria_no_urgente"

        classes.append(priority_class)
        actions.append(action)

    prioritized["operational_priority_class"] = classes
    prioritized["operational_management_action"] = actions
    prioritized["technical_decision"] = "pendiente_revision_tecnica"
    prioritized["technical_land_use"] = "sin_clasificar"
    prioritized["technical_observation"] = ""

    return prioritized


def build_priority_zones(
    hexagons: gpd.GeoDataFrame,
    candidates: gpd.GeoDataFrame,
    target_density_plants_ha: float,
) -> gpd.GeoDataFrame:
    """Resume candidatos y déficit teórico por hexágono."""

    zones = hexagons.copy()

    candidate_context = candidates.loc[candidates["hex_id"].notna()].copy()

    if candidate_context.empty:
        grouped = pd.DataFrame(index=pd.Index([], name="hex_id"))
    else:
        grouped = candidate_context.groupby("hex_id", dropna=True).agg(
            candidates_total=("candidate_id", "count"),
            priority_score_mean=("operational_priority_score", "mean"),
            priority_score_max=("operational_priority_score", "max"),
            candidates_excluded=("excluded_by_layer", "sum"),
            boundary_risk_candidates=("combined_boundary_risk", "sum"),
        )

        class_counts = (
            candidate_context.groupby(
                ["hex_id", "operational_priority_class"],
                dropna=True,
            )
            .size()
            .unstack(fill_value=0)
        )

        grouped = grouped.join(class_counts, how="left")

    zones = zones.merge(grouped, how="left", left_on="hex_id", right_index=True)

    count_columns = [
        "candidates_total",
        "candidates_excluded",
        "boundary_risk_candidates",
        "prioridad_alta",
        "prioridad_media",
        "prioridad_baja",
        "descartado_por_exclusion",
        "revision_borde_no_evaluable",
    ]

    for column in count_columns:
        if column not in zones.columns:
            zones[column] = 0

        zones[column] = pd.to_numeric(zones[column], errors="coerce").fillna(0).astype(int)

    if "priority_score_mean" not in zones.columns:
        zones["priority_score_mean"] = 0.0
    else:
        zones["priority_score_mean"] = pd.to_numeric(
            zones["priority_score_mean"],
            errors="coerce",
        ).fillna(0.0)

    if "priority_score_max" not in zones.columns:
        zones["priority_score_max"] = 0.0
    else:
        zones["priority_score_max"] = pd.to_numeric(
            zones["priority_score_max"],
            errors="coerce",
        ).fillna(0.0)

    zones["target_density_ha"] = float(target_density_plants_ha)
    zones["target_plants_theoretical"] = (
        zones["clipped_area_m2"] / 10000.0 * target_density_plants_ha
    )

    zones["target_plants_floor"] = np.floor(
        zones["target_plants_theoretical"] + 1e-9
    ).astype(int)

    zones["theoretical_deficit_plants"] = np.maximum(
        zones["target_plants_floor"] - zones["plant_count"].astype(int),
        0,
    ).astype(int)

    zones["actionable_candidates"] = (
        zones["prioridad_alta"] + zones["prioridad_media"]
    )

    zones["recommended_field_checks"] = np.minimum(
        zones["theoretical_deficit_plants"],
        zones["actionable_candidates"],
    ).astype(int)

    zone_classes: list[str] = []
    zone_actions: list[str] = []

    for _, row in zones.iterrows():
        evaluable = bool(row["is_evaluable"])
        high_count = int(row["prioridad_alta"])
        medium_count = int(row["prioridad_media"])
        total_count = int(row["candidates_total"])
        density_class = str(row["density_class"])

        if not evaluable:
            zone_class = "borde_no_evaluable"
            zone_action = "revision_manual_sin_recomendacion_automatica"

        elif high_count > 0 and density_class == "deficit_severo":
            zone_class = "prioridad_alta"
            zone_action = "programar_inspeccion_de_campo_prioritaria"

        elif (
            high_count + medium_count > 0
            and density_class in {"deficit_severo", "deficit_moderado"}
        ):
            zone_class = "prioridad_media"
            zone_action = "incluir_en_recorrido_tecnico"

        elif total_count > 0:
            zone_class = "prioridad_baja"
            zone_action = "revision_complementaria"

        else:
            zone_class = "sin_candidatos"
            zone_action = "sin_accion_por_oportunidades"

        zone_classes.append(zone_class)
        zone_actions.append(zone_action)

    zones["operational_zone_class"] = zone_classes
    zones["operational_zone_action"] = zone_actions
    zones["technical_status"] = "pendiente_revision_tecnica"

    return gpd.GeoDataFrame(zones, geometry="geometry", crs=hexagons.crs)


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
    layer: gpd.GeoDataFrame,
    output_path: Path,
    layer_name: str,
) -> None:
    """Escribe un GeoPackage mediante un archivo temporal."""

    temporary_path = output_path.with_suffix(".partial.gpkg")

    try:
        if temporary_path.exists():
            temporary_path.unlink()

        layer.to_file(
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
    output_path: Path,
    layer_name: str,
    expected_rows: int,
) -> dict[str, Any]:
    """Reabre una salida y verifica su cantidad, CRS y geometría."""

    layers = pyogrio.list_layers(output_path)
    verified = gpd.read_file(
        output_path,
        layer=layer_name,
        engine="pyogrio",
    )

    if len(verified) != expected_rows:
        raise RuntimeError(
            "La cantidad de elementos del GeoPackage no coincide con la salida."
        )

    if verified.crs is None:
        raise RuntimeError("El GeoPackage generado no tiene CRS.")

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
    result: OperationalPriorityResult,
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


def prioritize_planting_opportunities(
    hex_density_gpkg: str | Path,
    candidates_gpkg: str | Path,
    opportunities_gpkg: str | Path,
    target_density_plants_ha: float,
    hex_layer: str = "densidad_hexagonal",
    candidates_layer: str = "candidatos_siembra",
    opportunities_layer: str = "zonas_oportunidad_siembra",
    config_path: str | Path | None = None,
    exclusions_gpkg: str | Path | None = None,
    exclusions_layer: str | None = None,
    output_dir: str | Path | None = None,
) -> OperationalPriorityResult:
    """Combina déficit hexagonal y oportunidades geométricas."""

    started_at = datetime.now().isoformat(timespec="seconds")
    start_time = time.perf_counter()

    normalized_hex_path = Path(hex_density_gpkg).expanduser().resolve(strict=False)
    normalized_candidates_path = Path(candidates_gpkg).expanduser().resolve(
        strict=False
    )
    normalized_opportunities_path = Path(opportunities_gpkg).expanduser().resolve(
        strict=False
    )

    result = OperationalPriorityResult(
        success=False,
        started_at=started_at,
        finished_at=None,
        hex_density_gpkg=str(normalized_hex_path),
        candidates_gpkg=str(normalized_candidates_path),
        opportunities_gpkg=str(normalized_opportunities_path),
        target_density_plants_ha=float(target_density_plants_ha),
    )

    output_directory: Path | None = None
    generated_paths: list[Path] = []

    try:
        for path, label in (
            (normalized_hex_path, "mapa hexagonal"),
            (normalized_candidates_path, "candidatos de siembra"),
            (normalized_opportunities_path, "zonas de oportunidad"),
        ):
            if not path.is_file():
                raise FileNotFoundError(f"No existe el archivo de {label}: {path}")

        normalized_config_path, priority_config = load_priority_config(config_path)

        output_directory = resolve_output_directory(
            candidates_gpkg=normalized_candidates_path,
            target_density_plants_ha=target_density_plants_ha,
            output_dir=output_dir,
        )

        result.output_directory = str(output_directory)

        candidates_csv_path = (
            output_directory / "candidatos_siembra_priorizados.csv"
        )
        candidates_output_path = (
            output_directory / "candidatos_siembra_priorizados.gpkg"
        )
        zones_output_path = output_directory / "zonas_prioridad_operativa.gpkg"
        summary_csv_path = output_directory / "resumen_prioridad_operativa.csv"
        report_path = output_directory / "prioridad_operativa.json"

        expected_outputs = (
            candidates_csv_path,
            candidates_output_path,
            zones_output_path,
            summary_csv_path,
            report_path,
        )

        existing_outputs = [path for path in expected_outputs if path.exists()]

        if existing_outputs:
            raise FileExistsError(
                "No se sobrescribirán salidas existentes: "
                + ", ".join(str(path) for path in existing_outputs)
            )

        output_directory.mkdir(parents=True, exist_ok=True)

        hexagons, candidates, opportunities = read_inputs(
            hex_density_gpkg=normalized_hex_path,
            candidates_gpkg=normalized_candidates_path,
            opportunities_gpkg=normalized_opportunities_path,
            hex_layer=hex_layer,
            candidates_layer=candidates_layer,
            opportunities_layer=opportunities_layer,
        )

        consistency = validate_target_density_consistency(
            hexagons=hexagons,
            candidates=candidates,
            target_density_plants_ha=target_density_plants_ha,
            maximum_difference_percent=priority_config[
                "maximum_reference_difference_percent"
            ],
        )

        exclusions, exclusion_union = read_exclusions(
            exclusions_gpkg=exclusions_gpkg,
            exclusions_layer=exclusions_layer,
            target_crs=hexagons.crs,
        )

        candidates_with_hex = assign_hexagon_context(
            candidates=candidates,
            hexagons=hexagons,
        )

        candidates_with_context = attach_opportunity_context(
            candidates=candidates_with_hex,
            opportunities=opportunities,
        )

        prioritized_candidates = calculate_candidate_priorities(
            candidates=candidates_with_context,
            config=priority_config,
            exclusion_union=exclusion_union,
        )

        priority_zones = build_priority_zones(
            hexagons=hexagons,
            candidates=prioritized_candidates,
            target_density_plants_ha=target_density_plants_ha,
        )

        candidates_without_geometry = pd.DataFrame(
            prioritized_candidates.drop(columns="geometry", errors="ignore")
        )

        write_csv_atomic(candidates_without_geometry, candidates_csv_path)
        generated_paths.append(candidates_csv_path)
        result.prioritized_candidates_csv = str(candidates_csv_path)

        write_gpkg_atomic(
            prioritized_candidates,
            candidates_output_path,
            "candidatos_siembra_priorizados",
        )
        generated_paths.append(candidates_output_path)
        result.prioritized_candidates_gpkg = str(candidates_output_path)

        write_gpkg_atomic(
            priority_zones,
            zones_output_path,
            "zonas_prioridad_operativa",
        )
        generated_paths.append(zones_output_path)
        result.priority_zones_gpkg = str(zones_output_path)

        candidate_class_counts = (
            prioritized_candidates["operational_priority_class"]
            .value_counts()
            .to_dict()
        )

        zone_class_counts = (
            priority_zones["operational_zone_class"]
            .value_counts()
            .to_dict()
        )

        actionable_candidates = int(
            prioritized_candidates["operational_priority_class"]
            .isin(["prioridad_alta", "prioridad_media"])
            .sum()
        )

        summary_record = {
            "fecha_proceso": datetime.now().isoformat(timespec="seconds"),
            "target_density_plants_ha": float(target_density_plants_ha),
            "candidates_input": int(len(candidates)),
            "candidates_priority_high": int(
                candidate_class_counts.get("prioridad_alta", 0)
            ),
            "candidates_priority_medium": int(
                candidate_class_counts.get("prioridad_media", 0)
            ),
            "candidates_priority_low": int(
                candidate_class_counts.get("prioridad_baja", 0)
            ),
            "candidates_boundary_review": int(
                candidate_class_counts.get("revision_borde_no_evaluable", 0)
            ),
            "candidates_excluded": int(
                candidate_class_counts.get("descartado_por_exclusion", 0)
            ),
            "actionable_candidates_high_medium": actionable_candidates,
            "zones_total": int(len(priority_zones)),
            "zones_priority_high": int(zone_class_counts.get("prioridad_alta", 0)),
            "zones_priority_medium": int(
                zone_class_counts.get("prioridad_media", 0)
            ),
            "zones_priority_low": int(zone_class_counts.get("prioridad_baja", 0)),
            "zones_boundary_not_evaluable": int(
                zone_class_counts.get("borde_no_evaluable", 0)
            ),
            "zones_without_candidates": int(
                zone_class_counts.get("sin_candidatos", 0)
            ),
            "recommended_field_checks_total": int(
                priority_zones["recommended_field_checks"].sum()
            ),
            "exclusion_features": int(len(exclusions)) if exclusions is not None else 0,
            "technical_status": "pendiente_revision_tecnica",
        }

        write_csv_atomic(pd.DataFrame([summary_record]), summary_csv_path)
        generated_paths.append(summary_csv_path)
        result.summary_csv = str(summary_csv_path)

        elapsed_seconds = round(time.perf_counter() - start_time, 3)

        result.metadata = {
            "config_path": str(normalized_config_path),
            "target_consistency": consistency,
            "priority_config": priority_config,
            "candidates": {
                "input": int(len(candidates)),
                "output": int(len(prioritized_candidates)),
                "classes": {
                    str(key): int(value)
                    for key, value in candidate_class_counts.items()
                },
                "unassigned_to_hexagon": int(
                    prioritized_candidates["hex_id"].isna().sum()
                ),
            },
            "zones": {
                "total": int(len(priority_zones)),
                "classes": {
                    str(key): int(value)
                    for key, value in zone_class_counts.items()
                },
                "recommended_field_checks_total": int(
                    priority_zones["recommended_field_checks"].sum()
                ),
            },
            "exclusions": {
                "provided": exclusions is not None,
                "feature_count": int(len(exclusions)) if exclusions is not None else 0,
            },
            "verification": {
                "candidates": verify_gpkg(
                    candidates_output_path,
                    "candidatos_siembra_priorizados",
                    len(prioritized_candidates),
                ),
                "zones": verify_gpkg(
                    zones_output_path,
                    "zonas_prioridad_operativa",
                    len(priority_zones),
                ),
            },
            "elapsed_seconds": elapsed_seconds,
        }

        if exclusions is None:
            result.warnings.append(
                "No se proporcionó una capa de vías, canales o infraestructura. "
                "La exclusión de usos no cultivables deberá realizarse durante "
                "la revisión técnica."
            )

        if prioritized_candidates["hex_id"].isna().any():
            result.warnings.append(
                "Uno o más candidatos no pudieron asociarse a un hexágono. "
                "Se conservaron para revisión, pero no deben priorizarse "
                "automáticamente."
            )

        result.warnings.append(
            "La prioridad es un indicador operativo configurable. No confirma "
            "que una posición sea agronómicamente apta para resiembra."
        )

        result.success = True

    except Exception as error:
        result.errors.append(
            "No fue posible generar la priorización operativa: "
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

    if result.success and output_directory is not None:
        report_path = output_directory / "prioridad_operativa.json"
    else:
        GLOBAL_LOGS_DIRECTORY.mkdir(parents=True, exist_ok=True)
        report_path = (
            GLOBAL_LOGS_DIRECTORY
            / (
                "operational_priority_error_"
                + datetime.now().strftime("%Y%m%d_%H%M%S_%f")
                + ".json"
            )
        )

    save_report(result, report_path)

    return result


def print_operational_priority_summary(
    result: OperationalPriorityResult,
) -> None:
    """Muestra el resumen de la priorización."""

    print("=" * 72)
    print("PRIORIZACIÓN OPERATIVA DE OPORTUNIDADES DE SIEMBRA")
    print("=" * 72)
    print(
        "Densidad objetivo: "
        f"{result.target_density_plants_ha} plantas/ha"
    )
    print(
        "Estado: "
        f"{'COMPLETADO' if result.success else 'ERROR'}"
    )

    if result.metadata:
        candidate_classes = result.metadata["candidates"]["classes"]
        zone_classes = result.metadata["zones"]["classes"]

        print(
            "Candidatos analizados: "
            f"{result.metadata['candidates']['input']}"
        )
        print(
            "Prioridad alta: "
            f"{candidate_classes.get('prioridad_alta', 0)}"
        )
        print(
            "Prioridad media: "
            f"{candidate_classes.get('prioridad_media', 0)}"
        )
        print(
            "Prioridad baja: "
            f"{candidate_classes.get('prioridad_baja', 0)}"
        )
        print(
            "Descartados por exclusión: "
            f"{candidate_classes.get('descartado_por_exclusion', 0)}"
        )
        print(
            "Zonas de prioridad alta: "
            f"{zone_classes.get('prioridad_alta', 0)}"
        )
        print(
            "Zonas de prioridad media: "
            f"{zone_classes.get('prioridad_media', 0)}"
        )
        print(
            "Inspecciones sugeridas: "
            f"{result.metadata['zones']['recommended_field_checks_total']}"
        )
        print(
            "Tiempo: "
            f"{result.metadata['elapsed_seconds']} segundos"
        )

    if result.prioritized_candidates_gpkg:
        print(
            "Candidatos priorizados: "
            f"{result.prioritized_candidates_gpkg}"
        )

    if result.priority_zones_gpkg:
        print(
            "Zonas operativas: "
            f"{result.priority_zones_gpkg}"
        )

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


def run_operational_priority(
    hex_density_gpkg: str | Path,
    candidates_gpkg: str | Path,
    opportunities_gpkg: str | Path,
    target_density_plants_ha: float,
    hex_layer: str = "densidad_hexagonal",
    candidates_layer: str = "candidatos_siembra",
    opportunities_layer: str = "zonas_oportunidad_siembra",
    config_path: str | Path | None = None,
    exclusions_gpkg: str | Path | None = None,
    exclusions_layer: str | None = None,
    output_dir: str | Path | None = None,
) -> int:
    """Ejecuta la priorización desde main.py."""

    result = prioritize_planting_opportunities(
        hex_density_gpkg=hex_density_gpkg,
        candidates_gpkg=candidates_gpkg,
        opportunities_gpkg=opportunities_gpkg,
        target_density_plants_ha=target_density_plants_ha,
        hex_layer=hex_layer,
        candidates_layer=candidates_layer,
        opportunities_layer=opportunities_layer,
        config_path=config_path,
        exclusions_gpkg=exclusions_gpkg,
        exclusions_layer=exclusions_layer,
        output_dir=output_dir,
    )

    print_operational_priority_summary(result)

    return 0 if result.success else 1
