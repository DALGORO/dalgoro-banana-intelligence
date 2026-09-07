"""Puente local entre DBI web y el motor probado de densidad de banano."""
from __future__ import annotations

import json
import os
import signal
import subprocess
import threading
from datetime import datetime
from pathlib import Path
from typing import Annotated, Any
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile, status
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.deps import current_user, db as get_db
from app.dbi.dependencies import get_dbi_session
from app.dbi.models.agriculture import Farm, Plot
from app.dbi.models.assets import AnalysisInputAsset
from app.dbi.storage_contracts import DBIStoragePurpose
from app.dbi.storage_local import DBILocalObjectStore
from app.dbi.storage_policy import DBIStoragePolicy
from app.models.company import Company
from app.models.user import User
from .dbi_pilot import _local_store, _organization_ref, _require_company, _require_local_pilot, _tenant_ref

router = APIRouter(prefix="/dbi/pilot", tags=["dbi-density-local"])
LegacySession = Annotated[Session, Depends(get_db)]
DBISession = Annotated[Session, Depends(get_dbi_session)]
CurrentUser = Annotated[User, Depends(current_user)]

STAGES = (
    ("validate_environment", "Verificación del entorno"),
    ("validate_raster", "Validación de la ortofoto"),
    ("validate_boundary", "Validación del límite"),
    ("clip_raster", "Recorte de la ortofoto"),
    ("generate_tiles", "Generación de tiles"),
    ("run_yolo", "Inferencia YOLO"),
    ("georeference_detections", "Georreferenciación"),
    ("export_raw_gis", "Exportación GIS preliminar"),
    ("deduplicate_detections", "Deduplicación"),
    ("calculate_statistics", "Estadísticas espaciales"),
    ("analyze_spatial_pattern", "Análisis del patrón espacial"),
    ("generate_hex_density", "Densidad por hexágonos"),
    ("detect_planting_opportunities", "Oportunidades geométricas de siembra"),
    ("prioritize_planting_opportunities", "Priorización operativa"),
    ("generate_kde_density", "Mapa continuo KDE"),
    ("generate_cartographic_package", "Paquete cartográfico"),
    ("generate_technical_report", "Informe técnico PDF"),
)
TITLES = dict(STAGES)
TITLE_KEYS = {title: key for key, title in STAGES}
LOCK = threading.RLock()
PROCESSES: dict[str, subprocess.Popen[str]] = {}


class DensityRuntimeResponse(BaseModel):
    ready: bool
    engine_ready: bool
    model_ready: bool
    message: str


class DensityStageResponse(BaseModel):
    key: str
    title: str
    status: str
    error: str | None = None


class DensityJobResponse(BaseModel):
    job_id: UUID
    company_id: int
    farm_id: UUID
    plot_id: UUID
    orthophoto_asset_id: UUID
    status: str
    current_stage: str | None
    progress_percent: int
    stages: list[DensityStageResponse]
    report_ready: bool
    error: str | None
    created_at: str
    updated_at: str


class DensityJobCreatedResponse(BaseModel):
    job_id: UUID
    status: str


def now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def repo_root() -> Path:
    return Path(__file__).resolve().parents[6]


def service_root() -> Path:
    return repo_root() / "services" / "banana-density"


def density_root() -> Path:
    explicit = os.environ.get("DBI_DENSITY_ROOT", "").strip()
    if explicit:
        root = Path(explicit).expanduser()
    elif os.environ.get("LOCALAPPDATA", "").strip():
        root = Path(os.environ["LOCALAPPDATA"]) / "DALGORO" / "DBI" / "density"
    else:
        root = repo_root() / ".dbi-density"
    root = root.resolve(strict=False)
    root.mkdir(parents=True, exist_ok=True)
    return root


def engine_root() -> Path:
    candidates: list[Path] = []
    explicit = os.environ.get("DBI_DENSITY_ENGINE_ROOT", "").strip()
    if explicit:
        candidates.append(Path(explicit).expanduser())
    candidates += [Path("F:/PROY_CONTEO_BANANO_1/automatizacion_banano"), service_root()]
    for root in candidates:
        if (root / "main.py").is_file() and (root / "src" / "banana_analyzer").is_dir():
            return root.resolve(strict=False)
    return service_root()


def runtime_settings(root: Path) -> dict[str, Any]:
    path = root / "config" / "interfaz_ultimo_uso.json"
    if not path.is_file():
        return {}
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError, TypeError):
        return {}
    return value if isinstance(value, dict) else {}


def density_python() -> Path | None:
    candidates: list[Path] = []
    explicit = os.environ.get("DBI_DENSITY_PYTHON", "").strip()
    if explicit:
        candidates.append(Path(explicit).expanduser())
    candidates += [
        engine_root() / ".venv" / "Scripts" / "python.exe",
        service_root() / ".venv" / "Scripts" / "python.exe",
        Path("F:/PROY_CONTEO_BANANO_1/automatizacion_banano/.venv/Scripts/python.exe"),
    ]
    return next((p.resolve(strict=False) for p in candidates if p.is_file()), None)


def density_model() -> Path | None:
    candidates: list[Path] = []
    explicit = os.environ.get("DBI_DENSITY_MODEL_PATH", "").strip()
    if explicit:
        candidates.append(Path(explicit).expanduser())
    for root in (engine_root(), service_root()):
        value = str(runtime_settings(root).get("model_path") or "").strip()
        if value:
            candidates.append(Path(value).expanduser())
    root = repo_root()
    candidates += [
        root / "runs/detect/banano_v4/weights/best.pt",
        root / "runs/detect/banano_v3/weights/best.pt",
        Path("F:/PROY_CONTEO_BANANO_1/runs/detect/banano_v4/weights/best.pt"),
        Path("F:/PROY_CONTEO_BANANO_1/runs/detect/banano_v3/weights/best.pt"),
    ]
    return next((p.resolve(strict=False) for p in candidates if p.is_file()), None)


def technical_defaults() -> dict[str, str]:
    values = {
        "tile_size": "640", "overlap": "128", "min_valid_percent": "0.0",
        "yolo_confidence": "0.40", "yolo_iou": "0.70", "yolo_imgsz": "640",
        "yolo_device": "auto", "max_detections": "1000",
        "deduplication_distance": "1.00", "kde_pixel_size": "0.50",
    }
    for root in (service_root(), engine_root()):
        saved = runtime_settings(root)
        for key in values:
            if saved.get(key) not in (None, ""):
                values[key] = str(saved[key])
    return values


def runtime_status() -> tuple[Path | None, Path | None, str]:
    python, model = density_python(), density_model()
    missing: list[str] = []
    if not (engine_root() / "main.py").is_file() or not (service_root() / "web_bridge.py").is_file():
        missing.append("motor banana-density")
    if python is None:
        missing.append("entorno Python del analizador")
    if model is None:
        missing.append("modelo YOLO best.pt")
    message = "Falta: " + ", ".join(missing) + "." if missing else "Motor de densidad listo para ejecutar el flujo completo."
    return python, model, message


def job_dir(job_id: UUID | str) -> Path:
    return density_root() / "jobs" / str(job_id)


def job_file(job_id: UUID | str) -> Path:
    return job_dir(job_id) / "job.json"


def write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".partial")
    temp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(temp, path)


def read_job(job_id: UUID | str) -> dict[str, Any]:
    path = job_file(job_id)
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Análisis de densidad no encontrado.")
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError, TypeError) as error:
        raise HTTPException(status_code=409, detail="El estado local del análisis está dañado.") from error
    if not isinstance(data, dict):
        raise HTTPException(status_code=409, detail="El estado local del análisis es inválido.")
    return data


def update_job(job_id: UUID | str, **changes: Any) -> dict[str, Any]:
    with LOCK:
        data = read_job(job_id)
        data.update(changes)
        data["updated_at"] = now()
        write_json(job_file(job_id), data)
        return data


def save_upload(upload: UploadFile, path: Path, max_bytes: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    total = 0
    with path.open("wb") as target:
        while chunk := upload.file.read(1024 * 1024):
            total += len(chunk)
            if total > max_bytes:
                target.close()
                path.unlink(missing_ok=True)
                raise HTTPException(status_code=413, detail="El archivo supera el límite local permitido.")
            target.write(chunk)
    if total == 0:
        path.unlink(missing_ok=True)
        raise HTTPException(status_code=422, detail="El archivo cargado está vacío.")


def private_asset_path(store: DBILocalObjectStore, asset: AnalysisInputAsset) -> Path:
    address = DBIStoragePolicy.build_address(
        tenant_ref=asset.tenant_ref,
        purpose=DBIStoragePurpose.ANALYSIS_INPUT,
        object_id=asset.id,
    )
    if address.object_key != asset.object_key:
        raise HTTPException(status_code=409, detail="La ortofoto no coincide con su objeto privado.")
    root = (store.root / "objects").resolve()
    path = (root / Path(*address.object_key.split("/"))).resolve()
    if root not in path.parents or not path.is_file() or path.stat().st_size != asset.size_bytes:
        raise HTTPException(status_code=409, detail="No se encontró la ortofoto privada verificada.")
    return path


def scoped_inputs(
    session: Session,
    company_id: int,
    farm_id: UUID,
    plot_id: UUID,
    asset_id: UUID,
    store: DBILocalObjectStore,
) -> tuple[Farm, Plot, AnalysisInputAsset, Path]:
    farm = session.get(Farm, farm_id)
    if farm is None or farm.organization_ref != _organization_ref(company_id):
        raise HTTPException(status_code=404, detail="Finca DBI no encontrada.")
    plot = session.get(Plot, plot_id)
    if plot is None or plot.farm_id != farm_id:
        raise HTTPException(status_code=404, detail="Lote DBI no encontrado.")
    asset = session.get(AnalysisInputAsset, asset_id)
    if (
        asset is None or asset.tenant_ref != _tenant_ref() or asset.farm_id != farm_id
        or asset.plot_id != plot_id or asset.asset_kind != "orthophoto" or asset.status != "verified"
    ):
        raise HTTPException(status_code=404, detail="Ortofoto verificada no encontrada para este lote.")
    return farm, plot, asset, private_asset_path(store, asset)


def prepare_job(
    company: Company,
    farm: Farm,
    plot: Plot,
    asset: AnalysisInputAsset,
    orthophoto: Path,
    excel: UploadFile,
    sheet: str,
    density: float,
    exclusions: UploadFile | None,
) -> UUID:
    python, model, message = runtime_status()
    if python is None or model is None:
        raise HTTPException(status_code=503, detail=message)
    sheet = sheet.strip()
    if not sheet:
        raise HTTPException(status_code=422, detail="Indique la hoja del Excel.")
    if not (excel.filename or "").lower().endswith((".xls", ".xlsx")):
        raise HTTPException(status_code=422, detail="Las coordenadas deben cargarse en Excel (.xls o .xlsx).")
    if exclusions and not (exclusions.filename or "").lower().endswith(".gpkg"):
        raise HTTPException(status_code=422, detail="Las exclusiones deben cargarse como GeoPackage (.gpkg).")

    job_id = uuid4()
    base = job_dir(job_id)
    inputs, output = base / "inputs", base / "runs"
    inputs.mkdir(parents=True, exist_ok=False)
    output.mkdir(parents=True, exist_ok=True)
    excel_path = inputs / f"coordenadas{Path(excel.filename or 'limite.xlsx').suffix.lower()}"
    save_upload(excel, excel_path, 100 * 1024 * 1024)
    exclusions_path: Path | None = None
    if exclusions:
        exclusions_path = inputs / "exclusiones.gpkg"
        save_upload(exclusions, exclusions_path, 2 * 1024 * 1024 * 1024)

    company_name = str(getattr(company, "nombre", None) or getattr(company, "name", None) or "").strip()
    farm_name = str(getattr(farm, "name", "") or farm.id).strip()
    plot_name = str(getattr(plot, "name", "") or "").strip()
    t = technical_defaults()
    request_data = {
        "farm_name": f"{farm_name} - {plot_name}" if plot_name else farm_name,
        "producer": company_name,
        "orthophoto": str(orthophoto),
        "boundary_excel": str(excel_path),
        "boundary_sheet": sheet,
        "target_density": str(density),
        "model_path": str(model),
        "output_root": str(output),
        "report_date": "",
        "exclusions_gpkg": str(exclusions_path) if exclusions_path else "",
        "exclusions_layer": "COMBINAR TODAS LAS CAPAS" if exclusions_path else "",
        **t,
    }
    request_path, config_path = base / "request.json", base / "configuracion_web.yaml"
    write_json(request_path, request_data)
    bridge = service_root() / "web_bridge.py"
    prepared = subprocess.run(
        [str(python), str(bridge), "prepare", str(request_path), str(config_path), str(engine_root())],
        cwd=service_root(), capture_output=True, text=True, encoding="utf-8", errors="replace",
        timeout=180, check=False,
    )
    if prepared.returncode != 0 or not config_path.is_file():
        detail = (prepared.stdout + "\n" + prepared.stderr).strip()[-1800:]
        raise HTTPException(status_code=422, detail=f"No se pudo preparar el análisis con el motor actual. {detail}".strip())

    created = now()
    write_json(job_file(job_id), {
        "job_id": str(job_id), "company_id": int(company.id), "farm_id": str(farm.id),
        "plot_id": str(plot.id), "orthophoto_asset_id": str(asset.id), "status": "prepared",
        "current_stage": None, "completed_stages": [], "run_directory": None,
        "config_path": str(config_path), "output_root": str(output), "process_pid": None,
        "report_path": None, "error": None, "created_at": created, "updated_at": created,
    })
    return job_id


def discover_run(output: Path) -> Path | None:
    if not output.is_dir():
        return None
    runs = [p for p in output.iterdir() if p.is_dir() and (p / "estado_pipeline.json").is_file()]
    return max(runs, key=lambda p: p.stat().st_mtime) if runs else None


def pipeline_state(job: dict[str, Any]) -> dict[str, Any] | None:
    run_raw = str(job.get("run_directory") or "").strip()
    run = Path(run_raw) if run_raw else discover_run(Path(str(job.get("output_root") or "")))
    if run is None or not (run / "estado_pipeline.json").is_file():
        return None
    try:
        value = json.loads((run / "estado_pipeline.json").read_text(encoding="utf-8-sig"))
    except (OSError, ValueError, TypeError):
        return None
    return value if isinstance(value, dict) else None


def monitor(job_id: UUID, process: subprocess.Popen[str]) -> None:
    completed = list(read_job(job_id).get("completed_stages") or [])
    previous: str | None = None
    try:
        with (job_dir(job_id) / "pipeline.out.log").open("a", encoding="utf-8", errors="replace") as log:
            assert process.stdout is not None
            for line in process.stdout:
                log.write(line); log.flush()
                text = line.strip()
                if text.startswith("ETAPA:"):
                    key = TITLE_KEYS.get(text.split(":", 1)[1].strip())
                    if key:
                        if previous and previous not in completed:
                            completed.append(previous)
                        previous = key
                        update_job(job_id, completed_stages=completed, current_stage=key)
                elif text.startswith("[COMPLETADA]"):
                    for title, key in TITLE_KEYS.items():
                        if title in text and key not in completed:
                            completed.append(key)
                            update_job(job_id, completed_stages=completed, current_stage=key)
                            break
        code = process.wait()
        latest = read_job(job_id)
        run = discover_run(Path(str(latest["output_root"])))
        state = pipeline_state({**latest, "run_directory": str(run) if run else None})
        report: str | None = None
        if state and isinstance(state.get("artifacts"), dict):
            candidate = str(state["artifacts"].get("technical_report_pdf") or "").strip()
            if candidate and Path(candidate).is_file():
                report = candidate
        stopped = str(latest.get("status")) == "stopped"
        completed_ok = code == 0 and state is not None and state.get("status") == "completed"
        final = "stopped" if stopped else "completed" if completed_ok else "failed"
        error = str(latest.get("error")) if stopped and latest.get("error") else None
        if final == "failed":
            errors = state.get("errors") if state else None
            error = str(errors[-1]) if isinstance(errors, list) and errors else f"El motor terminó con código {code}. Revise el log del análisis."
        update_job(job_id, status=final, current_stage=None, process_pid=None,
                   run_directory=str(run) if run else None, report_path=report, error=error)
    except Exception as error:  # pragma: no cover
        try:
            update_job(job_id, status="failed", process_pid=None, error=f"{type(error).__name__}: {error}")
        except Exception:
            pass
    finally:
        with LOCK:
            PROCESSES.pop(str(job_id), None)


def launch(job_id: UUID, resume: bool = False) -> None:
    python, _model, message = runtime_status()
    if python is None:
        raise HTTPException(status_code=503, detail=message)
    with LOCK:
        current = PROCESSES.get(str(job_id))
        if current is not None and current.poll() is None:
            raise HTTPException(status_code=409, detail="El análisis ya está en ejecución.")
        job = read_job(job_id)
        engine = engine_root()
        command = [str(python), str(engine / "main.py"), "run-full-analysis", str(job["config_path"])]
        if resume:
            raw = str(job.get("run_directory") or "").strip()
            run = Path(raw) if raw else discover_run(Path(str(job["output_root"])))
            if run is None:
                raise HTTPException(status_code=409, detail="No existe una ejecución que pueda reanudarse.")
            command += ["--resume-run", str(run)]
        process = subprocess.Popen(
            command, cwd=engine, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, encoding="utf-8", errors="replace", bufsize=1,
        )
        PROCESSES[str(job_id)] = process
        update_job(job_id, status="running", current_stage=None, process_pid=process.pid, error=None)
        threading.Thread(target=monitor, args=(job_id, process), daemon=True).start()


def stage_responses(job: dict[str, Any]) -> list[DensityStageResponse]:
    state = pipeline_state(job)
    state_stages = state.get("stages") if state else None
    completed = set(map(str, job.get("completed_stages") or []))
    current = str(job.get("current_stage") or "")
    result: list[DensityStageResponse] = []
    for key, title in STAGES:
        status_value, error = "pending", None
        if isinstance(state_stages, dict) and isinstance(state_stages.get(key), dict):
            raw = state_stages[key]
            status_value = str(raw.get("status") or "pending")
            error = str(raw.get("error")) if raw.get("error") else None
        elif key in completed:
            status_value = "completed"
        elif key == current:
            status_value = "running"
        result.append(DensityStageResponse(key=key, title=title, status=status_value, error=error))
    return result


def response(job: dict[str, Any]) -> DensityJobResponse:
    stages = stage_responses(job)
    done = sum(item.status == "completed" for item in stages)
    bonus = 0.5 if any(item.status == "running" for item in stages) else 0.0
    report = str(job.get("report_path") or "").strip()
    return DensityJobResponse(
        job_id=UUID(str(job["job_id"])), company_id=int(job["company_id"]),
        farm_id=UUID(str(job["farm_id"])), plot_id=UUID(str(job["plot_id"])),
        orthophoto_asset_id=UUID(str(job["orthophoto_asset_id"])), status=str(job.get("status") or "unknown"),
        current_stage=str(job["current_stage"]) if job.get("current_stage") else None,
        progress_percent=min(100, max(0, int(round(((done + bonus) / len(STAGES)) * 100)))),
        stages=stages, report_ready=bool(report and Path(report).is_file()),
        error=str(job["error"]) if job.get("error") else None,
        created_at=str(job["created_at"]), updated_at=str(job["updated_at"]),
    )


def authorize_job(company_id: int, session: Session, user: User, job_id: UUID) -> dict[str, Any]:
    _require_local_pilot(); _require_company(session, user, company_id)
    job = read_job(job_id)
    if int(job.get("company_id") or 0) != company_id:
        raise HTTPException(status_code=404, detail="Análisis de densidad no encontrado.")
    return job


def latest_job(company_id: int) -> dict[str, Any] | None:
    root = density_root() / "jobs"
    candidates: list[dict[str, Any]] = []
    if root.is_dir():
        for path in root.glob("*/job.json"):
            try:
                data = json.loads(path.read_text(encoding="utf-8-sig"))
            except (OSError, ValueError, TypeError):
                continue
            if isinstance(data, dict) and int(data.get("company_id") or 0) == company_id:
                candidates.append(data)
    return max(candidates, key=lambda x: str(x.get("updated_at") or x.get("created_at") or "")) if candidates else None


@router.get("/companies/{company_id}/density/runtime", response_model=DensityRuntimeResponse)
def get_runtime(company_id: int, legacy_session: LegacySession, user: CurrentUser) -> DensityRuntimeResponse:
    _require_local_pilot(); _require_company(legacy_session, user, company_id)
    python, model, message = runtime_status()
    engine_ready = python is not None and (engine_root() / "main.py").is_file() and (service_root() / "web_bridge.py").is_file()
    return DensityRuntimeResponse(ready=engine_ready and model is not None, engine_ready=engine_ready,
                                  model_ready=model is not None, message=message)


@router.post("/companies/{company_id}/density/jobs", response_model=DensityJobCreatedResponse,
             status_code=status.HTTP_202_ACCEPTED)
def create_job(
    company_id: int, request: Request, legacy_session: LegacySession, dbi_session: DBISession, user: CurrentUser,
    farm_id: Annotated[UUID, Form()], plot_id: Annotated[UUID, Form()],
    orthophoto_asset_id: Annotated[UUID, Form()], boundary_sheet: Annotated[str, Form(min_length=1, max_length=120)],
    target_density: Annotated[float, Form(gt=0, le=10000)], boundary_excel: Annotated[UploadFile, File()],
    exclusions_gpkg: UploadFile | None = File(default=None),
) -> DensityJobCreatedResponse:
    _require_local_pilot()
    company = _require_company(legacy_session, user, company_id)
    farm, plot, asset, ortho = scoped_inputs(
        dbi_session, company_id, farm_id, plot_id, orthophoto_asset_id, _local_store(request)
    )
    job_id = prepare_job(company, farm, plot, asset, ortho, boundary_excel, boundary_sheet, target_density, exclusions_gpkg)
    launch(job_id)
    return DensityJobCreatedResponse(job_id=job_id, status="running")


@router.get("/companies/{company_id}/density/jobs/latest", response_model=DensityJobResponse | None)
def get_latest_job(company_id: int, legacy_session: LegacySession, user: CurrentUser) -> DensityJobResponse | None:
    _require_local_pilot(); _require_company(legacy_session, user, company_id)
    job = latest_job(company_id)
    return response(job) if job else None


@router.get("/companies/{company_id}/density/jobs/{job_id}", response_model=DensityJobResponse)
def get_job(company_id: int, job_id: UUID, legacy_session: LegacySession, user: CurrentUser) -> DensityJobResponse:
    return response(authorize_job(company_id, legacy_session, user, job_id))


@router.post("/companies/{company_id}/density/jobs/{job_id}/resume", response_model=DensityJobCreatedResponse)
def resume_job(company_id: int, job_id: UUID, legacy_session: LegacySession, user: CurrentUser) -> DensityJobCreatedResponse:
    job = authorize_job(company_id, legacy_session, user, job_id)
    if str(job.get("status")) not in {"failed", "stopped", "paused"}:
        raise HTTPException(status_code=409, detail="Este análisis no está disponible para reanudación.")
    launch(job_id, resume=True)
    return DensityJobCreatedResponse(job_id=job_id, status="running")


@router.post("/companies/{company_id}/density/jobs/{job_id}/stop", response_model=DensityJobCreatedResponse)
def stop_job(company_id: int, job_id: UUID, legacy_session: LegacySession, user: CurrentUser) -> DensityJobCreatedResponse:
    job = authorize_job(company_id, legacy_session, user, job_id)
    if str(job.get("status")) != "running":
        raise HTTPException(status_code=409, detail="El análisis no está en ejecución.")
    process = PROCESSES.get(str(job_id))
    pid = int(job.get("process_pid") or 0)
    try:
        if os.name == "nt" and pid > 0:
            subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True, check=False)
        elif process is not None and process.poll() is None:
            process.send_signal(signal.SIGTERM)
    finally:
        update_job(job_id, status="stopped", process_pid=None, error="Ejecución detenida por el usuario.")
    return DensityJobCreatedResponse(job_id=job_id, status="stopped")


@router.get("/companies/{company_id}/density/jobs/{job_id}/report")
def download_report(company_id: int, job_id: UUID, legacy_session: LegacySession, user: CurrentUser) -> FileResponse:
    job = authorize_job(company_id, legacy_session, user, job_id)
    report_raw, run_raw = str(job.get("report_path") or "").strip(), str(job.get("run_directory") or "").strip()
    if not report_raw or not run_raw:
        raise HTTPException(status_code=404, detail="El informe técnico todavía no está disponible.")
    report, run = Path(report_raw).resolve(strict=False), Path(run_raw).resolve(strict=False)
    if run != report and run not in report.parents:
        raise HTTPException(status_code=409, detail="La ruta del informe no pertenece a esta ejecución.")
    if not report.is_file() or report.suffix.lower() != ".pdf":
        raise HTTPException(status_code=404, detail="El informe técnico todavía no está disponible.")
    return FileResponse(report, media_type="application/pdf", filename=report.name)
