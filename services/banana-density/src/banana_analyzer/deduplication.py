from __future__ import annotations

import json
import math
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Iterator

import numpy as np
import pandas as pd
from pyproj import CRS


PROJECT_ROOT = Path(__file__).resolve().parents[2]
GLOBAL_LOGS_DIRECTORY = PROJECT_ROOT / "logs"

DEFAULT_DUPLICATE_DISTANCE_METERS = 0.50

REQUIRED_COLUMNS = {
    "detection_id",
    "tile_file",
    "class_id",
    "confidence",
    "coord_x",
    "coord_y",
    "epsg",
}

AUDIT_COLUMNS = [
    "duplicate_group_id",
    "kept_detection_id",
    "kept_tile_file",
    "kept_confidence",
    "distance_to_kept_m",
    "dedup_reason",
]


@dataclass
class DeduplicationResult:
    """Resultado estructurado de la deduplicación espacial."""

    success: bool
    started_at: str
    finished_at: str | None
    input_csv: str
    distance_threshold_m: float
    output_directory: str | None = None
    clean_csv: str | None = None
    removed_csv: str | None = None
    report_path: str | None = None
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


def resolve_output_directory(
    input_csv: Path,
    output_dir: str | Path | None,
) -> Path:
    """Determina la carpeta de salida de detecciones limpias."""

    if output_dir is not None:
        return Path(
            output_dir
        ).expanduser().resolve(strict=False)

    if input_csv.parent.name == "03_detecciones_raw":
        return (
            input_csv.parent.parent
            / "04_detecciones_limpias"
        )

    return input_csv.parent / "deduplicated"


def validate_parameters(
    distance_threshold_m: float,
) -> list[str]:
    """Valida los parámetros de deduplicación."""

    errors: list[str] = []

    if not math.isfinite(distance_threshold_m):
        errors.append(
            "La distancia de deduplicación debe ser "
            "un número finito."
        )

    elif distance_threshold_m <= 0:
        errors.append(
            "La distancia de deduplicación debe ser "
            "mayor que cero."
        )

    return errors


def validate_input_table(
    table: pd.DataFrame,
) -> list[str]:
    """Comprueba la estructura mínima del CSV."""

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
            "El CSV no contiene detecciones."
        )

    return errors


def normalize_input_table(
    table: pd.DataFrame,
) -> tuple[pd.DataFrame, int]:
    """Normaliza coordenadas, confianza, clase y EPSG."""

    normalized = table.copy()

    for column in (
        "coord_x",
        "coord_y",
        "confidence",
        "epsg",
    ):
        normalized[column] = pd.to_numeric(
            normalized[column],
            errors="coerce",
        )

    normalized["tile_file"] = (
        normalized["tile_file"]
        .astype("string")
        .str.strip()
    )

    normalized["detection_id"] = (
        normalized["detection_id"]
        .astype("string")
        .str.strip()
    )

    invalid_mask = (
        normalized["coord_x"].isna()
        | normalized["coord_y"].isna()
        | normalized["confidence"].isna()
        | normalized["epsg"].isna()
        | normalized["tile_file"].isna()
        | normalized["detection_id"].isna()
        | normalized["tile_file"].eq("")
        | normalized["detection_id"].eq("")
        | ~np.isfinite(normalized["coord_x"])
        | ~np.isfinite(normalized["coord_y"])
        | ~np.isfinite(normalized["confidence"])
    )

    if invalid_mask.any():
        rows = [
            int(index + 2)
            for index
            in normalized.index[invalid_mask]
        ]

        raise ValueError(
            "Existen datos obligatorios vacíos o "
            f"inválidos en las filas: {rows}."
        )

    if not normalized["confidence"].between(
        0.0,
        1.0,
    ).all():
        raise ValueError(
            "La columna confidence contiene valores "
            "fuera del intervalo de 0 a 1."
        )

    if normalized["detection_id"].duplicated().any():
        duplicated_ids = (
            normalized.loc[
                normalized[
                    "detection_id"
                ].duplicated(keep=False),
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
            "La tabla debe contener un único EPSG. "
            f"Valores encontrados: {epsg_values}."
        )

    epsg_code = epsg_values[0]
    crs = CRS.from_epsg(epsg_code)

    if not crs.is_projected:
        raise ValueError(
            "La deduplicación por distancia requiere "
            "un CRS proyectado."
        )

    unit_names = [
        axis.unit_name.lower()
        for axis in crs.axis_info
        if axis.unit_name
    ]

    if not unit_names or not all(
        (
            "metre" in unit_name
            or "meter" in unit_name
        )
        for unit_name in unit_names
    ):
        raise ValueError(
            "El CRS debe utilizar metros para aplicar "
            "el umbral de distancia."
        )

    normalized["epsg"] = (
        normalized["epsg"].astype(int)
    )

    return normalized, epsg_code


def build_spatial_grid(
    coordinates: np.ndarray,
    cell_size: float,
) -> dict[tuple[int, int], list[int]]:
    """
    Indexa los puntos mediante una cuadrícula espacial.

    Evita comparar cada detección contra todas las demás.
    """

    grid: dict[
        tuple[int, int],
        list[int],
    ] = {}

    for index, (
        x_value,
        y_value,
    ) in enumerate(coordinates):
        cell = (
            math.floor(
                float(x_value) / cell_size
            ),
            math.floor(
                float(y_value) / cell_size
            ),
        )

        grid.setdefault(
            cell,
            [],
        ).append(index)

    return grid


def iter_neighbor_indices(
    x_value: float,
    y_value: float,
    cell_size: float,
    grid: dict[
        tuple[int, int],
        list[int],
    ],
) -> Iterator[int]:
    """Busca candidatos en las nueve celdas vecinas."""

    cell_x = math.floor(
        x_value / cell_size
    )

    cell_y = math.floor(
        y_value / cell_size
    )

    for x_offset in (-1, 0, 1):
        for y_offset in (-1, 0, 1):
            yield from grid.get(
                (
                    cell_x + x_offset,
                    cell_y + y_offset,
                ),
                (),
            )


def deduplicate_table(
    table: pd.DataFrame,
    distance_threshold_m: float,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """
    Elimina duplicados entre tiles distintos.

    Se procesan las detecciones desde la mayor confianza
    hacia la menor. Una detección aceptada conserva prioridad
    y suprime detecciones de la misma clase, correspondientes
    a otro tile y localizadas dentro del umbral establecido.
    """

    working = table.reset_index(
        drop=True
    ).copy()

    coordinates = working[
        [
            "coord_x",
            "coord_y",
        ]
    ].to_numpy(dtype=float)

    confidences = working[
        "confidence"
    ].to_numpy(dtype=float)

    tile_files = (
        working["tile_file"]
        .astype(str)
        .to_numpy()
    )

    class_ids = (
        working["class_id"]
        .astype(str)
        .to_numpy()
    )

    detection_ids = (
        working["detection_id"]
        .astype(str)
        .to_numpy()
    )

    order = sorted(
        range(len(working)),
        key=lambda index: (
            -confidences[index],
            detection_ids[index],
        ),
    )

    # 0 = no procesada
    # 1 = conservada
    # 2 = eliminada
    status = np.zeros(
        len(working),
        dtype=np.uint8,
    )

    grid = build_spatial_grid(
        coordinates=coordinates,
        cell_size=distance_threshold_m,
    )

    removed_records: list[
        dict[str, Any]
    ] = []

    winner_duplicate_counts: dict[
        int,
        int,
    ] = {}

    winner_group_ids: dict[
        int,
        str,
    ] = {}

    group_counter = 0

    threshold_squared = (
        distance_threshold_m**2
    )

    for winner_index in order:
        if status[winner_index] != 0:
            continue

        status[winner_index] = 1

        winner_x = float(
            coordinates[
                winner_index,
                0,
            ]
        )

        winner_y = float(
            coordinates[
                winner_index,
                1,
            ]
        )

        candidates_to_remove: list[
            tuple[int, float]
        ] = []

        for candidate_index in iter_neighbor_indices(
            x_value=winner_x,
            y_value=winner_y,
            cell_size=distance_threshold_m,
            grid=grid,
        ):
            if candidate_index == winner_index:
                continue

            if status[candidate_index] != 0:
                continue

            if (
                tile_files[candidate_index]
                == tile_files[winner_index]
            ):
                continue

            if (
                class_ids[candidate_index]
                != class_ids[winner_index]
            ):
                continue

            delta_x = (
                float(
                    coordinates[
                        candidate_index,
                        0,
                    ]
                )
                - winner_x
            )

            delta_y = (
                float(
                    coordinates[
                        candidate_index,
                        1,
                    ]
                )
                - winner_y
            )

            distance_squared = (
                delta_x * delta_x
                + delta_y * delta_y
            )

            if (
                distance_squared
                <= threshold_squared
            ):
                candidates_to_remove.append(
                    (
                        candidate_index,
                        math.sqrt(
                            distance_squared
                        ),
                    )
                )

        if not candidates_to_remove:
            continue

        group_counter += 1

        group_id = (
            f"dupgrp_{group_counter:07d}"
        )

        winner_group_ids[
            winner_index
        ] = group_id

        winner_duplicate_counts[
            winner_index
        ] = len(candidates_to_remove)

        for (
            candidate_index,
            distance_m,
        ) in candidates_to_remove:
            status[candidate_index] = 2

            removed_record = (
                working.iloc[
                    candidate_index
                ].to_dict()
            )

            removed_record.update(
                {
                    "duplicate_group_id": (
                        group_id
                    ),
                    "kept_detection_id": (
                        detection_ids[
                            winner_index
                        ]
                    ),
                    "kept_tile_file": (
                        tile_files[
                            winner_index
                        ]
                    ),
                    "kept_confidence": float(
                        confidences[
                            winner_index
                        ]
                    ),
                    "distance_to_kept_m": round(
                        distance_m,
                        8,
                    ),
                    "dedup_reason": (
                        "same_class_different_tile_"
                        "within_distance_threshold"
                    ),
                }
            )

            removed_records.append(
                removed_record
            )

    clean = working.loc[
        status == 1
    ].copy()

    clean["dedup_status"] = "kept"

    clean["duplicate_group_id"] = [
        winner_group_ids.get(index)
        for index in clean.index
    ]

    clean["duplicates_removed_count"] = [
        winner_duplicate_counts.get(
            index,
            0,
        )
        for index in clean.index
    ]

    clean[
        "dedup_distance_threshold_m"
    ] = distance_threshold_m

    clean = clean.sort_values(
        by="detection_id",
        kind="stable",
    ).reset_index(drop=True)

    if removed_records:
        removed = pd.DataFrame(
            removed_records
        )

        removed = removed.sort_values(
            by=[
                "duplicate_group_id",
                "distance_to_kept_m",
                "detection_id",
            ],
            kind="stable",
        ).reset_index(drop=True)

    else:
        removed = pd.DataFrame(
            columns=[
                *working.columns.tolist(),
                *AUDIT_COLUMNS,
            ]
        )

    return clean, removed


def write_csv_atomic(
    table: pd.DataFrame,
    output_path: Path,
) -> None:
    """Escribe un CSV sin dejar archivos incompletos."""

    temporary_path = (
        output_path.with_suffix(
            ".partial.csv"
        )
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


def save_report(
    result: DeduplicationResult,
    report_path: Path,
) -> Path:
    """Guarda el informe JSON."""

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


def deduplicate_detections(
    input_csv: str | Path,
    distance_threshold_m: float = (
        DEFAULT_DUPLICATE_DISTANCE_METERS
    ),
    output_dir: str | Path | None = None,
) -> DeduplicationResult:
    """Ejecuta la deduplicación espacial."""

    started_at = (
        datetime.now().isoformat(
            timespec="seconds"
        )
    )

    start_time = time.perf_counter()

    normalized_input_csv = Path(
        input_csv
    ).expanduser().resolve(strict=False)

    result = DeduplicationResult(
        success=False,
        started_at=started_at,
        finished_at=None,
        input_csv=str(
            normalized_input_csv
        ),
        distance_threshold_m=(
            distance_threshold_m
        ),
    )

    output_directory = (
        resolve_output_directory(
            input_csv=normalized_input_csv,
            output_dir=output_dir,
        )
    )

    result.output_directory = str(
        output_directory
    )

    clean_csv_path = (
        output_directory
        / "detections_deduplicated.csv"
    )

    removed_csv_path = (
        output_directory
        / "duplicates_removed.csv"
    )

    report_path = (
        output_directory
        / "deduplication_report.json"
    )

    result.errors.extend(
        validate_parameters(
            distance_threshold_m
        )
    )

    if not normalized_input_csv.is_file():
        result.errors.append(
            "El CSV de entrada no existe."
        )

    existing_outputs = [
        path
        for path in (
            clean_csv_path,
            removed_csv_path,
            report_path,
        )
        if path.exists()
    ]

    if existing_outputs:
        result.errors.append(
            "No se sobrescribirán salidas "
            "existentes: "
            + ", ".join(
                str(path)
                for path in existing_outputs
            )
        )

    if result.errors:
        result.finished_at = (
            datetime.now().isoformat(
                timespec="seconds"
            )
        )

        error_report = (
            GLOBAL_LOGS_DIRECTORY
            / (
                "deduplication_error_"
                + datetime.now().strftime(
                    "%Y%m%d_%H%M%S"
                )
                + ".json"
            )
        )

        save_report(
            result,
            error_report,
        )

        return result

    output_directory.mkdir(
        parents=True,
        exist_ok=True,
    )

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
                "El CSV no cumple la "
                "estructura requerida."
            )

        normalized, epsg_code = (
            normalize_input_table(
                table
            )
        )

        clean, removed = (
            deduplicate_table(
                table=normalized,
                distance_threshold_m=(
                    distance_threshold_m
                ),
            )
        )

        raw_count = len(normalized)
        clean_count = len(clean)
        removed_count = len(removed)

        if (
            raw_count
            != clean_count + removed_count
        ):
            raise RuntimeError(
                "La suma de detecciones conservadas "
                "y eliminadas no coincide con el "
                "total de entrada."
            )

        if clean[
            "detection_id"
        ].duplicated().any():
            raise RuntimeError(
                "La salida limpia contiene "
                "detection_id repetidos."
            )

        write_csv_atomic(
            table=clean,
            output_path=clean_csv_path,
        )

        write_csv_atomic(
            table=removed,
            output_path=removed_csv_path,
        )

        result.clean_csv = str(
            clean_csv_path
        )

        result.removed_csv = str(
            removed_csv_path
        )

        distance_stats = None

        if not removed.empty:
            distance_stats = {
                "minimum_m": round(
                    float(
                        removed[
                            "distance_to_kept_m"
                        ].min()
                    ),
                    8,
                ),
                "mean_m": round(
                    float(
                        removed[
                            "distance_to_kept_m"
                        ].mean()
                    ),
                    8,
                ),
                "median_m": round(
                    float(
                        removed[
                            "distance_to_kept_m"
                        ].median()
                    ),
                    8,
                ),
                "maximum_m": round(
                    float(
                        removed[
                            "distance_to_kept_m"
                        ].max()
                    ),
                    8,
                ),
            }

        elapsed_seconds = round(
            time.perf_counter()
            - start_time,
            3,
        )

        result.metadata = {
            "input_rows": int(
                raw_count
            ),
            "kept_rows": int(
                clean_count
            ),
            "removed_rows": int(
                removed_count
            ),
            "reduction_percent": round(
                (
                    removed_count
                    / raw_count
                    * 100.0
                    if raw_count > 0
                    else 0.0
                ),
                4,
            ),
            "duplicate_groups": int(
                clean[
                    "duplicate_group_id"
                ].notna().sum()
            ),
            "epsg": epsg_code,
            "crs": (
                f"EPSG:{epsg_code}"
            ),
            "distance_threshold_m": (
                distance_threshold_m
            ),
            "rules": {
                "same_class_only": True,
                "different_tiles_only": True,
                "winner_selection": (
                    "highest_confidence_"
                    "then_detection_id"
                ),
                "same_tile_detections_"
                "preserved": True,
            },
            "removed_distance_statistics": (
                distance_stats
            ),
            "elapsed_seconds": (
                elapsed_seconds
            ),
        }

        result.warnings.append(
            "El umbral aplicado es un parámetro "
            "de calibración. Debe validarse "
            "visualmente antes de considerarlo "
            "definitivo para producción."
        )

        result.success = True

    except Exception as error:
        result.errors.append(
            "No fue posible deduplicar las "
            "detecciones: "
            f"{type(error).__name__}: {error}"
        )

        for incomplete_path in (
            clean_csv_path,
            removed_csv_path,
        ):
            if incomplete_path.exists():
                try:
                    incomplete_path.unlink()

                except OSError:
                    result.warnings.append(
                        "No fue posible eliminar "
                        "una salida incompleta: "
                        f"{incomplete_path}"
                    )

    result.finished_at = (
        datetime.now().isoformat(
            timespec="seconds"
        )
    )

    save_report(
        result=result,
        report_path=report_path,
    )

    return result


def print_deduplication_summary(
    result: DeduplicationResult,
) -> None:
    """Muestra un resumen en la terminal."""

    print("=" * 72)
    print(
        "DEDUPLICACIÓN ESPACIAL DE DETECCIONES"
    )
    print("=" * 72)

    print(
        f"CSV de entrada: {result.input_csv}"
    )

    print(
        "Umbral: "
        f"{result.distance_threshold_m} m"
    )

    print(
        "Estado: "
        f"{'COMPLETADO' if result.success else 'ERROR'}"
    )

    if result.metadata:
        print(
            "Detecciones crudas: "
            f"{result.metadata['input_rows']}"
        )

        print(
            "Detecciones conservadas: "
            f"{result.metadata['kept_rows']}"
        )

        print(
            "Duplicados eliminados: "
            f"{result.metadata['removed_rows']}"
        )

        print(
            "Reducción: "
            f"{result.metadata['reduction_percent']} %"
        )

        print(
            "Grupos con duplicados: "
            f"{result.metadata['duplicate_groups']}"
        )

        print(
            "Tiempo: "
            f"{result.metadata['elapsed_seconds']} "
            "segundos"
        )

    if result.clean_csv:
        print(
            f"CSV limpio: {result.clean_csv}"
        )

    if result.removed_csv:
        print(
            "Auditoría de eliminados: "
            f"{result.removed_csv}"
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


def run_deduplication(
    input_csv: str | Path,
    distance_threshold_m: float = (
        DEFAULT_DUPLICATE_DISTANCE_METERS
    ),
    output_dir: str | Path | None = None,
) -> int:
    """Ejecuta la deduplicación desde main.py."""

    result = deduplicate_detections(
        input_csv=input_csv,
        distance_threshold_m=(
            distance_threshold_m
        ),
        output_dir=output_dir,
    )

    print_deduplication_summary(
        result
    )

    return 0 if result.success else 1