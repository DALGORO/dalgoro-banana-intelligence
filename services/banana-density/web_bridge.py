"""Adaptador CLI mínimo para reutilizar la configuración de la GUI estable."""

from __future__ import annotations

import argparse
import importlib
import importlib.util
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from types import ModuleType
from typing import Any


def _read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(payload, dict):
        raise ValueError("La solicitud web debe ser un objeto JSON.")
    return payload


def _load_interface(engine_root: Path) -> ModuleType:
    interface_path = engine_root / "interfaz_banano.py"
    if not interface_path.is_file():
        raise FileNotFoundError(
            f"No existe la interfaz estable del analizador: {interface_path}"
        )
    spec = importlib.util.spec_from_file_location(
        "dalgoro_density_stable_interface",
        interface_path,
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("No se pudo cargar la interfaz estable del analizador.")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _ensure_geotiff_alias(values: dict[str, Any], config_path: Path) -> None:
    """Da al motor estable una ruta .tif sin duplicar la ortofoto privada DBI.

    El object store DBI usa claves opacas sin extensión. La GUI estable valida que
    la ortofoto termine en .tif/.tiff antes de abrirla. El alias debe crearse en el
    mismo volumen físico que la ortofoto porque Windows no admite hard links entre
    volúmenes diferentes.
    """

    raw = str(values.get("orthophoto") or "").strip()
    if not raw:
        return

    source = Path(raw).expanduser().resolve(strict=False)

    if source.suffix.lower() in {".tif", ".tiff"}:
        return

    if not source.is_file():
        return

    job_id = config_path.parent.name

    temp_candidates = [
        os.environ.get("TEMP", "").strip(),
        os.environ.get("TMP", "").strip(),
    ]

    alias_root: Path | None = None

    for raw_temp in temp_candidates:
        if not raw_temp:
            continue

        candidate = Path(raw_temp).expanduser().resolve(strict=False)

        if candidate.drive.lower() == source.drive.lower():
            alias_root = candidate / "dalgoro-density-aliases" / job_id
            break

    if alias_root is None:
        storage_raw = os.environ.get("DBI_LOCAL_STORAGE_ROOT", "").strip()

        if storage_raw:
            storage_root = Path(storage_raw).expanduser().resolve(strict=False)

            if storage_root.drive.lower() == source.drive.lower():
                alias_root = (
                    storage_root
                    / ".density-aliases"
                    / job_id
                )

    if alias_root is None:
        raise RuntimeError(
            "No existe un directorio temporal DBI en el mismo volumen "
            "que la ortofoto privada."
        )

    alias = alias_root / "ortofoto.tif"
    alias.parent.mkdir(parents=True, exist_ok=True)

    if alias.exists():
        try:
            if os.path.samefile(source, alias):
                values["orthophoto"] = str(alias)
                return
        except OSError:
            pass

        alias.unlink()

    try:
        os.link(source, alias)
    except OSError as error:
        raise RuntimeError(
            "No se pudo crear la vista .tif de la ortofoto privada DBI "
            "en el mismo volumen sin duplicar el archivo."
        ) from error

    values["orthophoto"] = str(alias)


def _prepare_pipeline_workspace(values: dict[str, Any], config_path: Path) -> None:
    """Mueve solo las salidas pesadas a un espacio DALGORO dedicado en Windows.

    El estado y los inputs del trabajo permanecen en LOCALAPPDATA. El directorio
    ``runs`` de control se conserva como junction hacia el workspace en F:, de
    modo que DBI mantiene sus rutas y trazabilidad mientras el motor calcula el
    espacio libre y escribe físicamente en el volumen con mayor capacidad.
    """

    if os.name != "nt":
        return

    local_output_raw = str(values.get("output_root") or "").strip()
    if not local_output_raw:
        raise RuntimeError("El análisis no definió un directorio de salida.")

    local_output = Path(local_output_raw).expanduser().resolve(strict=False)
    expected_output = (config_path.parent / "runs").resolve(strict=False)
    if local_output != expected_output:
        raise RuntimeError(
            "El directorio de salida del trabajo no coincide con el espacio DBI esperado."
        )

    workspace_raw = os.environ.get("DBI_DENSITY_WORKSPACE_ROOT", "").strip()
    workspace_root = Path(
        workspace_raw
        or "F:/DALGORO_DBI/BANANA_INTELLIGENCE/DENSITY_PIPELINE"
    ).expanduser().resolve(strict=False)

    anchor = Path(workspace_root.anchor)
    if not workspace_root.anchor or not anchor.exists():
        raise RuntimeError(
            f"No está disponible el volumen del workspace de densidad: {workspace_root.anchor or workspace_root}"
        )

    job_id = config_path.parent.name
    workspace_job = workspace_root / "jobs" / job_id
    pipeline_output = workspace_job / "runs"

    if local_output == pipeline_output.resolve(strict=False):
        pipeline_output.mkdir(parents=True, exist_ok=True)
    else:
        pipeline_output.mkdir(parents=True, exist_ok=False)

        if not local_output.is_dir():
            raise RuntimeError(
                f"No existe el directorio local de salida preparado por DBI: {local_output}"
            )

        if any(local_output.iterdir()):
            raise RuntimeError(
                f"El directorio local de salida no está vacío y no puede reubicarse: {local_output}"
            )

        local_output.rmdir()

        junction = subprocess.run(
            [
                "cmd.exe",
                "/d",
                "/c",
                "mklink",
                "/J",
                str(local_output),
                str(pipeline_output),
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )

        if junction.returncode != 0 or not local_output.is_dir():
            local_output.mkdir(parents=True, exist_ok=True)

            try:
                pipeline_output.rmdir()
                workspace_job.rmdir()
            except OSError:
                pass

            detail = (junction.stdout + "\n" + junction.stderr).strip()

            raise RuntimeError(
                "No se pudo enlazar el directorio de ejecución DBI "
                "con el workspace dedicado"
                + (f": {detail}" if detail else ".")
            )

    trace = {
        "schema_version": "dalgoro-dbi-density-workspace.v1",
        "job_id": job_id,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "control_job_root": str(config_path.parent),
        "control_output_link": str(local_output),
        "pipeline_output_root": str(pipeline_output),
        "producer": str(values.get("producer") or ""),
        "farm_name": str(values.get("farm_name") or ""),
        "target_density": str(values.get("target_density") or ""),
    }
    (workspace_job / "traceability.json").write_text(
        json.dumps(trace, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    values["output_root"] = str(pipeline_output)


def prepare(request_path: Path, config_path: Path, engine_root: Path) -> int:
    root = engine_root.expanduser().resolve(strict=False)
    interface = _load_interface(root)
    values = _read_json(request_path)

    _ensure_geotiff_alias(values, config_path)

    all_layers = str(getattr(interface, "ALL_EXCLUSION_LAYERS"))
    if str(values.get("exclusions_gpkg") or "").strip():
        values["exclusions_layer"] = all_layers
    else:
        values["exclusions_gpkg"] = ""
        values["exclusions_layer"] = ""

    interface.validate_values(values)
    _prepare_pipeline_workspace(values, config_path)
    config = interface.build_pipeline_config(values)

    # Las configuraciones cartográficas/técnicas deben provenir del mismo motor
    # que Darwin ya usa en producción local, no de una copia paralela del repo web.
    config["configs"] = {
        "spatial_analysis": str(root / "config" / "spatial_analysis.yaml"),
        "cartography": str(root / "config" / "cartography.yaml"),
        "report": str(root / "config" / "report.yaml"),
    }
    interface.atomic_write_yaml(config_path, config)
    print(
        json.dumps(
            {
                "success": True,
                "config_path": str(config_path),
                "engine_root": str(root),
                "exclusions_layer": config["analysis"].get("exclusions_layer"),
            },
            ensure_ascii=False,
        )
    )
    return 0


def candidate_review(run_directory: Path, reviewed_candidates: Path, engine_root: Path) -> int:
    """Ejecuta sin duplicar lógica la revisión de candidatos del motor estable."""

    root = engine_root.expanduser().resolve(strict=False)
    run = run_directory.expanduser().resolve(strict=False)
    reviewed = reviewed_candidates.expanduser().resolve(strict=False)
    module_path = root / "src" / "banana_analyzer" / "candidate_review.py"
    if not module_path.is_file():
        raise FileNotFoundError(
            f"El motor estable no incorpora revisión de candidatos: {module_path}"
        )
    if not run.is_dir():
        raise FileNotFoundError(f"No existe la ejecución a revisar: {run}")
    if not reviewed.is_file():
        raise FileNotFoundError(f"No existe el GeoPackage revisado: {reviewed}")

    source_root = str(root / "src")
    if source_root not in sys.path:
        sys.path.insert(0, source_root)
    module = importlib.import_module("banana_analyzer.candidate_review")
    runner = getattr(module, "run_candidate_review", None)
    if not callable(runner):
        raise RuntimeError("El motor estable no expone run_candidate_review().")
    return int(runner(run, reviewed))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="banana-density-web-bridge")
    sub = parser.add_subparsers(dest="command", required=True)
    prepare_parser = sub.add_parser("prepare")
    prepare_parser.add_argument("request_path", type=Path)
    prepare_parser.add_argument("config_path", type=Path)
    prepare_parser.add_argument("engine_root", type=Path)

    review_parser = sub.add_parser("candidate-review")
    review_parser.add_argument("run_directory", type=Path)
    review_parser.add_argument("reviewed_candidates", type=Path)
    review_parser.add_argument("engine_root", type=Path)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    if args.command == "prepare":
        return prepare(args.request_path, args.config_path, args.engine_root)
    if args.command == "candidate-review":
        return candidate_review(args.run_directory, args.reviewed_candidates, args.engine_root)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())