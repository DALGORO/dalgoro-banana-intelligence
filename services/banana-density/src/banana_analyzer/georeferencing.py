from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import rasterio


PROJECT_ROOT = Path(__file__).resolve().parents[2]
GLOBAL_LOGS_DIRECTORY = PROJECT_ROOT / "logs"

REQUIRED_COLUMNS = {
    "detection_id",
    "tile_id",
    "tile_file",
    "center_x_px",
    "center_y_px",
}


@dataclass
class GeoreferencingResult:
    """Resultado de la georreferenciación de detecciones."""

    success: bool
    started_at: str
    finished_at: str | None
    detections_csv: str
    tiles_directory: str
    output_csv: str | None = None
    errors_csv: str | None = None
    report_path: str | None = None
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


def resolve_output_directory(
    detections_csv: Path,
    output_dir: str | Path | None,
) -> Path:
    """Determina la carpeta de salida."""

    if output_dir is not None:
        return Path(
            output_dir
        ).expanduser().resolve(strict=False)

    return detections_csv.parent


def validate_input_paths(
    detections_csv: Path,
    tiles_directory: Path,
) -> list[str]:
    """Valida los archivos y carpetas de entrada."""

    errors: list[str] = []

    if not detections_csv.is_file():
        errors.append(
            "El CSV de detecciones no existe."
        )

    if not tiles_directory.is_dir():
        errors.append(
            "La carpeta de tiles no existe."
        )

    return errors


def load_detections(
    detections_csv: Path,
) -> pd.DataFrame:
    """Lee el CSV generado por el módulo YOLO."""

    return pd.read_csv(
        detections_csv,
        encoding="utf-8-sig",
    )


def validate_required_columns(
    detections: pd.DataFrame,
) -> list[str]:
    """Comprueba que existan las columnas necesarias."""

    missing_columns = sorted(
        REQUIRED_COLUMNS
        - set(detections.columns)
    )

    if not missing_columns:
        return []

    return [
        "Faltan columnas obligatorias en el CSV: "
        + ", ".join(missing_columns)
    ]


def normalize_numeric_columns(
    detections: pd.DataFrame,
) -> tuple[pd.DataFrame, list[dict[str, Any]]]:
    """Convierte a número las coordenadas de píxel."""

    working = detections.copy()

    working["center_x_px"] = pd.to_numeric(
        working["center_x_px"],
        errors="coerce",
    )

    working["center_y_px"] = pd.to_numeric(
        working["center_y_px"],
        errors="coerce",
    )

    invalid_mask = (
        working["center_x_px"].isna()
        | working["center_y_px"].isna()
    )

    invalid_rows: list[dict[str, Any]] = []

    if invalid_mask.any():
        for dataframe_index, row in working.loc[
            invalid_mask
        ].iterrows():
            invalid_rows.append(
                {
                    "csv_row": int(
                        dataframe_index + 2
                    ),
                    "detection_id": row.get(
                        "detection_id"
                    ),
                    "tile_file": row.get(
                        "tile_file"
                    ),
                    "error": (
                        "center_x_px o center_y_px "
                        "no es un valor numérico."
                    ),
                }
            )

    return working, invalid_rows


def get_tile_metadata(
    tiles_directory: Path,
    tile_filename: str,
) -> dict[str, Any]:
    """Lee la transformación y metadatos de un tile."""

    safe_filename = Path(
        str(tile_filename)
    ).name

    tile_path = (
        tiles_directory
        / safe_filename
    )

    if not tile_path.is_file():
        raise FileNotFoundError(
            f"No se encontró el tile: {tile_path}"
        )

    with rasterio.open(tile_path) as source:
        if source.crs is None:
            raise ValueError(
                f"El tile no tiene CRS: {tile_path.name}"
            )

        if (
            source.transform
            == rasterio.Affine.identity()
        ):
            raise ValueError(
                "El tile tiene una transformación "
                f"identidad: {tile_path.name}"
            )

        return {
            "tile_path": str(tile_path),
            "width": int(source.width),
            "height": int(source.height),
            "transform": source.transform,
            "crs_object": source.crs,
            "crs": source.crs.to_string(),
            "epsg": source.crs.to_epsg(),
            "is_projected": bool(
                source.crs.is_projected
            ),
            "resolution_x": abs(
                float(source.res[0])
            ),
            "resolution_y": abs(
                float(source.res[1])
            ),
        }


def load_all_tile_metadata(
    detections: pd.DataFrame,
    tiles_directory: Path,
) -> tuple[
    dict[str, dict[str, Any]],
    list[dict[str, Any]],
]:
    """Carga una vez los metadatos de cada tile utilizado."""

    tile_metadata: dict[
        str,
        dict[str, Any],
    ] = {}

    tile_errors: list[dict[str, Any]] = []

    tile_names = sorted(
        {
            str(tile_file)
            for tile_file
            in detections["tile_file"].dropna()
        }
    )

    reference_crs = None

    for tile_filename in tile_names:
        try:
            metadata = get_tile_metadata(
                tiles_directory=tiles_directory,
                tile_filename=tile_filename,
            )

            if reference_crs is None:
                reference_crs = metadata[
                    "crs_object"
                ]
            elif (
                metadata["crs_object"]
                != reference_crs
            ):
                raise ValueError(
                    "El CRS del tile no coincide "
                    "con el CRS de los demás tiles."
                )

            tile_metadata[
                tile_filename
            ] = metadata

        except Exception as error:
            tile_errors.append(
                {
                    "tile_file": tile_filename,
                    "error_type": type(
                        error
                    ).__name__,
                    "error": str(error),
                }
            )

    return tile_metadata, tile_errors


def transform_detection_coordinates(
    detections: pd.DataFrame,
    tile_metadata: dict[
        str,
        dict[str, Any],
    ],
) -> tuple[pd.DataFrame, list[dict[str, Any]]]:
    """
    Convierte centros YOLO a coordenadas del CRS.

    Se usa directamente la transformación afín porque
    los centros YOLO son coordenadas continuas de imagen.
    """

    result = detections.copy()

    result["coord_x"] = np.nan
    result["coord_y"] = np.nan
    result["crs"] = None
    result["epsg"] = None
    result["resolution_x"] = np.nan
    result["resolution_y"] = np.nan
    result["source_tile_path"] = None
    result["georeferencing_method"] = (
        "tile_affine_transform"
    )

    coordinate_errors: list[
        dict[str, Any]
    ] = []

    for tile_filename, group in result.groupby(
        "tile_file",
        sort=False,
    ):
        tile_filename_text = str(
            tile_filename
        )

        metadata = tile_metadata.get(
            tile_filename_text
        )

        if metadata is None:
            for dataframe_index, row in group.iterrows():
                coordinate_errors.append(
                    {
                        "csv_row": int(
                            dataframe_index + 2
                        ),
                        "detection_id": row.get(
                            "detection_id"
                        ),
                        "tile_file": (
                            tile_filename_text
                        ),
                        "error": (
                            "No existen metadatos "
                            "geográficos para el tile."
                        ),
                    }
                )

            continue

        x_pixels = group[
            "center_x_px"
        ].to_numpy(dtype=float)

        y_pixels = group[
            "center_y_px"
        ].to_numpy(dtype=float)

        valid_bounds = (
            (x_pixels >= 0.0)
            & (
                x_pixels
                <= metadata["width"]
            )
            & (y_pixels >= 0.0)
            & (
                y_pixels
                <= metadata["height"]
            )
        )

        if not valid_bounds.all():
            invalid_indices = group.index[
                ~valid_bounds
            ]

            for dataframe_index in invalid_indices:
                row = result.loc[
                    dataframe_index
                ]

                coordinate_errors.append(
                    {
                        "csv_row": int(
                            dataframe_index + 2
                        ),
                        "detection_id": row.get(
                            "detection_id"
                        ),
                        "tile_file": (
                            tile_filename_text
                        ),
                        "error": (
                            "El centro de la detección "
                            "está fuera de los límites "
                            "del tile."
                        ),
                    }
                )

        valid_group_indices = group.index[
            valid_bounds
        ]

        if len(valid_group_indices) == 0:
            continue

        valid_x = result.loc[
            valid_group_indices,
            "center_x_px",
        ].to_numpy(dtype=float)

        valid_y = result.loc[
            valid_group_indices,
            "center_y_px",
        ].to_numpy(dtype=float)

        transform = metadata["transform"]

        world_x = (
            transform.a * valid_x
            + transform.b * valid_y
            + transform.c
        )

        world_y = (
            transform.d * valid_x
            + transform.e * valid_y
            + transform.f
        )

        result.loc[
            valid_group_indices,
            "coord_x",
        ] = world_x

        result.loc[
            valid_group_indices,
            "coord_y",
        ] = world_y

        result.loc[
            valid_group_indices,
            "crs",
        ] = metadata["crs"]

        result.loc[
            valid_group_indices,
            "epsg",
        ] = metadata["epsg"]

        result.loc[
            valid_group_indices,
            "resolution_x",
        ] = metadata["resolution_x"]

        result.loc[
            valid_group_indices,
            "resolution_y",
        ] = metadata["resolution_y"]

        result.loc[
            valid_group_indices,
            "source_tile_path",
        ] = metadata["tile_path"]

    return result, coordinate_errors


def save_errors_csv(
    errors: list[dict[str, Any]],
    output_path: Path,
) -> Path:
    """Guarda errores de georreferenciación."""

    error_table = pd.DataFrame(errors)

    error_table.to_csv(
        output_path,
        index=False,
        encoding="utf-8-sig",
    )

    return output_path


def save_result_csv(
    detections: pd.DataFrame,
    output_path: Path,
) -> Path:
    """Guarda el CSV mediante un archivo temporal."""

    temporary_path = output_path.with_suffix(
        ".partial.csv"
    )

    try:
        detections.to_csv(
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

    return output_path


def save_report(
    result: GeoreferencingResult,
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


def georeference_raw_detections(
    detections_csv: str | Path,
    tiles_directory: str | Path,
    output_dir: str | Path | None = None,
) -> GeoreferencingResult:
    """Transforma centros YOLO a coordenadas geográficas."""

    started_at = datetime.now().isoformat(
        timespec="seconds"
    )

    start_time = time.perf_counter()

    normalized_detections_csv = Path(
        detections_csv
    ).expanduser().resolve(strict=False)

    normalized_tiles_directory = Path(
        tiles_directory
    ).expanduser().resolve(strict=False)

    result = GeoreferencingResult(
        success=False,
        started_at=started_at,
        finished_at=None,
        detections_csv=str(
            normalized_detections_csv
        ),
        tiles_directory=str(
            normalized_tiles_directory
        ),
    )

    result.errors.extend(
        validate_input_paths(
            detections_csv=(
                normalized_detections_csv
            ),
            tiles_directory=(
                normalized_tiles_directory
            ),
        )
    )

    output_directory = resolve_output_directory(
        detections_csv=(
            normalized_detections_csv
        ),
        output_dir=output_dir,
    )

    output_directory.mkdir(
        parents=True,
        exist_ok=True,
    )

    output_csv_path = (
        output_directory
        / "detections_georeferenced_raw.csv"
    )

    errors_csv_path = (
        output_directory
        / "georeferencing_errors.csv"
    )

    report_path = (
        output_directory
        / "georeferencing_report.json"
    )

    if output_csv_path.exists():
        result.errors.append(
            "La salida ya existe y no será "
            f"sobrescrita: {output_csv_path}"
        )

    if result.errors:
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

    try:
        detections = load_detections(
            normalized_detections_csv
        )

        result.errors.extend(
            validate_required_columns(
                detections
            )
        )

        if result.errors:
            raise ValueError(
                "El CSV no tiene la estructura requerida."
            )

        detections, numeric_errors = (
            normalize_numeric_columns(
                detections
            )
        )

        if numeric_errors:
            save_errors_csv(
                errors=numeric_errors,
                output_path=errors_csv_path,
            )

            result.errors_csv = str(
                errors_csv_path
            )

            raise ValueError(
                "Existen coordenadas de píxel "
                "vacías o no numéricas."
            )

        tile_metadata, tile_errors = (
            load_all_tile_metadata(
                detections=detections,
                tiles_directory=(
                    normalized_tiles_directory
                ),
            )
        )

        if tile_errors:
            save_errors_csv(
                errors=tile_errors,
                output_path=errors_csv_path,
            )

            result.errors_csv = str(
                errors_csv_path
            )

            raise ValueError(
                "Uno o más tiles no pudieron "
                "validarse geográficamente."
            )

        georeferenced, coordinate_errors = (
            transform_detection_coordinates(
                detections=detections,
                tile_metadata=tile_metadata,
            )
        )

        if coordinate_errors:
            save_errors_csv(
                errors=coordinate_errors,
                output_path=errors_csv_path,
            )

            result.errors_csv = str(
                errors_csv_path
            )

            raise ValueError(
                "Una o más detecciones no pudieron "
                "transformarse correctamente."
            )

        invalid_coordinates = (
            georeferenced["coord_x"].isna()
            | georeferenced["coord_y"].isna()
        )

        if invalid_coordinates.any():
            raise ValueError(
                "La salida contiene coordenadas "
                "geográficas vacías."
            )

        save_result_csv(
            detections=georeferenced,
            output_path=output_csv_path,
        )

        result.output_csv = str(
            output_csv_path
        )

        epsg_values = sorted(
            {
                int(value)
                for value
                in georeferenced[
                    "epsg"
                ].dropna()
            }
        )

        coordinate_bounds = None

        if not georeferenced.empty:
            coordinate_bounds = {
                "min_x": float(
                    georeferenced[
                        "coord_x"
                    ].min()
                ),
                "min_y": float(
                    georeferenced[
                        "coord_y"
                    ].min()
                ),
                "max_x": float(
                    georeferenced[
                        "coord_x"
                    ].max()
                ),
                "max_y": float(
                    georeferenced[
                        "coord_y"
                    ].max()
                ),
            }

        elapsed_seconds = round(
            time.perf_counter() - start_time,
            3,
        )

        result.metadata = {
            "input_rows": int(
                len(detections)
            ),
            "output_rows": int(
                len(georeferenced)
            ),
            "unique_tiles_used": int(
                georeferenced[
                    "tile_file"
                ].nunique()
            ),
            "epsg_values": epsg_values,
            "coordinate_bounds": (
                coordinate_bounds
            ),
            "georeferencing_method": (
                "continuous_pixel_coordinates_"
                "through_tile_affine_transform"
            ),
            "elapsed_seconds": (
                elapsed_seconds
            ),
        }

        if len(epsg_values) != 1:
            result.warnings.append(
                "La salida contiene más de un EPSG "
                "o no fue posible identificarlo."
            )

        result.success = True

    except Exception as error:
        result.errors.append(
            "No fue posible georreferenciar "
            "las detecciones: "
            f"{type(error).__name__}: {error}"
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


def print_georeferencing_summary(
    result: GeoreferencingResult,
) -> None:
    """Muestra el resultado en la terminal."""

    print("=" * 72)
    print("GEORREFERENCIACIÓN DE DETECCIONES YOLO")
    print("=" * 72)

    print(
        f"CSV de entrada: {result.detections_csv}"
    )

    print(
        f"Tiles: {result.tiles_directory}"
    )

    print(
        "Estado: "
        f"{'COMPLETADO' if result.success else 'ERROR'}"
    )

    if result.metadata:
        print(
            "Detecciones de entrada: "
            f"{result.metadata['input_rows']}"
        )

        print(
            "Detecciones georreferenciadas: "
            f"{result.metadata['output_rows']}"
        )

        print(
            "Tiles utilizados: "
            f"{result.metadata['unique_tiles_used']}"
        )

        print(
            "EPSG: "
            f"{result.metadata['epsg_values']}"
        )

        print(
            "Tiempo: "
            f"{result.metadata['elapsed_seconds']} "
            "segundos"
        )

    if result.output_csv:
        print(
            "CSV georreferenciado: "
            f"{result.output_csv}"
        )

    if result.errors_csv:
        print(
            "CSV de errores: "
            f"{result.errors_csv}"
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
            "\nInforme: "
            f"{result.report_path}"
        )

    print("=" * 72)


def run_detection_georeferencing(
    detections_csv: str | Path,
    tiles_directory: str | Path,
    output_dir: str | Path | None = None,
) -> int:
    """Ejecuta la georreferenciación desde main.py."""

    result = georeference_raw_detections(
        detections_csv=detections_csv,
        tiles_directory=tiles_directory,
        output_dir=output_dir,
    )

    print_georeferencing_summary(
        result
    )

    return 0 if result.success else 1