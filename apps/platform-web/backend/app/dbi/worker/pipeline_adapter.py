"""Adaptador conservador entre DBI y el orquestador headless heredado."""

from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Callable

import yaml

from app.dbi.worker.contracts import (
    DBIWorkerConflict,
    PipelineExecutionEvidence,
    ResolvedAnalysisPlan,
)
from app.dbi.worker.materialization import DBIWorkerWorkspace

AUTHOR = "Ing. Darwin A. González Romero"
PROCESS_STAGES = (
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
_ALLOWED_CONFIG_KEYS = frozenset(
    {
        "target_density_plants_ha",
        "boundary_sheet",
        "exclusions_layer",
        "producer",
        "report_date",
        "tile_size",
        "overlap",
        "min_valid_percent",
        "yolo_confidence",
        "confidence",
        "yolo_iou",
        "iou",
        "yolo_imgsz",
        "yolo_device",
        "max_detections",
        "yolo_limit",
        "deduplication_distance_m",
        "kde_radius_m",
        "kde_pixel_size_m",
        "run_system_check",
        "run_boundary_validation",
    }
)

REPOSITORY_ROOT = Path(__file__).resolve().parents[6]
BANANA_SERVICE_ROOT = REPOSITORY_ROOT / "services" / "banana-density"
BANANA_MAIN = BANANA_SERVICE_ROOT / "main.py"


def _runtime_parameter(payload: dict[str, object], canonical: str, alias: str | None, default):
    if canonical in payload and alias is not None and alias in payload:
        if payload[canonical] != payload[alias]:
            raise DBIWorkerConflict(f"{canonical} y {alias} son divergentes.")
    if canonical in payload:
        return payload[canonical]
    if alias is not None and alias in payload:
        return payload[alias]
    return default


def build_legacy_runtime_config(
    plan: ResolvedAnalysisPlan,
    workspace: DBIWorkerWorkspace,
) -> dict[str, object]:
    payload = dict(plan.pipeline.payload)
    unknown = set(payload).difference(_ALLOWED_CONFIG_KEYS)
    if unknown:
        raise DBIWorkerConflict(
            "pipeline_config contiene claves no ejecutables: "
            + ", ".join(sorted(unknown))
        )
    if "target_density_plants_ha" not in payload:
        raise DBIWorkerConflict(
            "pipeline_config debe fijar target_density_plants_ha."
        )

    target_density = float(payload["target_density_plants_ha"])
    if target_density <= 0:
        raise DBIWorkerConflict("target_density_plants_ha debe ser positivo.")
    boundary_sheet = str(payload.get("boundary_sheet", "0"))
    exclusions_layer = (
        str(payload.get("exclusions_layer", "exclusions"))
        if plan.exclusions is not None
        else None
    )

    parameters = {
        "tile_size": int(payload.get("tile_size", 640)),
        "overlap": int(payload.get("overlap", 128)),
        "min_valid_percent": float(payload.get("min_valid_percent", 0.0)),
        "yolo_confidence": float(
            _runtime_parameter(payload, "yolo_confidence", "confidence", 0.40)
        ),
        "yolo_iou": float(_runtime_parameter(payload, "yolo_iou", "iou", 0.70)),
        "yolo_imgsz": int(payload.get("yolo_imgsz", 640)),
        "yolo_device": str(payload.get("yolo_device", "auto")),
        "max_detections": int(payload.get("max_detections", 1000)),
        "yolo_limit": payload.get("yolo_limit"),
        "deduplication_distance_m": float(
            payload.get("deduplication_distance_m", 1.0)
        ),
        "kde_radius_m": payload.get("kde_radius_m"),
        "kde_pixel_size_m": float(payload.get("kde_pixel_size_m", 0.50)),
    }

    return {
        "version": 1,
        "analysis": {
            "farm_name": f"{plan.farm_name} — {plan.plot_name}",
            "producer": str(payload.get("producer", "")),
            "author": AUTHOR,
            "report_date": payload.get("report_date"),
            "orthophoto_path": str(workspace.orthophoto_path),
            "boundary_excel_path": str(workspace.boundary_path),
            "boundary_sheet": boundary_sheet,
            "target_density_plants_ha": target_density,
            "model_path": str(workspace.model_path),
            "output_root": str(workspace.output_root),
            "exclusions_gpkg": (
                None
                if workspace.exclusions_path is None
                else str(workspace.exclusions_path)
            ),
            "exclusions_layer": exclusions_layer,
        },
        "parameters": parameters,
        "configs": {
            "spatial_analysis": str(BANANA_SERVICE_ROOT / "config" / "spatial_analysis.yaml"),
            "cartography": str(BANANA_SERVICE_ROOT / "config" / "cartography.yaml"),
            "report": str(BANANA_SERVICE_ROOT / "config" / "report.yaml"),
        },
        "pipeline": {
            "run_system_check": bool(payload.get("run_system_check", True)),
            "run_boundary_validation": bool(
                payload.get("run_boundary_validation", True)
            ),
        },
    }


def write_legacy_runtime_config(
    plan: ResolvedAnalysisPlan,
    workspace: DBIWorkerWorkspace,
) -> None:
    runtime = build_legacy_runtime_config(plan, workspace)
    temporary = workspace.pipeline_config_path.with_suffix(".yaml.partial")
    temporary.write_text(
        yaml.safe_dump(
            runtime,
            allow_unicode=True,
            sort_keys=False,
            width=100,
        ),
        encoding="utf-8",
    )
    temporary.replace(workspace.pipeline_config_path)


def _find_run_directory(output_root: Path) -> Path:
    candidates = sorted(
        {
            path.parent
            for path in output_root.rglob("estado_pipeline.json")
            if path.is_file()
        }
    )
    if len(candidates) != 1:
        raise DBIWorkerConflict(
            "el pipeline no produjo exactamente una ejecución identificable."
        )
    return candidates[0]


class DBILegacyPipelineAdapter:
    """Ejecuta una etapa por proceso para heartbeat y cancelación cooperativa."""

    def __init__(self, *, poll_seconds: float = 1.0) -> None:
        if poll_seconds <= 0:
            raise ValueError("poll_seconds debe ser positivo.")
        self._poll_seconds = poll_seconds

    def _run_child(
        self,
        *,
        command: list[str],
        log_path: Path,
        heartbeat: Callable[[], object],
    ) -> int:
        environment = os.environ.copy()
        environment["PYTHONUTF8"] = "1"
        environment["PYTHONIOENCODING"] = "utf-8"
        with log_path.open("a", encoding="utf-8", errors="replace") as log:
            process = subprocess.Popen(
                command,
                cwd=BANANA_SERVICE_ROOT,
                stdout=log,
                stderr=subprocess.STDOUT,
                env=environment,
            )
            lease_error: BaseException | None = None
            while process.poll() is None:
                try:
                    heartbeat()
                except BaseException as error:  # el lease perdido no se oculta
                    lease_error = error
                time.sleep(self._poll_seconds)
            return_code = int(process.wait())
            if lease_error is not None:
                raise lease_error
            return return_code

    def run(
        self,
        *,
        plan: ResolvedAnalysisPlan,
        workspace: DBIWorkerWorkspace,
        heartbeat: Callable[[], object],
        cancel_requested: Callable[[], bool],
    ) -> PipelineExecutionEvidence:
        write_legacy_runtime_config(plan, workspace)
        if cancel_requested():
            return PipelineExecutionEvidence(status="canceled", return_code=0)
        if not BANANA_MAIN.is_file():
            raise DBIWorkerConflict("entrypoint de banana-density no disponible.")

        run_directory: Path | None = None
        log_path = workspace.logs_dir / "pipeline-worker.log"
        for index, stage in enumerate(PROCESS_STAGES):
            if cancel_requested():
                return PipelineExecutionEvidence(
                    status="canceled",
                    return_code=0,
                    run_directory=(None if run_directory is None else str(run_directory)),
                    pipeline_state_path=(
                        None
                        if run_directory is None
                        else str(run_directory / "estado_pipeline.json")
                    ),
                )

            command = [
                sys.executable,
                str(BANANA_MAIN),
                "run-full-analysis",
                str(workspace.pipeline_config_path),
            ]
            if run_directory is not None:
                command.extend(
                    [
                        "--resume-run",
                        str(run_directory),
                        "--from-stage",
                        stage,
                    ]
                )
            if index < len(PROCESS_STAGES) - 1:
                command.extend(["--stop-after", stage])

            return_code = self._run_child(
                command=command,
                log_path=log_path,
                heartbeat=heartbeat,
            )
            if return_code != 0:
                return PipelineExecutionEvidence(
                    status="failed",
                    return_code=min(max(return_code, 1), 255),
                    run_directory=(None if run_directory is None else str(run_directory)),
                    pipeline_state_path=(
                        None
                        if run_directory is None
                        else str(run_directory / "estado_pipeline.json")
                    ),
                )
            if run_directory is None:
                run_directory = _find_run_directory(workspace.output_root)

        assert run_directory is not None
        manifest = run_directory / "manifiesto_pipeline.json"
        state = run_directory / "estado_pipeline.json"
        if not manifest.is_file() or manifest.stat().st_size <= 0:
            raise DBIWorkerConflict("pipeline exitoso carece de manifiesto final.")
        if not state.is_file() or state.stat().st_size <= 0:
            raise DBIWorkerConflict("pipeline exitoso carece de estado final.")
        return PipelineExecutionEvidence(
            status="succeeded",
            return_code=0,
            run_directory=str(run_directory),
            pipeline_manifest_path=str(manifest),
            pipeline_state_path=str(state),
        )
