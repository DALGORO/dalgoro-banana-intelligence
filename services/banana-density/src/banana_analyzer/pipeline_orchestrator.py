from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Iterable

import yaml


PROJECT_ROOT = Path(__file__).resolve().parents[2]
MAIN_FILE = PROJECT_ROOT / "main.py"
DEFAULT_CONFIG_PATH = PROJECT_ROOT / "config" / "pipeline_config.yaml"

PIPELINE_BUILD = "BANANA_PIPELINE_ORCHESTRATOR_V1_20260717_R2_TILES"
PIPELINE_STATE_VERSION = 1

BOOTSTRAP_STAGE_KEYS = (
    "validate_environment",
    "validate_raster",
    "validate_boundary",
    "clip_raster",
)

PROCESS_STAGE_KEYS = (
    "generate_tiles",
    "run_yolo",
    "georeference_detections",
    "export_raw_gis",
    "deduplicate_detections",
    "calculate_statistics",
    "analyze_spatial_pattern",
    "generate_hex_density",
    "detect_planting_opportunities",
    "prioritize_planting_opportunities",
    "generate_kde_density",
    "generate_cartographic_package",
    "generate_technical_report",
)

ALL_STAGE_KEYS = BOOTSTRAP_STAGE_KEYS + PROCESS_STAGE_KEYS

STAGE_TITLES = {
    "validate_environment": "Verificación del entorno",
    "validate_raster": "Validación de la ortofoto",
    "validate_boundary": "Validación del límite",
    "clip_raster": "Recorte de la ortofoto",
    "generate_tiles": "Generación de tiles",
    "run_yolo": "Inferencia YOLO",
    "georeference_detections": "Georreferenciación",
    "export_raw_gis": "Exportación GIS preliminar",
    "deduplicate_detections": "Deduplicación",
    "calculate_statistics": "Estadísticas espaciales",
    "analyze_spatial_pattern": "Análisis del patrón espacial",
    "generate_hex_density": "Densidad por hexágonos",
    "detect_planting_opportunities": "Oportunidades geométricas de siembra",
    "prioritize_planting_opportunities": "Priorización operativa",
    "generate_kde_density": "Mapa continuo KDE",
    "generate_cartographic_package": "Paquete cartográfico",
    "generate_technical_report": "Informe técnico PDF",
}


@dataclass(frozen=True)
class PipelinePaths:
    """Rutas deterministas de una ejecución automática."""

    run: Path
    clipped: Path
    tiles: Path
    yolo: Path
    georeferenced: Path
    detections_clean: Path
    gis: Path
    raw_gis: Path
    spatial_pattern: Path
    hex_density: Path
    opportunities: Path
    priority: Path
    kde: Path
    maps: Path
    report: Path
    logs: Path
    temp: Path
    state_json: Path
    config_snapshot_yaml: Path
    config_snapshot_json: Path
    pipeline_manifest_json: Path


@dataclass(frozen=True)
class StageDefinition:
    """Define una etapa del flujo."""

    key: str
    title: str
    command_builder: Callable[["PipelineContext"], list[str]]
    validator: Callable[["PipelineContext"], tuple[bool, list[str]]]
    cleanup_targets: Callable[["PipelineContext"], list[Path]]


@dataclass
class PipelineContext:
    """Contexto normalizado utilizado por todas las etapas."""

    config_path: Path
    config: dict[str, Any]
    run_directory: Path
    paths: PipelinePaths
    target_density: float
    density_token: str
    state: dict[str, Any]


def now_iso() -> str:
    """Fecha y hora local en ISO sin microsegundos."""

    return datetime.now().isoformat(timespec="seconds")


def density_token(value: float) -> str:
    """Convierte la densidad en una identificación segura."""

    numeric = float(value)

    if numeric.is_integer():
        return str(int(numeric))

    text = f"{numeric:.4f}".rstrip("0").rstrip(".")
    return text.replace(".", "_")


def atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    """Escribe JSON mediante un archivo temporal."""

    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".partial")

    try:
        temporary.write_text(
            json.dumps(
                payload,
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        temporary.replace(path)
    finally:
        if temporary.exists():
            temporary.unlink()


def atomic_write_yaml(path: Path, payload: dict[str, Any]) -> None:
    """Escribe YAML mediante un archivo temporal."""

    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".partial")

    try:
        temporary.write_text(
            yaml.safe_dump(
                payload,
                allow_unicode=True,
                sort_keys=False,
                width=100,
            ),
            encoding="utf-8",
        )
        temporary.replace(path)
    finally:
        if temporary.exists():
            temporary.unlink()


def resolve_project_path(
    value: str | Path | None,
    *,
    config_directory: Path,
) -> Path | None:
    """Resuelve rutas absolutas o relativas al proyecto."""

    if value in (None, ""):
        return None

    expanded = os.path.expandvars(
        os.path.expanduser(str(value))
    )
    candidate = Path(expanded)

    if candidate.is_absolute():
        return candidate.resolve(strict=False)

    project_candidate = (
        PROJECT_ROOT / candidate
    ).resolve(strict=False)

    if project_candidate.exists():
        return project_candidate

    return (
        config_directory / candidate
    ).resolve(strict=False)


def read_yaml(path: Path) -> dict[str, Any]:
    """Lee un YAML y exige un diccionario raíz."""

    loaded = yaml.safe_load(
        path.read_text(encoding="utf-8")
    )

    if not isinstance(loaded, dict):
        raise ValueError(
            f"El archivo no contiene un objeto YAML válido: {path}"
        )

    return loaded


def validate_support_config(
    path: Path,
    *,
    minimum_version: int,
    required_section: str,
) -> None:
    """Comprueba la versión mínima de una configuración auxiliar."""

    loaded = read_yaml(path)
    version = int(loaded.get("version", 0) or 0)

    if version < minimum_version:
        raise ValueError(
            f"{path.name} debe tener versión {minimum_version} "
            f"o superior. Versión encontrada: {version}."
        )

    section = loaded.get(required_section)

    if not isinstance(section, dict):
        raise ValueError(
            f"{path.name} debe contener la sección "
            f"'{required_section}'."
        )


def load_pipeline_config(
    config_path: str | Path | None,
) -> tuple[Path, dict[str, Any]]:
    """Carga y normaliza la configuración completa del análisis."""

    requested = (
        DEFAULT_CONFIG_PATH
        if config_path is None
        else Path(config_path)
    )

    resolved = requested.expanduser().resolve(strict=False)

    if not resolved.is_file():
        raise FileNotFoundError(
            f"No existe la configuración del pipeline: {resolved}"
        )

    loaded = read_yaml(resolved)
    version = int(loaded.get("version", 0) or 0)

    if version != 1:
        raise ValueError(
            "La configuración del orquestador debe tener version: 1."
        )

    analysis = loaded.get("analysis")
    parameters = loaded.get("parameters")
    support_configs = loaded.get("configs")
    pipeline_options = loaded.get("pipeline", {})

    if not isinstance(analysis, dict):
        raise ValueError(
            "Falta la sección obligatoria 'analysis'."
        )

    if not isinstance(parameters, dict):
        raise ValueError(
            "Falta la sección obligatoria 'parameters'."
        )

    if not isinstance(support_configs, dict):
        raise ValueError(
            "Falta la sección obligatoria 'configs'."
        )

    if not isinstance(pipeline_options, dict):
        raise ValueError(
            "La sección 'pipeline' debe ser un objeto YAML."
        )

    config_directory = resolved.parent

    required_analysis = (
        "farm_name",
        "orthophoto_path",
        "boundary_excel_path",
        "boundary_sheet",
        "target_density_plants_ha",
        "model_path",
        "output_root",
    )

    missing = [
        key
        for key in required_analysis
        if analysis.get(key) in (None, "")
    ]

    if missing:
        raise ValueError(
            "Faltan datos obligatorios en analysis: "
            + ", ".join(missing)
        )

    normalized_analysis = dict(analysis)

    path_fields = (
        "orthophoto_path",
        "boundary_excel_path",
        "model_path",
        "output_root",
        "exclusions_gpkg",
    )

    for field in path_fields:
        if (
            field == "output_root"
            and analysis.get(field) not in (None, "")
        ):
            raw_output_root = Path(
                os.path.expandvars(
                    os.path.expanduser(
                        str(analysis[field])
                    )
                )
            )

            normalized = (
                raw_output_root.resolve(strict=False)
                if raw_output_root.is_absolute()
                else (
                    PROJECT_ROOT / raw_output_root
                ).resolve(strict=False)
            )
        else:
            normalized = resolve_project_path(
                analysis.get(field),
                config_directory=config_directory,
            )

        normalized_analysis[field] = (
            str(normalized)
            if normalized is not None
            else None
        )

    normalized_configs = dict(support_configs)

    for field in (
        "spatial_analysis",
        "cartography",
        "report",
    ):
        value = support_configs.get(field)

        if value in (None, ""):
            raise ValueError(
                f"Falta configs.{field}."
            )

        normalized = resolve_project_path(
            value,
            config_directory=config_directory,
        )
        normalized_configs[field] = str(normalized)

    normalized = {
        "version": 1,
        "analysis": normalized_analysis,
        "parameters": dict(parameters),
        "configs": normalized_configs,
        "pipeline": dict(pipeline_options),
    }

    validate_pipeline_config(normalized)
    return resolved, normalized


def validate_pipeline_config(config: dict[str, Any]) -> None:
    """Valida entradas, parámetros y configuraciones auxiliares."""

    analysis = config["analysis"]
    parameters = config["parameters"]
    support_configs = config["configs"]

    input_files = {
        "ortofoto": Path(analysis["orthophoto_path"]),
        "Excel del límite": Path(analysis["boundary_excel_path"]),
        "modelo YOLO": Path(analysis["model_path"]),
    }

    for label, path in input_files.items():
        if not path.is_file():
            raise FileNotFoundError(
                f"No existe {label}: {path}"
            )

    output_root = Path(analysis["output_root"])

    if output_root.exists() and not output_root.is_dir():
        raise ValueError(
            f"output_root no es una carpeta: {output_root}"
        )

    target_density = float(
        analysis["target_density_plants_ha"]
    )

    if target_density <= 0:
        raise ValueError(
            "target_density_plants_ha debe ser mayor que cero."
        )

    exclusions_gpkg = analysis.get("exclusions_gpkg")
    exclusions_layer = analysis.get("exclusions_layer")

    if bool(exclusions_gpkg) != bool(exclusions_layer):
        raise ValueError(
            "exclusions_gpkg y exclusions_layer deben "
            "proporcionarse juntos o dejarse ambos vacíos."
        )

    if exclusions_gpkg and not Path(exclusions_gpkg).is_file():
        raise FileNotFoundError(
            f"No existe la capa de exclusiones: {exclusions_gpkg}"
        )

    integer_positive = {
        "tile_size": 640,
        "overlap": 128,
        "yolo_imgsz": 640,
        "max_detections": 1000,
    }

    for key, default in integer_positive.items():
        value = int(parameters.get(key, default))

        if value <= 0 and key != "overlap":
            raise ValueError(
                f"parameters.{key} debe ser mayor que cero."
            )

        if key == "overlap" and value < 0:
            raise ValueError(
                "parameters.overlap no puede ser negativo."
            )

    tile_size = int(parameters.get("tile_size", 640))
    overlap = int(parameters.get("overlap", 128))

    if overlap >= tile_size:
        raise ValueError(
            "parameters.overlap debe ser menor que tile_size."
        )

    ranged_values = {
        "yolo_confidence": (0.0, 1.0, 0.40),
        "yolo_iou": (0.0, 1.0, 0.70),
    }

    for key, (minimum, maximum, default) in ranged_values.items():
        value = float(parameters.get(key, default))

        if not minimum <= value <= maximum:
            raise ValueError(
                f"parameters.{key} debe estar entre "
                f"{minimum} y {maximum}."
            )

    deduplication_distance = float(
        parameters.get(
            "deduplication_distance_m",
            1.00,
        )
    )

    if deduplication_distance <= 0:
        raise ValueError(
            "deduplication_distance_m debe ser mayor que cero."
        )

    support_paths = {
        key: Path(value)
        for key, value in support_configs.items()
    }

    for key, path in support_paths.items():
        if not path.is_file():
            raise FileNotFoundError(
                f"No existe configs.{key}: {path}"
            )

    validate_support_config(
        support_paths["spatial_analysis"],
        minimum_version=6,
        required_section="kde",
    )
    validate_support_config(
        support_paths["cartography"],
        minimum_version=2,
        required_section="cartography",
    )
    validate_support_config(
        support_paths["report"],
        minimum_version=2,
        required_section="report",
    )

    cartography = read_yaml(
        support_paths["cartography"]
    )["cartography"]
    report = read_yaml(
        support_paths["report"]
    )["report"]

    if not isinstance(
        cartography.get("branding"),
        dict,
    ):
        raise ValueError(
            "cartography.yaml versión 2 debe contener "
            "cartography.branding."
        )

    if not isinstance(report.get("branding"), dict):
        raise ValueError(
            "report.yaml versión 2 debe contener report.branding."
        )


def build_pipeline_paths(
    run_directory: Path,
    target_density: float,
) -> PipelinePaths:
    """Construye todas las rutas del escenario productivo."""

    token = density_token(target_density)
    gis = run_directory / "05_gis"

    return PipelinePaths(
        run=run_directory,
        clipped=run_directory / "01_recorte",
        tiles=run_directory / "02_tiles",
        yolo=(
            run_directory
            / "03_detecciones_raw"
            / "yolo"
        ),
        georeferenced=(
            run_directory
            / "03_detecciones_raw"
            / "georreferenciadas"
        ),
        detections_clean=(
            run_directory
            / "04_detecciones_limpias"
        ),
        gis=gis,
        raw_gis=gis / "detecciones_raw",
        spatial_pattern=gis / "analisis_espacial",
        hex_density=(
            gis
            / f"densidad_hexagonal_objetivo_{token}"
        ),
        opportunities=(
            gis
            / f"oportunidades_siembra_{token}"
        ),
        priority=(
            gis
            / f"prioridad_operativa_{token}"
        ),
        kde=gis / f"mapa_calor_kde_{token}",
        maps=(
            run_directory
            / "06_mapas"
            / f"paquete_cartografico_{token}_dalgoro_v2"
        ),
        report=(
            run_directory
            / "07_reporte"
            / f"informe_dalgoro_v2_{token}"
        ),
        logs=run_directory / "logs",
        temp=run_directory / "temp",
        state_json=run_directory / "estado_pipeline.json",
        config_snapshot_yaml=(
            run_directory / "configuracion_analisis.yaml"
        ),
        config_snapshot_json=(
            run_directory / "configuracion_analisis.json"
        ),
        pipeline_manifest_json=(
            run_directory / "manifiesto_pipeline.json"
        ),
    )


def critical_config(config: dict[str, Any]) -> dict[str, Any]:
    """Extrae parámetros que no deben cambiar al reanudar."""

    analysis = config["analysis"]
    parameters = config["parameters"]
    support_configs = config["configs"]

    return {
        "orthophoto_path": analysis["orthophoto_path"],
        "boundary_excel_path": analysis["boundary_excel_path"],
        "boundary_sheet": str(analysis["boundary_sheet"]),
        "target_density_plants_ha": float(
            analysis["target_density_plants_ha"]
        ),
        "model_path": analysis["model_path"],
        "exclusions_gpkg": analysis.get("exclusions_gpkg"),
        "exclusions_layer": analysis.get("exclusions_layer"),
        "tile_size": int(parameters.get("tile_size", 640)),
        "overlap": int(parameters.get("overlap", 128)),
        "min_valid_percent": float(
            parameters.get("min_valid_percent", 0.0)
        ),
        "yolo_confidence": float(
            parameters.get("yolo_confidence", 0.40)
        ),
        "yolo_iou": float(
            parameters.get("yolo_iou", 0.70)
        ),
        "yolo_imgsz": int(
            parameters.get("yolo_imgsz", 640)
        ),
        "yolo_device": str(
            parameters.get("yolo_device", "auto")
        ),
        "max_detections": int(
            parameters.get("max_detections", 1000)
        ),
        "deduplication_distance_m": float(
            parameters.get(
                "deduplication_distance_m",
                1.00,
            )
        ),
        "spatial_analysis_config": (
            support_configs["spatial_analysis"]
        ),
    }


def config_fingerprint(config: dict[str, Any]) -> str:
    """Hash reproducible de parámetros críticos."""

    encoded = json.dumps(
        critical_config(config),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")

    return hashlib.sha256(encoded).hexdigest()


def create_initial_state(
    config_path: Path,
    config: dict[str, Any],
    run_directory: Path,
) -> dict[str, Any]:
    """Crea el estado inicial después del recorte."""

    stages: dict[str, Any] = {}

    for key in ALL_STAGE_KEYS:
        stages[key] = {
            "title": STAGE_TITLES[key],
            "status": (
                "completed"
                if key in BOOTSTRAP_STAGE_KEYS
                else "pending"
            ),
            "started_at": None,
            "finished_at": None,
            "elapsed_seconds": None,
            "return_code": None,
            "log_path": None,
            "command": None,
            "validation_messages": [],
            "error": None,
        }

    return {
        "version": PIPELINE_STATE_VERSION,
        "pipeline_build": PIPELINE_BUILD,
        "created_at": now_iso(),
        "updated_at": now_iso(),
        "status": "running",
        "current_stage": None,
        "run_directory": str(run_directory),
        "source_config_path": str(config_path),
        "critical_config_fingerprint": config_fingerprint(config),
        "stages": stages,
        "artifacts": {},
        "warnings": [],
        "errors": [],
    }


def save_state(context: PipelineContext) -> None:
    """Guarda el estado y actualiza la fecha."""

    context.state["updated_at"] = now_iso()
    atomic_write_json(
        context.paths.state_json,
        context.state,
    )


def load_or_reconstruct_state(
    config_path: Path,
    config: dict[str, Any],
    run_directory: Path,
) -> dict[str, Any]:
    """Lee un estado existente o crea uno para una ejecución adoptada."""

    paths = build_pipeline_paths(
        run_directory,
        float(config["analysis"]["target_density_plants_ha"]),
    )

    if paths.state_json.is_file():
        loaded = json.loads(
            paths.state_json.read_text(encoding="utf-8")
        )

        if not isinstance(loaded, dict):
            raise ValueError(
                "estado_pipeline.json no contiene un objeto válido."
            )

        stored_fingerprint = loaded.get(
            "critical_config_fingerprint"
        )
        current_fingerprint = config_fingerprint(config)

        if (
            stored_fingerprint
            and stored_fingerprint != current_fingerprint
        ):
            raise ValueError(
                "La configuración crítica cambió desde el inicio "
                "de la ejecución. No se puede reanudar mezclando "
                "ortofotos, modelo, densidad o parámetros técnicos."
            )

        return loaded

    state = create_initial_state(
        config_path=config_path,
        config=config,
        run_directory=run_directory,
    )
    state["warnings"].append(
        "La ejecución no tenía estado previo. "
        "Se creó un estado para adopción y reanudación."
    )
    return state


def command_text(command: Iterable[str]) -> str:
    """Representación legible y segura del comando."""

    return subprocess.list2cmdline(
        [str(part) for part in command]
    )


def run_command(
    *,
    stage_key: str,
    title: str,
    command: list[str],
    log_path: Path,
) -> tuple[int, float]:
    """Ejecuta un comando hijo, muestra salida y conserva el log."""

    log_path.parent.mkdir(parents=True, exist_ok=True)
    started = time.perf_counter()

    print()
    print("=" * 78)
    print(f"ETAPA: {title}")
    print("=" * 78)
    print(command_text(command))
    print("-" * 78)

    environment = os.environ.copy()
    environment["PYTHONUTF8"] = "1"
    environment["PYTHONIOENCODING"] = "utf-8"

    with log_path.open(
        "w",
        encoding="utf-8",
        errors="replace",
    ) as log_file:
        log_file.write(
            f"PIPELINE_BUILD={PIPELINE_BUILD}\n"
        )
        log_file.write(
            f"STAGE={stage_key}\n"
        )
        log_file.write(
            f"STARTED_AT={now_iso()}\n"
        )
        log_file.write(
            f"COMMAND={command_text(command)}\n\n"
        )
        log_file.flush()

        process = subprocess.Popen(
            command,
            cwd=PROJECT_ROOT,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=environment,
        )

        assert process.stdout is not None

        for line in process.stdout:
            print(line, end="")
            log_file.write(line)
            log_file.flush()

        return_code = process.wait()
        elapsed = round(
            time.perf_counter() - started,
            3,
        )

        log_file.write(
            f"\nRETURN_CODE={return_code}\n"
        )
        log_file.write(
            f"ELAPSED_SECONDS={elapsed}\n"
        )
        log_file.write(
            f"FINISHED_AT={now_iso()}\n"
        )

    return return_code, elapsed


def validate_files(
    files: Iterable[Path],
) -> tuple[bool, list[str]]:
    """Valida archivos obligatorios y tamaño mayor que cero."""

    messages: list[str] = []
    success = True

    for path in files:
        if not path.is_file():
            success = False
            messages.append(
                f"No existe: {path}"
            )
            continue

        if path.stat().st_size <= 0:
            success = False
            messages.append(
                f"Archivo vacío: {path}"
            )

    return success, messages


def validate_glob_count(
    directory: Path,
    pattern: str,
    minimum: int,
) -> tuple[bool, list[str]]:
    """Valida una cantidad mínima de archivos."""

    matches = list(directory.rglob(pattern))

    if len(matches) < minimum:
        return False, [
            f"Se esperaban al menos {minimum} archivos "
            f"'{pattern}' en {directory}; se encontraron "
            f"{len(matches)}."
        ]

    empty = [
        path
        for path in matches
        if path.is_file() and path.stat().st_size <= 0
    ]

    if empty:
        return False, [
            "Se encontraron archivos vacíos: "
            + ", ".join(str(path) for path in empty[:5])
        ]

    return True, []


def read_success_json(
    path: Path,
) -> tuple[bool, list[str]]:
    """Comprueba un manifiesto JSON con success=true."""

    file_ok, messages = validate_files([path])

    if not file_ok:
        return False, messages

    try:
        loaded = json.loads(
            path.read_text(encoding="utf-8")
        )
    except Exception as error:
        return False, [
            f"No se pudo leer {path.name}: "
            f"{type(error).__name__}: {error}"
        ]

    if loaded.get("success") is not True:
        errors = loaded.get("errors") or []
        details = "; ".join(str(item) for item in errors)

        return False, [
            f"{path.name} registra success=false."
            + (f" {details}" if details else "")
        ]

    return True, []


def find_clipped_raster(paths: PipelinePaths) -> Path:
    """Localiza la ortofoto recortada."""

    preferred = sorted(
        paths.clipped.rglob("*_recortada.tif")
    )

    if preferred:
        return preferred[0]

    alternatives = sorted(
        paths.clipped.rglob("*.tif")
    )

    if not alternatives:
        raise FileNotFoundError(
            "No se encontró un GeoTIFF recortado en "
            f"{paths.clipped}."
        )

    return alternatives[0]


def exact_file(directory: Path, name: str) -> Path:
    """Devuelve una ruta exacta dentro de una etapa."""

    return directory / name


def find_tiles_directory(paths: PipelinePaths) -> Path:
    """
    Localiza la carpeta que contiene directamente los tiles.

    El módulo de tiling guarda normalmente los GeoTIFF en
    ``02_tiles/geotiff``. Los módulos YOLO y de georreferenciación
    requieren esa carpeta concreta, no solamente ``02_tiles``.
    """

    preferred_directories = (
        paths.tiles / "geotiff",
        paths.tiles,
    )

    for directory in preferred_directories:
        if not directory.is_dir():
            continue

        direct_tiles = list(directory.glob("*.tif"))
        direct_tiles.extend(directory.glob("*.tiff"))

        if direct_tiles:
            return directory

    recursive_tiles = list(paths.tiles.rglob("*.tif"))
    recursive_tiles.extend(paths.tiles.rglob("*.tiff"))

    if not recursive_tiles:
        raise FileNotFoundError(
            "No se encontraron tiles .tif o .tiff dentro de "
            f"{paths.tiles}."
        )

    counts_by_parent: dict[Path, int] = {}

    for tile_path in recursive_tiles:
        counts_by_parent[tile_path.parent] = (
            counts_by_parent.get(tile_path.parent, 0) + 1
        )

    return max(
        counts_by_parent,
        key=counts_by_parent.get,
    )


def validate_clipped(context: PipelineContext) -> tuple[bool, list[str]]:
    try:
        path = find_clipped_raster(context.paths)
    except FileNotFoundError as error:
        return False, [str(error)]

    return validate_files([path])


def validate_tiles(context: PipelineContext) -> tuple[bool, list[str]]:
    try:
        tiles_directory = find_tiles_directory(
            context.paths
        )
    except FileNotFoundError as error:
        return False, [str(error)]

    tiles = list(tiles_directory.glob("*.tif"))
    tiles.extend(tiles_directory.glob("*.tiff"))

    if not tiles:
        return False, [
            "La carpeta localizada no contiene tiles: "
            f"{tiles_directory}"
        ]

    empty_tiles = [
        tile
        for tile in tiles
        if tile.stat().st_size <= 0
    ]

    if empty_tiles:
        return False, [
            "Se encontraron tiles vacíos: "
            + ", ".join(
                str(path)
                for path in empty_tiles[:5]
            )
        ]

    return True, []


def validate_yolo(context: PipelineContext) -> tuple[bool, list[str]]:
    return validate_files(
        [
            exact_file(
                context.paths.yolo,
                "detections_raw.csv",
            )
        ]
    )


def validate_georeferenced(
    context: PipelineContext,
) -> tuple[bool, list[str]]:
    return validate_files(
        [
            exact_file(
                context.paths.georeferenced,
                "detections_georeferenced_raw.csv",
            )
        ]
    )


def validate_raw_gis(
    context: PipelineContext,
) -> tuple[bool, list[str]]:
    return validate_files(
        [
            exact_file(
                context.paths.raw_gis,
                "inventario_banano_raw.csv",
            ),
            exact_file(
                context.paths.raw_gis,
                "inventario_banano_raw.gpkg",
            ),
        ]
    )


def validate_deduplicated(
    context: PipelineContext,
) -> tuple[bool, list[str]]:
    return validate_files(
        [
            exact_file(
                context.paths.detections_clean,
                "detections_deduplicated.csv",
            )
        ]
    )


def validate_statistics(
    context: PipelineContext,
) -> tuple[bool, list[str]]:
    return validate_files(
        [
            context.paths.gis / "inventario_banano_validado.gpkg",
            context.paths.gis / "limite_analisis.gpkg",
            context.paths.gis / "estadisticas_banano.csv",
            context.paths.gis / "estadisticas_banano.json",
        ]
    )


def validate_spatial_pattern(
    context: PipelineContext,
) -> tuple[bool, list[str]]:
    return validate_files(
        [
            context.paths.spatial_pattern
            / "analisis_patron_espacial.json",
            context.paths.spatial_pattern
            / "analisis_patron_espacial.csv",
            context.paths.spatial_pattern
            / "patron_espacial_puntos.gpkg",
        ]
    )


def validate_hex_density(
    context: PipelineContext,
) -> tuple[bool, list[str]]:
    return validate_files(
        [
            context.paths.hex_density
            / "densidad_hexagonal.gpkg",
            context.paths.hex_density
            / "resumen_densidad_hexagonal.csv",
            context.paths.hex_density
            / "densidad_hexagonal.json",
        ]
    )


def validate_opportunities(
    context: PipelineContext,
) -> tuple[bool, list[str]]:
    base_ok, messages = validate_files(
        [
            context.paths.opportunities
            / "resumen_oportunidades_siembra.csv",
            context.paths.opportunities
            / "oportunidades_siembra.json",
            context.paths.opportunities
            / "candidatos_siembra.csv",
        ]
    )

    if not base_ok:
        return False, messages

    required_gpkg = [
        context.paths.opportunities
        / "zonas_oportunidad_siembra.gpkg",
        context.paths.opportunities
        / "candidatos_siembra.gpkg",
    ]
    gpkg_ok, gpkg_messages = validate_files(required_gpkg)

    if not gpkg_ok:
        return False, gpkg_messages + [
            "La priorización requiere por ahora al menos "
            "una zona y un candidato geométrico."
        ]

    return True, []


def validate_priority(
    context: PipelineContext,
) -> tuple[bool, list[str]]:
    return validate_files(
        [
            context.paths.priority
            / "candidatos_siembra_priorizados.gpkg",
            context.paths.priority
            / "zonas_prioridad_operativa.gpkg",
            context.paths.priority
            / "resumen_prioridad_operativa.csv",
            context.paths.priority
            / "prioridad_operativa.json",
        ]
    )


def validate_kde(
    context: PipelineContext,
) -> tuple[bool, list[str]]:
    return validate_files(
        [
            context.paths.kde
            / "densidad_kde_corregida_plantas_ha.tif",
            context.paths.kde
            / "densidad_kde_relativa.tif",
            context.paths.kde
            / "zonas_densidad_kde.gpkg",
            context.paths.kde
            / "resumen_mapa_calor_kde.csv",
            context.paths.kde
            / "mapa_calor_kde.json",
        ]
    )


def validate_maps(
    context: PipelineContext,
) -> tuple[bool, list[str]]:
    count_ok, messages = validate_glob_count(
        context.paths.maps,
        "*.png",
        6,
    )

    if not count_ok:
        return False, messages

    files_ok, file_messages = validate_files(
        [
            context.paths.maps / "indice_mapas.csv",
            context.paths.maps
            / "manifiesto_paquete_cartografico.json",
        ]
    )

    if not files_ok:
        return False, file_messages

    return read_success_json(
        context.paths.maps
        / "manifiesto_paquete_cartografico.json"
    )


def find_report_pdf(context: PipelineContext) -> Path | None:
    """Localiza el único PDF técnico de la etapa."""

    matches = sorted(
        context.paths.report.glob(
            "informe_tecnico_*.pdf"
        )
    )

    return matches[0] if matches else None


def validate_report(
    context: PipelineContext,
) -> tuple[bool, list[str]]:
    report_pdf = find_report_pdf(context)

    if report_pdf is None:
        return False, [
            f"No se encontró el PDF en {context.paths.report}."
        ]

    manifests = sorted(
        context.paths.report.glob(
            "manifiesto_informe_*.json"
        )
    )
    summaries = sorted(
        context.paths.report.glob(
            "resumen_informe_*.csv"
        )
    )

    if not manifests or not summaries:
        return False, [
            "Falta el manifiesto o el resumen CSV del informe."
        ]

    files_ok, messages = validate_files(
        [report_pdf, manifests[0], summaries[0]]
    )

    if not files_ok:
        return False, messages

    return read_success_json(manifests[0])


def command_base() -> list[str]:
    """Inicio estándar de todos los comandos internos."""

    return [
        sys.executable,
        str(MAIN_FILE),
    ]


def add_optional_exclusions(
    command: list[str],
    context: PipelineContext,
) -> list[str]:
    """Agrega la capa de exclusiones cuando existe."""

    analysis = context.config["analysis"]
    exclusions_gpkg = analysis.get("exclusions_gpkg")
    exclusions_layer = analysis.get("exclusions_layer")

    if exclusions_gpkg and exclusions_layer:
        command.extend(
            [
                "--exclusions-gpkg",
                str(exclusions_gpkg),
                "--exclusions-layer",
                str(exclusions_layer),
            ]
        )

    return command


def stage_definitions() -> list[StageDefinition]:
    """Construye las etapas posteriores al recorte."""

    def tiles_command(context: PipelineContext) -> list[str]:
        parameters = context.config["parameters"]

        return command_base() + [
            "generate-tiles",
            str(find_clipped_raster(context.paths)),
            "--tile-size",
            str(int(parameters.get("tile_size", 640))),
            "--overlap",
            str(int(parameters.get("overlap", 128))),
            "--min-valid-percent",
            str(
                float(
                    parameters.get(
                        "min_valid_percent",
                        0.0,
                    )
                )
            ),
            "--output-dir",
            str(context.paths.tiles),
        ]

    def yolo_command(context: PipelineContext) -> list[str]:
        analysis = context.config["analysis"]
        parameters = context.config["parameters"]

        tiles_directory = find_tiles_directory(
            context.paths
        )

        command = command_base() + [
            "run-yolo",
            str(tiles_directory),
            str(analysis["model_path"]),
            "--confidence",
            str(
                float(
                    parameters.get(
                        "yolo_confidence",
                        0.40,
                    )
                )
            ),
            "--iou",
            str(
                float(
                    parameters.get(
                        "yolo_iou",
                        0.70,
                    )
                )
            ),
            "--imgsz",
            str(
                int(
                    parameters.get(
                        "yolo_imgsz",
                        640,
                    )
                )
            ),
            "--device",
            str(
                parameters.get(
                    "yolo_device",
                    "auto",
                )
            ),
            "--max-det",
            str(
                int(
                    parameters.get(
                        "max_detections",
                        1000,
                    )
                )
            ),
            "--output-dir",
            str(context.paths.yolo),
        ]

        limit = parameters.get("yolo_limit")

        if limit not in (None, ""):
            command.extend(
                ["--limit", str(int(limit))]
            )

        return command

    def georeference_command(
        context: PipelineContext,
    ) -> list[str]:
        return command_base() + [
            "georeference-detections",
            str(
                context.paths.yolo
                / "detections_raw.csv"
            ),
            str(
                find_tiles_directory(
                    context.paths
                )
            ),
            "--output-dir",
            str(context.paths.georeferenced),
        ]

    def raw_gis_command(
        context: PipelineContext,
    ) -> list[str]:
        return command_base() + [
            "export-gis",
            str(
                context.paths.georeferenced
                / "detections_georeferenced_raw.csv"
            ),
            "--output-dir",
            str(context.paths.raw_gis),
            "--name-prefix",
            "inventario_banano_raw",
            "--layer-name",
            "detecciones_raw",
        ]

    def dedup_command(context: PipelineContext) -> list[str]:
        distance = float(
            context.config["parameters"].get(
                "deduplication_distance_m",
                1.00,
            )
        )

        return command_base() + [
            "deduplicate-detections",
            str(
                context.paths.georeferenced
                / "detections_georeferenced_raw.csv"
            ),
            "--distance",
            str(distance),
            "--output-dir",
            str(context.paths.detections_clean),
        ]

    def statistics_command(
        context: PipelineContext,
    ) -> list[str]:
        analysis = context.config["analysis"]

        return command_base() + [
            "calculate-statistics",
            str(
                context.paths.detections_clean
                / "detections_deduplicated.csv"
            ),
            str(analysis["boundary_excel_path"]),
            str(analysis["orthophoto_path"]),
            "--sheet",
            str(analysis["boundary_sheet"]),
            "--output-dir",
            str(context.paths.gis),
        ]

    def spatial_command(
        context: PipelineContext,
    ) -> list[str]:
        return command_base() + [
            "analyze-spatial-pattern",
            str(
                context.paths.gis
                / "inventario_banano_validado.gpkg"
            ),
            str(
                context.paths.gis
                / "limite_analisis.gpkg"
            ),
            "--config",
            str(
                context.config["configs"][
                    "spatial_analysis"
                ]
            ),
            "--output-dir",
            str(context.paths.spatial_pattern),
        ]

    def hex_command(context: PipelineContext) -> list[str]:
        return command_base() + [
            "generate-hex-density",
            str(
                context.paths.gis
                / "inventario_banano_validado.gpkg"
            ),
            str(
                context.paths.gis
                / "limite_analisis.gpkg"
            ),
            "--config",
            str(
                context.config["configs"][
                    "spatial_analysis"
                ]
            ),
            "--reference-density",
            str(context.target_density),
            "--output-dir",
            str(context.paths.hex_density),
        ]

    def opportunities_command(
        context: PipelineContext,
    ) -> list[str]:
        command = command_base() + [
            "detect-planting-opportunities",
            str(
                context.paths.gis
                / "inventario_banano_validado.gpkg"
            ),
            str(
                context.paths.gis
                / "limite_analisis.gpkg"
            ),
            "--target-density",
            str(context.target_density),
            "--config",
            str(
                context.config["configs"][
                    "spatial_analysis"
                ]
            ),
            "--output-dir",
            str(context.paths.opportunities),
        ]

        return add_optional_exclusions(
            command,
            context,
        )

    def priority_command(
        context: PipelineContext,
    ) -> list[str]:
        command = command_base() + [
            "prioritize-planting-opportunities",
            str(
                context.paths.hex_density
                / "densidad_hexagonal.gpkg"
            ),
            str(
                context.paths.opportunities
                / "candidatos_siembra.gpkg"
            ),
            str(
                context.paths.opportunities
                / "zonas_oportunidad_siembra.gpkg"
            ),
            "--target-density",
            str(context.target_density),
            "--config",
            str(
                context.config["configs"][
                    "spatial_analysis"
                ]
            ),
            "--output-dir",
            str(context.paths.priority),
        ]

        return add_optional_exclusions(
            command,
            context,
        )

    def kde_command(context: PipelineContext) -> list[str]:
        parameters = context.config["parameters"]

        command = command_base() + [
            "generate-kde-density",
            str(
                context.paths.gis
                / "inventario_banano_validado.gpkg"
            ),
            str(
                context.paths.gis
                / "limite_analisis.gpkg"
            ),
            "--target-density",
            str(context.target_density),
            "--spatial-report",
            str(
                context.paths.spatial_pattern
                / "analisis_patron_espacial.json"
            ),
            "--config",
            str(
                context.config["configs"][
                    "spatial_analysis"
                ]
            ),
            "--output-dir",
            str(context.paths.kde),
        ]

        radius = parameters.get("kde_radius_m")

        if radius not in (None, ""):
            command.extend(
                ["--radius", str(float(radius))]
            )

        pixel_size = parameters.get(
            "kde_pixel_size_m"
        )

        if pixel_size not in (None, ""):
            command.extend(
                [
                    "--pixel-size",
                    str(float(pixel_size)),
                ]
            )

        return command

    def maps_command(context: PipelineContext) -> list[str]:
        analysis = context.config["analysis"]

        return command_base() + [
            "generate-cartographic-package",
            str(context.paths.run),
            "--target-density",
            str(context.target_density),
            "--farm-name",
            str(analysis["farm_name"]),
            "--producer",
            str(analysis.get("producer", "")),
            "--author",
            str(
                analysis.get(
                    "author",
                    "Ing. Darwin A. González Romero",
                )
            ),
            "--config",
            str(
                context.config["configs"][
                    "cartography"
                ]
            ),
            "--output-dir",
            str(context.paths.maps),
        ]

    def report_command(context: PipelineContext) -> list[str]:
        analysis = context.config["analysis"]

        command = command_base() + [
            "generate-technical-report",
            str(context.paths.run),
            "--target-density",
            str(context.target_density),
            "--farm-name",
            str(analysis["farm_name"]),
            "--producer",
            str(analysis.get("producer", "")),
            "--author",
            str(
                analysis.get(
                    "author",
                    "Ing. Darwin A. González Romero",
                )
            ),
            "--maps-dir",
            str(context.paths.maps),
            "--config",
            str(
                context.config["configs"][
                    "report"
                ]
            ),
            "--output-dir",
            str(context.paths.report),
        ]

        report_date = analysis.get("report_date")

        if report_date not in (None, ""):
            command.extend(
                ["--report-date", str(report_date)]
            )

        return command

    def single_directory(
        attribute: str,
    ) -> Callable[[PipelineContext], list[Path]]:
        return lambda context: [
            getattr(context.paths, attribute)
        ]

    return [
        StageDefinition(
            "generate_tiles",
            STAGE_TITLES["generate_tiles"],
            tiles_command,
            validate_tiles,
            single_directory("tiles"),
        ),
        StageDefinition(
            "run_yolo",
            STAGE_TITLES["run_yolo"],
            yolo_command,
            validate_yolo,
            single_directory("yolo"),
        ),
        StageDefinition(
            "georeference_detections",
            STAGE_TITLES[
                "georeference_detections"
            ],
            georeference_command,
            validate_georeferenced,
            single_directory("georeferenced"),
        ),
        StageDefinition(
            "export_raw_gis",
            STAGE_TITLES["export_raw_gis"],
            raw_gis_command,
            validate_raw_gis,
            single_directory("raw_gis"),
        ),
        StageDefinition(
            "deduplicate_detections",
            STAGE_TITLES[
                "deduplicate_detections"
            ],
            dedup_command,
            validate_deduplicated,
            single_directory("detections_clean"),
        ),
        StageDefinition(
            "calculate_statistics",
            STAGE_TITLES["calculate_statistics"],
            statistics_command,
            validate_statistics,
            lambda context: [
                context.paths.gis
                / "inventario_banano_validado.csv",
                context.paths.gis
                / "inventario_banano_validado.gpkg",
                context.paths.gis
                / "limite_analisis.gpkg",
                context.paths.gis
                / "estadisticas_banano.csv",
                context.paths.gis
                / "estadisticas_banano.json",
                context.paths.gis
                / "detecciones_fuera_limite.gpkg",
            ],
        ),
        StageDefinition(
            "analyze_spatial_pattern",
            STAGE_TITLES[
                "analyze_spatial_pattern"
            ],
            spatial_command,
            validate_spatial_pattern,
            single_directory("spatial_pattern"),
        ),
        StageDefinition(
            "generate_hex_density",
            STAGE_TITLES["generate_hex_density"],
            hex_command,
            validate_hex_density,
            single_directory("hex_density"),
        ),
        StageDefinition(
            "detect_planting_opportunities",
            STAGE_TITLES[
                "detect_planting_opportunities"
            ],
            opportunities_command,
            validate_opportunities,
            single_directory("opportunities"),
        ),
        StageDefinition(
            "prioritize_planting_opportunities",
            STAGE_TITLES[
                "prioritize_planting_opportunities"
            ],
            priority_command,
            validate_priority,
            single_directory("priority"),
        ),
        StageDefinition(
            "generate_kde_density",
            STAGE_TITLES["generate_kde_density"],
            kde_command,
            validate_kde,
            single_directory("kde"),
        ),
        StageDefinition(
            "generate_cartographic_package",
            STAGE_TITLES[
                "generate_cartographic_package"
            ],
            maps_command,
            validate_maps,
            single_directory("maps"),
        ),
        StageDefinition(
            "generate_technical_report",
            STAGE_TITLES[
                "generate_technical_report"
            ],
            report_command,
            validate_report,
            single_directory("report"),
        ),
    ]


def path_has_content(path: Path) -> bool:
    """Indica si una ruta contiene datos que deben conservarse."""

    if not path.exists():
        return False

    if path.is_file():
        return True

    return any(path.iterdir())


def archive_stage_outputs(
    context: PipelineContext,
    stage: StageDefinition,
) -> list[str]:
    """Conserva salidas anteriores antes de un reintento."""

    targets = [
        target
        for target in stage.cleanup_targets(context)
        if path_has_content(target)
    ]

    if not targets:
        return []

    archive_directory = (
        context.paths.logs
        / "reintentos"
        / (
            datetime.now().strftime(
                "%Y%m%d_%H%M%S"
            )
            + "_"
            + stage.key
        )
    )
    archive_directory.mkdir(
        parents=True,
        exist_ok=False,
    )

    archived: list[str] = []

    for target in targets:
        destination = (
            archive_directory / target.name
        )

        shutil.move(
            str(target),
            str(destination),
        )
        archived.append(str(destination))

        if target.suffix == "":
            target.mkdir(
                parents=True,
                exist_ok=True,
            )

    return archived


def prepare_run_directories(paths: PipelinePaths) -> None:
    """Garantiza las carpetas usadas por el orquestador."""

    for directory in (
        paths.tiles,
        paths.yolo.parent,
        paths.detections_clean,
        paths.gis,
        paths.logs,
        paths.temp,
        paths.maps.parent,
        paths.report.parent,
    ):
        directory.mkdir(
            parents=True,
            exist_ok=True,
        )


def persist_config_snapshot(
    context: PipelineContext,
) -> None:
    """Conserva la configuración normalizada en el proyecto."""

    atomic_write_yaml(
        context.paths.config_snapshot_yaml,
        context.config,
    )
    atomic_write_json(
        context.paths.config_snapshot_json,
        context.config,
    )


def locate_new_run_directory(
    *,
    output_root: Path,
    before: set[Path],
) -> Path:
    """Identifica la carpeta creada por clip-raster."""

    after = {
        path.resolve(strict=False)
        for path in output_root.iterdir()
        if path.is_dir()
    }

    new_directories = sorted(
        after.difference(before),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )

    structured = [
        path
        for path in new_directories
        if (path / "01_recorte").is_dir()
        and (path / "05_gis").is_dir()
    ]

    if not structured:
        raise FileNotFoundError(
            "clip-raster finalizó, pero no se pudo identificar "
            "la nueva carpeta de ejecución."
        )

    return structured[0]


def bootstrap_commands(
    config: dict[str, Any],
) -> list[tuple[str, str, list[str]]]:
    """Comandos previos a la existencia de la carpeta de ejecución."""

    analysis = config["analysis"]
    options = config.get("pipeline", {})
    commands: list[tuple[str, str, list[str]]] = []

    if bool(options.get("run_system_check", True)):
        commands.append(
            (
                "validate_environment",
                STAGE_TITLES[
                    "validate_environment"
                ],
                command_base() + ["system-check"],
            )
        )

    commands.append(
        (
            "validate_raster",
            STAGE_TITLES["validate_raster"],
            command_base()
            + [
                "validate-raster",
                str(analysis["orthophoto_path"]),
            ],
        )
    )

    if bool(
        options.get(
            "run_boundary_validation",
            True,
        )
    ):
        commands.append(
            (
                "validate_boundary",
                STAGE_TITLES[
                    "validate_boundary"
                ],
                command_base()
                + [
                    "validate-boundary",
                    str(
                        analysis[
                            "boundary_excel_path"
                        ]
                    ),
                    str(
                        analysis[
                            "orthophoto_path"
                        ]
                    ),
                    "--sheet",
                    str(
                        analysis[
                            "boundary_sheet"
                        ]
                    ),
                ],
            )
        )

    commands.append(
        (
            "clip_raster",
            STAGE_TITLES["clip_raster"],
            command_base()
            + [
                "clip-raster",
                str(
                    analysis[
                        "boundary_excel_path"
                    ]
                ),
                str(analysis["orthophoto_path"]),
                "--sheet",
                str(analysis["boundary_sheet"]),
                "--output-dir",
                str(analysis["output_root"]),
            ],
        )
    )

    return commands


def print_dry_run(
    config: dict[str, Any],
) -> None:
    """Muestra el plan completo sin procesar datos."""

    analysis = config["analysis"]
    target_density = float(
        analysis["target_density_plants_ha"]
    )
    fake_run = (
        Path(analysis["output_root"])
        / "<NUEVA_EJECUCION>"
    )
    paths = build_pipeline_paths(
        fake_run,
        target_density,
    )
    state = create_initial_state(
        config_path=Path("<CONFIG>"),
        config=config,
        run_directory=fake_run,
    )
    context = PipelineContext(
        config_path=Path("<CONFIG>"),
        config=config,
        run_directory=fake_run,
        paths=paths,
        target_density=target_density,
        density_token=density_token(
            target_density
        ),
        state=state,
    )

    print("=" * 78)
    print("PLAN DE EJECUCIÓN — SIN PROCESAR DATOS")
    print("=" * 78)

    for key, title, command in bootstrap_commands(config):
        print(f"\n{key}: {title}")
        print(command_text(command))

    print(
        "\nLas etapas siguientes utilizarán la carpeta "
        "creada por clip-raster:"
    )

    for stage in stage_definitions():
        print(f"\n{stage.key}: {stage.title}")

        try:
            command = stage.command_builder(context)
            print(command_text(command))
        except FileNotFoundError:
            print(
                "Comando dependiente de una salida "
                "generada por la etapa anterior."
            )


def should_execute_stage(
    *,
    stage: StageDefinition,
    context: PipelineContext,
    forced: set[str],
) -> tuple[bool, list[str]]:
    """Decide si una etapa puede omitirse."""

    validation_ok, validation_messages = (
        stage.validator(context)
    )
    stage_state = context.state["stages"][
        stage.key
    ]

    if (
        stage.key not in forced
        and validation_ok
    ):
        stage_state["status"] = "completed"
        stage_state["validation_messages"] = []
        stage_state["error"] = None
        return False, []

    return True, validation_messages


def invalidate_from_stage(
    context: PipelineContext,
    start_key: str,
) -> None:
    """Marca la etapa indicada y las posteriores como pendientes."""

    keys = list(PROCESS_STAGE_KEYS)
    start_index = keys.index(start_key)

    for key in keys[start_index:]:
        stage_state = context.state["stages"][key]
        stage_state["status"] = "pending"
        stage_state["error"] = None
        stage_state["validation_messages"] = []


def execute_processing_stages(
    *,
    context: PipelineContext,
    from_stage: str | None,
    stop_after: str | None,
    force_stages: set[str],
) -> int:
    """Ejecuta las etapas posteriores al recorte."""

    definitions = stage_definitions()
    keys = [stage.key for stage in definitions]

    if from_stage is not None:
        if from_stage not in keys:
            raise ValueError(
                "--from-stage debe ser una etapa posterior "
                "al recorte."
            )

        from_index = keys.index(from_stage)

        for previous in definitions[:from_index]:
            valid, messages = previous.validator(context)

            if not valid:
                raise RuntimeError(
                    "No se puede comenzar desde "
                    f"{from_stage}. Falta la salida de "
                    f"{previous.key}: {'; '.join(messages)}"
                )

    else:
        from_index = 0

    if force_stages:
        earliest = min(
            keys.index(key)
            for key in force_stages
        )
        invalidate_from_stage(
            context,
            keys[earliest],
        )
        force_stages = set(
            keys[earliest:]
        )
        from_index = min(from_index, earliest)

    for index, stage in enumerate(definitions):
        if index < from_index:
            continue

        context.state["current_stage"] = stage.key
        save_state(context)

        execute, previous_messages = (
            should_execute_stage(
                stage=stage,
                context=context,
                forced=force_stages,
            )
        )

        if not execute:
            print(
                f"[OMITIDA] {stage.title}: "
                "la salida existente fue validada."
            )

            if stop_after == stage.key:
                context.state["status"] = "paused"
                context.state["current_stage"] = None
                save_state(context)
                return 0

            continue

        stage_state = context.state["stages"][
            stage.key
        ]

        if (
            stage_state.get("status") == "failed"
            or stage.key in force_stages
            or previous_messages
        ):
            archived = archive_stage_outputs(
                context,
                stage,
            )

            if archived:
                context.state["warnings"].append(
                    f"Se archivaron salidas anteriores "
                    f"de {stage.key}: "
                    + ", ".join(archived)
                )

        command = stage.command_builder(context)
        log_path = (
            context.paths.logs
            / f"{index + 5:02d}_{stage.key}.log"
        )

        stage_state.update(
            {
                "status": "running",
                "started_at": now_iso(),
                "finished_at": None,
                "elapsed_seconds": None,
                "return_code": None,
                "log_path": str(log_path),
                "command": command,
                "validation_messages": [],
                "error": None,
            }
        )
        save_state(context)

        return_code, elapsed = run_command(
            stage_key=stage.key,
            title=stage.title,
            command=command,
            log_path=log_path,
        )

        stage_state["return_code"] = return_code
        stage_state["elapsed_seconds"] = elapsed
        stage_state["finished_at"] = now_iso()

        valid, validation_messages = (
            stage.validator(context)
        )
        stage_state["validation_messages"] = (
            validation_messages
        )

        if return_code != 0 or not valid:
            stage_state["status"] = "failed"
            stage_state["error"] = (
                f"return_code={return_code}. "
                + "; ".join(validation_messages)
            )
            context.state["status"] = "failed"
            context.state["errors"].append(
                f"{stage.key}: {stage_state['error']}"
            )
            save_state(context)

            print()
            print("PIPELINE DETENIDO")
            print(
                f"Etapa fallida: {stage.title}"
            )
            print(f"Log: {log_path}")
            print(
                "Use --resume-run después de corregir "
                "la causa. La etapa fallida se reintentará "
                "sin repetir las etapas completadas."
            )
            return 1

        stage_state["status"] = "completed"
        stage_state["error"] = None
        save_state(context)

        print(
            f"[COMPLETADA] {stage.title} "
            f"en {elapsed} segundos."
        )

        if stop_after == stage.key:
            context.state["status"] = "paused"
            context.state["current_stage"] = None
            save_state(context)

            print(
                f"Pipeline pausado después de {stage.key}."
            )
            return 0

    context.state["status"] = "completed"
    context.state["current_stage"] = None
    context.state["finished_at"] = now_iso()

    report_pdf = find_report_pdf(context)

    context.state["artifacts"] = {
        "run_directory": str(context.paths.run),
        "inventory_gpkg": str(
            context.paths.gis
            / "inventario_banano_validado.gpkg"
        ),
        "boundary_gpkg": str(
            context.paths.gis
            / "limite_analisis.gpkg"
        ),
        "hex_density_gpkg": str(
            context.paths.hex_density
            / "densidad_hexagonal.gpkg"
        ),
        "priority_candidates_gpkg": str(
            context.paths.priority
            / "candidatos_siembra_priorizados.gpkg"
        ),
        "kde_raster": str(
            context.paths.kde
            / "densidad_kde_corregida_plantas_ha.tif"
        ),
        "maps_directory": str(context.paths.maps),
        "technical_report_pdf": (
            str(report_pdf)
            if report_pdf is not None
            else None
        ),
    }
    save_state(context)

    manifest = {
        "success": True,
        "pipeline_build": PIPELINE_BUILD,
        "finished_at": now_iso(),
        "run_directory": str(context.paths.run),
        "target_density_plants_ha": (
            context.target_density
        ),
        "state_path": str(
            context.paths.state_json
        ),
        "artifacts": context.state["artifacts"],
        "warnings": context.state["warnings"],
    }
    atomic_write_json(
        context.paths.pipeline_manifest_json,
        manifest,
    )

    print()
    print("=" * 78)
    print("ANÁLISIS AUTOMÁTICO COMPLETADO")
    print("=" * 78)
    print(f"Ejecución: {context.paths.run}")
    print(f"Mapas: {context.paths.maps}")

    if report_pdf is not None:
        print(f"Informe PDF: {report_pdf}")

    print(f"Estado: {context.paths.state_json}")
    print(
        f"Manifiesto: "
        f"{context.paths.pipeline_manifest_json}"
    )
    print("=" * 78)
    return 0


def run_full_pipeline(
    config_path: str | Path | None = None,
    resume_run_directory: str | Path | None = None,
    from_stage: str | None = None,
    stop_after: str | None = None,
    force_stages: list[str] | None = None,
    dry_run: bool = False,
) -> int:
    """Ejecuta o reanuda el análisis integral."""

    context: PipelineContext | None = None

    try:
        resolved_config, config = (
            load_pipeline_config(config_path)
        )

        if dry_run:
            print_dry_run(config)
            return 0

        target_density = float(
            config["analysis"][
                "target_density_plants_ha"
            ]
        )
        forced = set(force_stages or [])

        invalid_forced = forced.difference(
            PROCESS_STAGE_KEYS
        )

        if invalid_forced:
            raise ValueError(
                "No se pueden forzar estas etapas: "
                + ", ".join(sorted(invalid_forced))
            )

        if resume_run_directory is None:
            if from_stage not in (None, "generate_tiles"):
                raise ValueError(
                    "En una ejecución nueva, --from-stage "
                    "solo puede omitirse o ser generate_tiles."
                )

            output_root = Path(
                config["analysis"]["output_root"]
            )
            output_root.mkdir(
                parents=True,
                exist_ok=True,
            )

            before = {
                path.resolve(strict=False)
                for path in output_root.iterdir()
                if path.is_dir()
            }

            bootstrap_log_directory = (
                output_root
                / "pipeline_bootstrap_logs"
                / datetime.now().strftime(
                    "%Y%m%d_%H%M%S"
                )
            )
            bootstrap_log_directory.mkdir(
                parents=True,
                exist_ok=False,
            )

            completed_bootstrap: list[str] = []

            for index, (
                stage_key,
                title,
                command,
            ) in enumerate(
                bootstrap_commands(config),
                start=1,
            ):
                log_path = (
                    bootstrap_log_directory
                    / f"{index:02d}_{stage_key}.log"
                )
                return_code, _elapsed = run_command(
                    stage_key=stage_key,
                    title=title,
                    command=command,
                    log_path=log_path,
                )

                if return_code != 0:
                    print(
                        "No se creó una ejecución porque "
                        f"falló: {title}."
                    )
                    print(
                        f"Revise el log: {log_path}"
                    )
                    return 1

                completed_bootstrap.append(
                    stage_key
                )

            run_directory = locate_new_run_directory(
                output_root=output_root,
                before=before,
            )
            paths = build_pipeline_paths(
                run_directory,
                target_density,
            )
            prepare_run_directories(paths)

            for log in bootstrap_log_directory.glob(
                "*.log"
            ):
                shutil.move(
                    str(log),
                    str(paths.logs / log.name),
                )

            try:
                bootstrap_log_directory.rmdir()
                bootstrap_log_directory.parent.rmdir()
            except OSError:
                pass

            state = create_initial_state(
                config_path=resolved_config,
                config=config,
                run_directory=run_directory,
            )

            for stage_key in BOOTSTRAP_STAGE_KEYS:
                stage_state = state["stages"][
                    stage_key
                ]

                if stage_key in completed_bootstrap:
                    stage_state["status"] = "completed"
                    stage_state["finished_at"] = now_iso()
                else:
                    stage_state["status"] = "skipped"

        else:
            run_directory = Path(
                resume_run_directory
            ).expanduser().resolve(strict=False)

            if not run_directory.is_dir():
                raise FileNotFoundError(
                    "No existe la ejecución a reanudar: "
                    f"{run_directory}"
                )

            paths = build_pipeline_paths(
                run_directory,
                target_density,
            )
            prepare_run_directories(paths)
            state = load_or_reconstruct_state(
                config_path=resolved_config,
                config=config,
                run_directory=run_directory,
            )

        context = PipelineContext(
            config_path=resolved_config,
            config=config,
            run_directory=run_directory,
            paths=paths,
            target_density=target_density,
            density_token=density_token(
                target_density
            ),
            state=state,
        )
        persist_config_snapshot(context)
        save_state(context)

        return execute_processing_stages(
            context=context,
            from_stage=from_stage,
            stop_after=stop_after,
            force_stages=forced,
        )

    except KeyboardInterrupt:
        if context is not None:
            context.state["status"] = "interrupted"
            context.state["current_stage"] = None
            context.state["warnings"].append(
                "El proceso fue interrumpido por el usuario."
            )
            save_state(context)

        print()
        print(
            "Proceso interrumpido por el usuario. "
            "La ejecución puede reanudarse con "
            "--resume-run."
        )
        return 130

    except Exception as error:
        if context is not None:
            context.state["status"] = "failed"
            context.state["current_stage"] = None
            context.state["errors"].append(
                f"{type(error).__name__}: {error}"
            )
            save_state(context)

        print("=" * 78)
        print("ERROR DEL ORQUESTADOR")
        print("=" * 78)
        print(
            f"{type(error).__name__}: {error}"
        )
        return 1
