from __future__ import annotations

import argparse
import re
import sys
import unicodedata
from pathlib import Path
from typing import Any

import yaml


BUILD_ID = "BANANA_CONFIG_WIZARD_V1_20260717"
PROJECT_ROOT = Path(__file__).resolve().parent
CONFIG_DIRECTORY = PROJECT_ROOT / "config"

DEFAULT_SPATIAL_CONFIG = (
    PROJECT_ROOT / "config" / "spatial_analysis.yaml"
)
DEFAULT_CARTOGRAPHY_CONFIG = (
    PROJECT_ROOT / "config" / "cartography.yaml"
)
DEFAULT_REPORT_CONFIG = (
    PROJECT_ROOT / "config" / "report.yaml"
)
DEFAULT_MODEL_PATH = (
    PROJECT_ROOT.parent
    / "runs"
    / "detect"
    / "banano_v3"
    / "weights"
    / "best.pt"
)


def sanitize_name(value: str) -> str:
    """Convierte un nombre en una identificación segura."""

    normalized = unicodedata.normalize("NFKD", value)
    normalized = "".join(
        character
        for character in normalized
        if not unicodedata.combining(character)
    )
    normalized = re.sub(
        r"[^A-Za-z0-9_-]+",
        "_",
        normalized,
    )
    normalized = normalized.strip("_")
    return normalized or "NUEVA_FINCA"


def normalize_path(value: str) -> Path:
    """Normaliza una ruta escrita por el usuario."""

    cleaned = value.strip().strip('"').strip("'")
    return Path(cleaned).expanduser().resolve(strict=False)


def prompt_text(
    label: str,
    *,
    default: str | None = None,
    required: bool = True,
) -> str:
    """Solicita texto mediante consola."""

    while True:
        suffix = f" [{default}]" if default not in (None, "") else ""
        answer = input(f"{label}{suffix}: ").strip()

        if not answer and default is not None:
            answer = default

        if answer or not required:
            return answer

        print("Este dato es obligatorio.")


def prompt_float(
    label: str,
    *,
    default: float | None = None,
    minimum: float | None = None,
) -> float:
    """Solicita un número decimal válido."""

    while True:
        default_text = (
            str(default)
            if default is not None
            else None
        )
        answer = prompt_text(
            label,
            default=default_text,
        ).replace(",", ".")

        try:
            value = float(answer)
        except ValueError:
            print("Ingrese un número válido.")
            continue

        if minimum is not None and value < minimum:
            print(
                f"El valor debe ser igual o mayor que {minimum}."
            )
            continue

        return value


def prompt_existing_file(
    label: str,
    *,
    default: Path | None = None,
    extensions: tuple[str, ...] | None = None,
) -> Path:
    """Solicita una ruta existente con extensión controlada."""

    while True:
        default_text = str(default) if default is not None else None
        answer = prompt_text(
            label,
            default=default_text,
        )
        path = normalize_path(answer)

        if not path.is_file():
            print(f"No existe el archivo: {path}")
            continue

        if extensions:
            suffix = path.suffix.lower()

            if suffix not in extensions:
                print(
                    "Extensión no admitida. Se esperaba: "
                    + ", ".join(extensions)
                )
                continue

        return path


def read_yaml(path: Path) -> dict[str, Any]:
    """Lee una configuración YAML."""

    loaded = yaml.safe_load(
        path.read_text(encoding="utf-8")
    )

    if not isinstance(loaded, dict):
        raise ValueError(
            f"El archivo YAML no contiene un objeto válido: {path}"
        )

    return loaded


def validate_support_config(
    path: Path,
    *,
    minimum_version: int,
    section: str,
    branding_required: bool = False,
) -> None:
    """Valida una configuración técnica existente."""

    if not path.is_file():
        raise FileNotFoundError(
            f"No existe la configuración: {path}"
        )

    loaded = read_yaml(path)
    version = int(loaded.get("version", 0) or 0)

    if version < minimum_version:
        raise ValueError(
            f"{path.name} debe ser versión {minimum_version} "
            f"o superior. Versión encontrada: {version}."
        )

    section_data = loaded.get(section)

    if not isinstance(section_data, dict):
        raise ValueError(
            f"{path.name} debe contener la sección '{section}'."
        )

    if branding_required and not isinstance(
        section_data.get("branding"),
        dict,
    ):
        raise ValueError(
            f"{path.name} debe contener '{section}.branding'."
        )


def project_relative_or_absolute(path: Path) -> str:
    """Usa ruta relativa cuando el archivo está dentro del proyecto."""

    try:
        relative = path.relative_to(PROJECT_ROOT)
    except ValueError:
        return path.as_posix()

    return relative.as_posix()


def build_config(
    *,
    farm_name: str,
    producer: str,
    report_date: str | None,
    orthophoto_path: Path,
    boundary_excel_path: Path,
    boundary_sheet: str,
    target_density: float,
    model_path: Path,
    output_root: str,
    exclusions_gpkg: Path | None,
    exclusions_layer: str | None,
) -> dict[str, Any]:
    """Construye la configuración oficial de una finca."""

    density_value: int | float = (
        int(target_density)
        if float(target_density).is_integer()
        else float(target_density)
    )

    return {
        "version": 1,
        "analysis": {
            "farm_name": farm_name,
            "producer": producer,
            "author": "Ing. Darwin A. González Romero",
            "report_date": report_date or None,
            "orthophoto_path": orthophoto_path.as_posix(),
            "boundary_excel_path": (
                boundary_excel_path.as_posix()
            ),
            "boundary_sheet": boundary_sheet,
            "target_density_plants_ha": density_value,
            "model_path": model_path.as_posix(),
            "output_root": output_root,
            "exclusions_gpkg": (
                exclusions_gpkg.as_posix()
                if exclusions_gpkg is not None
                else None
            ),
            "exclusions_layer": exclusions_layer or None,
        },
        "parameters": {
            "tile_size": 640,
            "overlap": 128,
            "min_valid_percent": 0.0,
            "yolo_confidence": 0.40,
            "yolo_iou": 0.70,
            "yolo_imgsz": 640,
            "yolo_device": "auto",
            "max_detections": 1000,
            "yolo_limit": None,
            "deduplication_distance_m": 1.00,
            "kde_radius_m": None,
            "kde_pixel_size_m": 0.50,
        },
        "configs": {
            "spatial_analysis": project_relative_or_absolute(
                DEFAULT_SPATIAL_CONFIG
            ),
            "cartography": project_relative_or_absolute(
                DEFAULT_CARTOGRAPHY_CONFIG
            ),
            "report": project_relative_or_absolute(
                DEFAULT_REPORT_CONFIG
            ),
        },
        "pipeline": {
            "run_system_check": True,
            "run_boundary_validation": True,
        },
    }


def validate_generated_config(
    config: dict[str, Any],
) -> None:
    """Valida el contenido antes de escribirlo."""

    analysis = config["analysis"]

    if not str(analysis["farm_name"]).strip():
        raise ValueError("farm_name está vacío.")

    if float(analysis["target_density_plants_ha"]) <= 0:
        raise ValueError(
            "target_density_plants_ha debe ser mayor que cero."
        )

    for field in (
        "orthophoto_path",
        "boundary_excel_path",
        "model_path",
    ):
        path = Path(str(analysis[field]))

        if not path.is_file():
            raise FileNotFoundError(
                f"No existe analysis.{field}: {path}"
            )

    has_exclusion_file = bool(
        analysis.get("exclusions_gpkg")
    )
    has_exclusion_layer = bool(
        analysis.get("exclusions_layer")
    )

    if has_exclusion_file != has_exclusion_layer:
        raise ValueError(
            "exclusions_gpkg y exclusions_layer deben "
            "proporcionarse juntos."
        )

    validate_support_config(
        DEFAULT_SPATIAL_CONFIG,
        minimum_version=6,
        section="kde",
    )
    validate_support_config(
        DEFAULT_CARTOGRAPHY_CONFIG,
        minimum_version=2,
        section="cartography",
        branding_required=True,
    )
    validate_support_config(
        DEFAULT_REPORT_CONFIG,
        minimum_version=2,
        section="report",
        branding_required=True,
    )


def save_config(
    config: dict[str, Any],
    output_path: Path,
    *,
    overwrite: bool,
) -> None:
    """Guarda la configuración sin sobrescribir por accidente."""

    output_path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    if output_path.exists() and not overwrite:
        raise FileExistsError(
            "La configuración ya existe. No fue reemplazada: "
            f"{output_path}"
        )

    temporary = output_path.with_suffix(
        output_path.suffix + ".partial"
    )

    try:
        temporary.write_text(
            yaml.safe_dump(
                config,
                allow_unicode=True,
                sort_keys=False,
                width=110,
            ),
            encoding="utf-8",
        )
        temporary.replace(output_path)
    finally:
        if temporary.exists():
            temporary.unlink()


def interactive_arguments() -> argparse.Namespace:
    """Solicita los datos necesarios para una nueva finca."""

    print("=" * 72)
    print("ASISTENTE DE CONFIGURACIÓN — NUEVA FINCA")
    print("=" * 72)

    farm_name = prompt_text(
        "Nombre de la finca o lote"
    )
    producer = prompt_text(
        "Productor o empresa",
        required=False,
    )
    orthophoto = prompt_existing_file(
        "Ruta de la ortofoto GeoTIFF",
        extensions=(".tif", ".tiff"),
    )
    boundary_excel = prompt_existing_file(
        "Ruta del Excel de coordenadas",
        extensions=(".xls", ".xlsx"),
    )
    boundary_sheet = prompt_text(
        "Nombre o posición de la hoja",
        default="Hoja1",
    )
    target_density = prompt_float(
        "Densidad objetivo (plantas/ha)",
        default=1400,
        minimum=1,
    )
    model_path = prompt_existing_file(
        "Ruta del modelo best.pt",
        default=(
            DEFAULT_MODEL_PATH
            if DEFAULT_MODEL_PATH.is_file()
            else None
        ),
        extensions=(".pt",),
    )
    report_date = prompt_text(
        "Fecha del informe DD/MM/AAAA "
        "(vacío = fecha automática)",
        required=False,
    )
    output_root = prompt_text(
        "Carpeta principal de ejecuciones",
        default="runs",
    )

    exclusions_answer = prompt_text(
        "Ruta de exclusiones GeoPackage "
        "(vacío = sin exclusiones)",
        required=False,
    )

    exclusions_gpkg: Path | None = None
    exclusions_layer: str | None = None

    if exclusions_answer:
        exclusions_gpkg = normalize_path(
            exclusions_answer
        )

        if (
            not exclusions_gpkg.is_file()
            or exclusions_gpkg.suffix.lower() != ".gpkg"
        ):
            raise FileNotFoundError(
                "La capa de exclusiones debe ser un "
                f"GeoPackage existente: {exclusions_gpkg}"
            )

        exclusions_layer = prompt_text(
            "Nombre de la capa dentro del GeoPackage"
        )

    safe_name = sanitize_name(farm_name)
    default_output = (
        CONFIG_DIRECTORY
        / f"pipeline_config_{safe_name}.yaml"
    )

    output_answer = prompt_text(
        "Archivo YAML de salida",
        default=str(default_output),
    )

    return argparse.Namespace(
        farm_name=farm_name,
        producer=producer,
        orthophoto=str(orthophoto),
        boundary_excel=str(boundary_excel),
        boundary_sheet=boundary_sheet,
        target_density=target_density,
        model=str(model_path),
        report_date=report_date,
        output_root=output_root,
        exclusions_gpkg=(
            str(exclusions_gpkg)
            if exclusions_gpkg is not None
            else None
        ),
        exclusions_layer=exclusions_layer,
        output=output_answer,
        overwrite=False,
    )


def build_parser() -> argparse.ArgumentParser:
    """Interfaz para uso automatizado o no interactivo."""

    parser = argparse.ArgumentParser(
        description=(
            "Crea una configuración reutilizable para "
            "analizar una nueva finca bananera."
        )
    )
    parser.add_argument("--farm-name")
    parser.add_argument("--producer", default="")
    parser.add_argument("--orthophoto")
    parser.add_argument("--boundary-excel")
    parser.add_argument(
        "--boundary-sheet",
        default="Hoja1",
    )
    parser.add_argument(
        "--target-density",
        type=float,
        default=1400,
    )
    parser.add_argument("--model")
    parser.add_argument(
        "--report-date",
        default=None,
    )
    parser.add_argument(
        "--output-root",
        default="runs",
    )
    parser.add_argument(
        "--exclusions-gpkg",
        default=None,
    )
    parser.add_argument(
        "--exclusions-layer",
        default=None,
    )
    parser.add_argument("--output")
    parser.add_argument(
        "--overwrite",
        action="store_true",
    )
    parser.add_argument(
        "--show-build",
        action="store_true",
    )
    return parser


def main() -> int:
    """Punto de entrada."""

    parser = build_parser()
    arguments = parser.parse_args()

    if arguments.show_build:
        print(BUILD_ID)
        return 0

    required_cli = (
        arguments.farm_name,
        arguments.orthophoto,
        arguments.boundary_excel,
        arguments.model,
        arguments.output,
    )

    if all(required_cli):
        active = arguments
    elif any(required_cli):
        parser.error(
            "Para uso no interactivo deben proporcionarse "
            "--farm-name, --orthophoto, --boundary-excel, "
            "--model y --output."
        )
    else:
        active = interactive_arguments()

    try:
        orthophoto = normalize_path(active.orthophoto)
        boundary_excel = normalize_path(
            active.boundary_excel
        )
        model = normalize_path(active.model)
        exclusions_gpkg = (
            normalize_path(active.exclusions_gpkg)
            if active.exclusions_gpkg
            else None
        )
        output = normalize_path(active.output)

        config = build_config(
            farm_name=str(active.farm_name).strip(),
            producer=str(active.producer).strip(),
            report_date=(
                str(active.report_date).strip()
                if active.report_date
                else None
            ),
            orthophoto_path=orthophoto,
            boundary_excel_path=boundary_excel,
            boundary_sheet=str(
                active.boundary_sheet
            ).strip(),
            target_density=float(
                active.target_density
            ),
            model_path=model,
            output_root=str(
                active.output_root
            ).strip(),
            exclusions_gpkg=exclusions_gpkg,
            exclusions_layer=(
                str(active.exclusions_layer).strip()
                if active.exclusions_layer
                else None
            ),
        )
        validate_generated_config(config)
        save_config(
            config,
            output,
            overwrite=bool(active.overwrite),
        )

        print("=" * 72)
        print("CONFIGURACIÓN CREADA")
        print("=" * 72)
        print(f"Build: {BUILD_ID}")
        print(f"Finca: {config['analysis']['farm_name']}")
        print(
            "Densidad: "
            f"{config['analysis']['target_density_plants_ha']} "
            "plantas/ha"
        )
        print(f"Archivo: {output}")
        print()
        print("Validar sin procesar:")
        print(
            f'python main.py run-full-analysis "{output}" '
            "--dry-run"
        )
        print()
        print("Ejecutar análisis:")
        print(
            f'python main.py run-full-analysis "{output}"'
        )
        print("=" * 72)
        return 0

    except Exception as error:
        print("=" * 72)
        print("NO SE CREÓ LA CONFIGURACIÓN")
        print("=" * 72)
        print(
            f"{type(error).__name__}: {error}"
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
