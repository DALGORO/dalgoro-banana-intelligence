from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_RUNS_DIRECTORY = PROJECT_ROOT / "runs"


@dataclass(frozen=True)
class RunWorkspace:
    """Estructura organizada de una ejecución."""

    run_id: str
    root: Path
    inputs: Path
    clipped: Path
    tiles: Path
    detections_raw: Path
    detections_clean: Path
    gis: Path
    maps: Path
    report: Path
    logs: Path
    temp: Path


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

    return normalized or "analisis"


def create_run_workspace(
    project_name: str,
    output_root: str | Path | None = None,
) -> RunWorkspace:
    """
    Crea una carpeta única para una ejecución.

    No sobrescribe ejecuciones anteriores.
    """

    if output_root is None:
        base_directory = DEFAULT_RUNS_DIRECTORY
    else:
        base_directory = Path(
            output_root
        ).expanduser().resolve(strict=False)

    base_directory.mkdir(
        parents=True,
        exist_ok=True,
    )

    safe_project_name = sanitize_name(project_name)

    timestamp = datetime.now().strftime(
        "%Y%m%d_%H%M%S"
    )

    base_run_id = (
        f"{safe_project_name}_{timestamp}"
    )

    run_id = base_run_id
    run_directory = base_directory / run_id

    counter = 1

    while run_directory.exists():
        run_id = f"{base_run_id}_{counter:02d}"
        run_directory = base_directory / run_id
        counter += 1

    paths = {
        "inputs": run_directory / "00_entradas",
        "clipped": run_directory / "01_recorte",
        "tiles": run_directory / "02_tiles",
        "detections_raw": (
            run_directory / "03_detecciones_raw"
        ),
        "detections_clean": (
            run_directory / "04_detecciones_limpias"
        ),
        "gis": run_directory / "05_gis",
        "maps": run_directory / "06_mapas",
        "report": run_directory / "07_reporte",
        "logs": run_directory / "logs",
        "temp": run_directory / "temp",
    }

    run_directory.mkdir(
        parents=True,
        exist_ok=False,
    )

    for directory in paths.values():
        directory.mkdir(
            parents=True,
            exist_ok=False,
        )

    return RunWorkspace(
        run_id=run_id,
        root=run_directory,
        inputs=paths["inputs"],
        clipped=paths["clipped"],
        tiles=paths["tiles"],
        detections_raw=paths[
            "detections_raw"
        ],
        detections_clean=paths[
            "detections_clean"
        ],
        gis=paths["gis"],
        maps=paths["maps"],
        report=paths["report"],
        logs=paths["logs"],
        temp=paths["temp"],
    )