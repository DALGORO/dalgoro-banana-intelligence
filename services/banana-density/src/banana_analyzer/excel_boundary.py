from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

import geopandas as gpd
import pandas as pd
import rasterio
from pyproj import CRS
from shapely.geometry import Polygon, box
from shapely.validation import explain_validity


PROJECT_ROOT = Path(__file__).resolve().parents[2]
LOGS_DIRECTORY = PROJECT_ROOT / "logs"

SUPPORTED_EXCEL_EXTENSIONS = {
    ".xls",
    ".xlsx",
    ".xlsm",
}

X_COLUMN_ALIASES = {
    "x",
    "coord_x",
    "coordenada_x",
    "coordenadax",
    "este",
    "easting",
    "utm_x",
    "utmx",
}

Y_COLUMN_ALIASES = {
    "y",
    "coord_y",
    "coordenada_y",
    "coordenaday",
    "norte",
    "northing",
    "utm_y",
    "utmy",
}

ORDER_COLUMN_ALIASES = {
    "orden",
    "order",
    "secuencia",
    "sequence",
    "vertice",
    "vertex",
    "punto",
    "point",
    "numero",
    "n",
}

EPSG_COLUMN_ALIASES = {
    "epsg",
    "crs",
    "codigo_epsg",
    "sistema_coordenadas",
}


@dataclass
class BoundaryValidationResult:
    """Resultado de la validación del límite leído desde Excel."""

    valid: bool
    checked_at: str
    excel_path: str
    raster_path: str
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


def normalize_column_name(column_name: object) -> str:
    """
    Normaliza un encabezado para reconocer variaciones de nombres.

    Ejemplos:
        Coordenada X -> coordenada_x
        COORD_X      -> coord_x
        Este (m)     -> este_m
    """

    text = str(column_name).strip().lower()

    text = unicodedata.normalize("NFKD", text)
    text = "".join(
        character
        for character in text
        if not unicodedata.combining(character)
    )

    text = re.sub(r"[^a-z0-9]+", "_", text)
    text = text.strip("_")

    return text


def detect_column(
    columns: list[object],
    aliases: set[str],
) -> object | None:
    """Busca una columna utilizando nombres alternativos."""

    normalized_columns = {
        normalize_column_name(column): column
        for column in columns
    }

    for alias in aliases:
        if alias in normalized_columns:
            return normalized_columns[alias]

    return None


def parse_sheet_reference(sheet_reference: str | int) -> str | int:
    """Convierte '0' en el índice numérico 0."""

    if isinstance(sheet_reference, int):
        return sheet_reference

    text = str(sheet_reference).strip()

    if text.isdigit():
        return int(text)

    return text


def select_excel_engine(excel_path: Path) -> str:
    """Selecciona el lector apropiado según la extensión."""

    if excel_path.suffix.lower() == ".xls":
        return "xlrd"

    return "openpyxl"


def read_excel_table(
    excel_path: Path,
    sheet_reference: str | int,
) -> pd.DataFrame:
    """Lee la tabla Excel sin modificar el archivo."""

    engine = select_excel_engine(excel_path)
    sheet_name = parse_sheet_reference(sheet_reference)

    return pd.read_excel(
        excel_path,
        sheet_name=sheet_name,
        engine=engine,
    )


def remove_consecutive_duplicate_points(
    coordinates: list[tuple[float, float]],
) -> list[tuple[float, float]]:
    """Elimina puntos consecutivos exactamente iguales."""

    cleaned_coordinates: list[tuple[float, float]] = []

    for coordinate in coordinates:
        if (
            not cleaned_coordinates
            or coordinate != cleaned_coordinates[-1]
        ):
            cleaned_coordinates.append(coordinate)

    if (
        len(cleaned_coordinates) > 1
        and cleaned_coordinates[0] == cleaned_coordinates[-1]
    ):
        cleaned_coordinates.pop()

    return cleaned_coordinates


def get_excel_epsg(
    table: pd.DataFrame,
    epsg_column: object | None,
) -> tuple[int | None, list[str]]:
    """Obtiene un código EPSG único desde la hoja."""

    errors: list[str] = []

    if epsg_column is None:
        return None, errors

    values = pd.to_numeric(
        table[epsg_column],
        errors="coerce",
    ).dropna()

    unique_values = sorted(
        {
            int(value)
            for value in values
        }
    )

    if len(unique_values) == 0:
        return None, errors

    if len(unique_values) > 1:
        errors.append(
            "La columna EPSG contiene más de un código diferente: "
            f"{unique_values}."
        )

        return None, errors

    return unique_values[0], errors


def coordinates_are_metric(crs: CRS) -> bool:
    """Comprueba si los ejes del CRS utilizan metros."""

    if not crs.is_projected:
        return False

    unit_names = [
        axis.unit_name.lower()
        for axis in crs.axis_info
        if axis.unit_name
    ]

    if not unit_names:
        return False

    return all(
        "metre" in unit_name
        or "meter" in unit_name
        for unit_name in unit_names
    )


def load_boundary_from_excel(
    excel_path: str | Path,
    raster_path: str | Path,
    sheet_reference: str | int = 0,
) -> tuple[
    BoundaryValidationResult,
    gpd.GeoDataFrame | None,
]:
    """
    Lee coordenadas X/Y y construye un polígono.

    El polígono se devuelve en el mismo CRS de la ortofoto.
    No se guarda todavía como archivo vectorial.
    """

    normalized_excel_path = Path(
        excel_path
    ).expanduser().resolve(strict=False)

    normalized_raster_path = Path(
        raster_path
    ).expanduser().resolve(strict=False)

    result = BoundaryValidationResult(
        valid=False,
        checked_at=datetime.now().isoformat(
            timespec="seconds"
        ),
        excel_path=str(normalized_excel_path),
        raster_path=str(normalized_raster_path),
    )

    if not normalized_excel_path.exists():
        result.errors.append(
            "El archivo Excel no existe."
        )

        return result, None

    if not normalized_excel_path.is_file():
        result.errors.append(
            "La ruta de Excel no corresponde a un archivo."
        )

        return result, None

    if (
        normalized_excel_path.suffix.lower()
        not in SUPPORTED_EXCEL_EXTENSIONS
    ):
        result.errors.append(
            "El archivo debe tener extensión "
            ".xls, .xlsx o .xlsm."
        )

        return result, None

    if not normalized_raster_path.exists():
        result.errors.append(
            "La ortofoto indicada no existe."
        )

        return result, None

    try:
        table = read_excel_table(
            normalized_excel_path,
            sheet_reference,
        )
    except Exception as error:
        result.errors.append(
            "No se pudo leer el archivo Excel: "
            f"{type(error).__name__}: {error}"
        )

        return result, None

    if table.empty:
        result.errors.append(
            "La hoja Excel seleccionada está vacía."
        )

        return result, None

    x_column = detect_column(
        list(table.columns),
        X_COLUMN_ALIASES,
    )

    y_column = detect_column(
        list(table.columns),
        Y_COLUMN_ALIASES,
    )

    order_column = detect_column(
        list(table.columns),
        ORDER_COLUMN_ALIASES,
    )

    epsg_column = detect_column(
        list(table.columns),
        EPSG_COLUMN_ALIASES,
    )

    if x_column is None:
        result.errors.append(
            "No se encontró una columna reconocible para X."
        )

    if y_column is None:
        result.errors.append(
            "No se encontró una columna reconocible para Y."
        )

    if result.errors:
        result.metadata["columnas_disponibles"] = [
            str(column)
            for column in table.columns
        ]

        return result, None

    working_table = table.copy()

    working_table["_excel_row"] = (
        working_table.index + 2
    )

    completely_empty = (
        working_table[x_column].isna()
        & working_table[y_column].isna()
    )

    working_table = working_table.loc[
        ~completely_empty
    ].copy()

    working_table["_x_numeric"] = pd.to_numeric(
        working_table[x_column],
        errors="coerce",
    )

    working_table["_y_numeric"] = pd.to_numeric(
        working_table[y_column],
        errors="coerce",
    )

    invalid_coordinate_rows = working_table.loc[
        working_table["_x_numeric"].isna()
        | working_table["_y_numeric"].isna(),
        "_excel_row",
    ].tolist()

    if invalid_coordinate_rows:
        result.errors.append(
            "Existen coordenadas vacías o no numéricas "
            "en las filas de Excel: "
            f"{invalid_coordinate_rows}."
        )

        return result, None

    if order_column is not None:
        working_table["_order_numeric"] = pd.to_numeric(
            working_table[order_column],
            errors="coerce",
        )

        invalid_order_rows = working_table.loc[
            working_table["_order_numeric"].isna(),
            "_excel_row",
        ].tolist()

        if invalid_order_rows:
            result.errors.append(
                "La columna de orden contiene valores "
                "vacíos o no numéricos en las filas: "
                f"{invalid_order_rows}."
            )

            return result, None

        duplicated_orders = working_table.loc[
            working_table["_order_numeric"].duplicated(
                keep=False
            ),
            "_order_numeric",
        ].tolist()

        if duplicated_orders:
            result.errors.append(
                "La columna de orden contiene valores "
                "repetidos: "
                f"{duplicated_orders}."
            )

            return result, None

        working_table = working_table.sort_values(
            "_order_numeric"
        )
    else:
        result.warnings.append(
            "No se encontró una columna ORDEN. "
            "Se utilizará exactamente el orden de las "
            "filas del archivo Excel."
        )

    coordinates = [
        (float(x_value), float(y_value))
        for x_value, y_value in zip(
            working_table["_x_numeric"],
            working_table["_y_numeric"],
            strict=True,
        )
    ]

    coordinates = remove_consecutive_duplicate_points(
        coordinates
    )

    unique_coordinates = set(coordinates)

    if len(unique_coordinates) < 3:
        result.errors.append(
            "Se requieren al menos tres coordenadas "
            "diferentes para construir un polígono."
        )

        return result, None

    polygon = Polygon(coordinates)

    if polygon.is_empty:
        result.errors.append(
            "El polígono generado está vacío."
        )

        return result, None

    if polygon.area <= 0:
        result.errors.append(
            "El polígono generado tiene un área igual a cero."
        )

        return result, None

    if not polygon.is_valid:
        result.errors.append(
            "El orden de los puntos produce una geometría "
            f"inválida: {explain_validity(polygon)}"
        )

        return result, None

    excel_epsg, epsg_errors = get_excel_epsg(
        working_table,
        epsg_column,
    )

    result.errors.extend(epsg_errors)

    if result.errors:
        return result, None

    try:
        with rasterio.open(
            normalized_raster_path
        ) as raster_source:
            raster_crs = raster_source.crs

            if raster_crs is None:
                result.errors.append(
                    "La ortofoto no tiene CRS."
                )

                return result, None

            raster_pyproj_crs = CRS.from_user_input(
                raster_crs
            )

            if excel_epsg is not None:
                coordinate_crs = CRS.from_epsg(
                    excel_epsg
                )
            else:
                coordinate_crs = raster_pyproj_crs

                result.warnings.append(
                    "El Excel no contiene una columna EPSG. "
                    "Se utilizará el CRS de la ortofoto: "
                    f"{raster_crs.to_string()}."
                )

            boundary = gpd.GeoDataFrame(
                {
                    "boundary_id": [1],
                    "source": [
                        normalized_excel_path.name
                    ],
                },
                geometry=[polygon],
                crs=coordinate_crs,
            )

            if coordinate_crs != raster_pyproj_crs:
                result.warnings.append(
                    "Las coordenadas Excel utilizan un CRS "
                    "diferente al raster. El polígono fue "
                    "reproyectado al CRS de la ortofoto."
                )

                boundary = boundary.to_crs(
                    raster_pyproj_crs
                )

            raster_extent = box(
                raster_source.bounds.left,
                raster_source.bounds.bottom,
                raster_source.bounds.right,
                raster_source.bounds.top,
            )

            boundary_geometry = boundary.geometry.iloc[0]

            if not boundary_geometry.intersects(
                raster_extent
            ):
                result.errors.append(
                    "El polígono generado no interseca "
                    "la extensión de la ortofoto. Revise "
                    "las coordenadas, el orden o el EPSG."
                )

                return result, None

            intersection_area = (
                boundary_geometry
                .intersection(raster_extent)
                .area
            )

            coverage_ratio = (
                intersection_area
                / boundary_geometry.area
            )

            if coverage_ratio < 0.999:
                result.warnings.append(
                    "Una parte del polígono se encuentra "
                    "fuera de la extensión de la ortofoto. "
                    f"Cobertura aproximada: "
                    f"{coverage_ratio * 100:.2f} %."
                )

            boundary_area = float(
                boundary_geometry.area
            )

            area_hectares: float | None = None

            if coordinates_are_metric(
                raster_pyproj_crs
            ):
                area_hectares = (
                    boundary_area / 10000
                )
            else:
                result.warnings.append(
                    "El CRS no utiliza metros. No se puede "
                    "calcular el área en hectáreas de forma "
                    "directa."
                )

            result.metadata = {
                "hoja": str(sheet_reference),
                "filas_leidas": int(len(table)),
                "vertices_utilizados": len(coordinates),
                "columna_x": str(x_column),
                "columna_y": str(y_column),
                "columna_orden": (
                    str(order_column)
                    if order_column is not None
                    else None
                ),
                "columna_epsg": (
                    str(epsg_column)
                    if epsg_column is not None
                    else None
                ),
                "epsg_excel": excel_epsg,
                "crs_resultado": (
                    raster_crs.to_string()
                ),
                "geometria_valida": bool(
                    boundary_geometry.is_valid
                ),
                "area_unidades_crs": round(
                    boundary_area,
                    4,
                ),
                "area_hectareas": (
                    round(area_hectares, 4)
                    if area_hectares is not None
                    else None
                ),
                "porcentaje_dentro_ortofoto": round(
                    coverage_ratio * 100,
                    4,
                ),
                "limites_poligono": {
                    "min_x": float(
                        boundary_geometry.bounds[0]
                    ),
                    "min_y": float(
                        boundary_geometry.bounds[1]
                    ),
                    "max_x": float(
                        boundary_geometry.bounds[2]
                    ),
                    "max_y": float(
                        boundary_geometry.bounds[3]
                    ),
                },
            }

    except Exception as error:
        result.errors.append(
            "No fue posible comparar el polígono "
            "con la ortofoto: "
            f"{type(error).__name__}: {error}"
        )

        return result, None

    result.valid = len(result.errors) == 0

    return result, boundary


def save_boundary_validation_report(
    result: BoundaryValidationResult,
) -> Path:
    """Guarda el informe del límite en JSON."""

    LOGS_DIRECTORY.mkdir(
        parents=True,
        exist_ok=True,
    )

    timestamp = datetime.now().strftime(
        "%Y%m%d_%H%M%S"
    )

    excel_name = (
        Path(result.excel_path).stem
        or "coordenadas"
    )

    output_path = (
        LOGS_DIRECTORY
        / (
            f"boundary_validation_"
            f"{excel_name}_{timestamp}.json"
        )
    )

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


def print_boundary_summary(
    result: BoundaryValidationResult,
    report_path: Path,
) -> None:
    """Muestra el resultado en la terminal."""

    print("=" * 72)
    print("VALIDACIÓN DEL LÍMITE DESDE EXCEL")
    print("=" * 72)

    print(f"Excel: {result.excel_path}")
    print(f"Ortofoto: {result.raster_path}")

    print(
        "Estado: "
        f"{'VÁLIDO' if result.valid else 'NO VÁLIDO'}"
    )

    if result.metadata:
        print(
            "Columnas X/Y: "
            f"{result.metadata['columna_x']} / "
            f"{result.metadata['columna_y']}"
        )

        print(
            "Vértices utilizados: "
            f"{result.metadata['vertices_utilizados']}"
        )

        print(
            "CRS resultante: "
            f"{result.metadata['crs_resultado']}"
        )

        print(
            "Área: "
            f"{result.metadata['area_hectareas']} ha"
        )

        print(
            "Polígono dentro de la ortofoto: "
            f"{result.metadata['porcentaje_dentro_ortofoto']} %"
        )

    if result.errors:
        print("\nERRORES:")

        for error in result.errors:
            print(f"  - {error}")

    if result.warnings:
        print("\nADVERTENCIAS:")

        for warning in result.warnings:
            print(f"  - {warning}")

    print(f"\nInforme guardado en: {report_path}")
    print("=" * 72)


def run_boundary_validation(
    excel_path: str | Path,
    raster_path: str | Path,
    sheet_reference: str | int = 0,
) -> int:
    """Ejecuta la validación desde la aplicación."""

    result, _boundary = load_boundary_from_excel(
        excel_path=excel_path,
        raster_path=raster_path,
        sheet_reference=sheet_reference,
    )

    report_path = save_boundary_validation_report(
        result
    )

    print_boundary_summary(
        result,
        report_path,
    )

    return 0 if result.valid else 1