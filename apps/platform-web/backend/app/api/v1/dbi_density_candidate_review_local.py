"""Revisión técnica de candidatos para ejecuciones locales de densidad DBI."""
from __future__ import annotations

import json
import subprocess
import threading
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

from fastapi import APIRouter, File, HTTPException, UploadFile, status
from fastapi.responses import FileResponse
from pydantic import BaseModel

from .dbi_density_local import (
    CurrentUser,
    LegacySession,
    authorize_job,
    density_python,
    engine_root,
    job_dir,
    now,
    save_upload,
    service_root,
    update_job,
    write_json,
)

router = APIRouter(prefix="/dbi/pilot", tags=["dbi-density-candidate-review-local"])
REVIEW_LOCK = threading.RLock()
REVIEW_PROCESSES: dict[str, subprocess.Popen[str]] = {}


class CandidateReviewStatusResponse(BaseModel):
    available: bool
    candidates_ready: bool
    status: str
    error: str | None = None
    updated_at: str | None = None


def _review_state_path(job_id: UUID | str) -> Path:
    return job_dir(job_id) / "candidate_review_web.json"


def _read_review_state(job_id: UUID | str) -> dict[str, Any]:
    path = _review_state_path(job_id)
    if not path.is_file():
        return {"status": "idle", "error": None, "updated_at": None}
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError, TypeError):
        return {"status": "failed", "error": "El estado de la revisión técnica está dañado.", "updated_at": None}
    return value if isinstance(value, dict) else {"status": "failed", "error": "El estado de la revisión técnica es inválido.", "updated_at": None}


def _write_review_state(job_id: UUID | str, **changes: Any) -> dict[str, Any]:
    with REVIEW_LOCK:
        current = _read_review_state(job_id)
        current.update(changes)
        current["updated_at"] = now()
        write_json(_review_state_path(job_id), current)
        return current


def _review_engine_available() -> bool:
    python = density_python()
    module = engine_root() / "src" / "banana_analyzer" / "candidate_review.py"
    return python is not None and module.is_file()


def _run_directory(job: dict[str, Any]) -> Path:
    raw = str(job.get("run_directory") or "").strip()
    if not raw:
        raise HTTPException(status_code=409, detail="La ejecución completa todavía no tiene un directorio de resultados.")
    run = Path(raw).expanduser().resolve(strict=False)
    if not run.is_dir():
        raise HTTPException(status_code=409, detail="No se encontró el directorio de resultados de esta ejecución.")
    return run


def _candidate_file(run: Path) -> Path | None:
    candidates = [
        path
        for path in run.rglob("candidatos_siembra.gpkg")
        if path.is_file()
        and "revision_tecnica_candidatos" not in path.parts
        and path.parent.name.startswith("oportunidades_siembra_")
    ]
    return max(candidates, key=lambda path: path.stat().st_mtime) if candidates else None


def _latest_report(run: Path) -> Path | None:
    reports = [
        path
        for path in run.rglob("*.pdf")
        if path.is_file()
        and "salidas_anteriores" not in path.parts
        and "07_reporte" in path.parts
    ]
    return max(reports, key=lambda path: path.stat().st_mtime) if reports else None


def _response(job_id: UUID, job: dict[str, Any]) -> CandidateReviewStatusResponse:
    available = _review_engine_available()
    candidates_ready = False
    if str(job.get("status") or "") == "completed" and str(job.get("run_directory") or "").strip():
        try:
            candidates_ready = _candidate_file(_run_directory(job)) is not None
        except HTTPException:
            candidates_ready = False
    state = _read_review_state(job_id)
    return CandidateReviewStatusResponse(
        available=available,
        candidates_ready=candidates_ready,
        status=str(state.get("status") or "idle"),
        error=str(state["error"]) if state.get("error") else None,
        updated_at=str(state["updated_at"]) if state.get("updated_at") else None,
    )


def _monitor_review(job_id: UUID, run: Path, process: subprocess.Popen[str]) -> None:
    tail: list[str] = []
    log_path = job_dir(job_id) / "candidate-review.out.log"
    try:
        with log_path.open("a", encoding="utf-8", errors="replace") as log:
            assert process.stdout is not None
            for line in process.stdout:
                log.write(line)
                log.flush()
                text = line.strip()
                if text:
                    tail.append(text)
                    if len(tail) > 30:
                        tail.pop(0)
        code = process.wait()
        if code == 0:
            report = _latest_report(run)
            if report is not None:
                update_job(job_id, report_path=str(report))
            _write_review_state(job_id, status="completed", error=None, process_pid=None)
        else:
            detail = " | ".join(tail[-8:])[-1800:]
            _write_review_state(
                job_id,
                status="failed",
                error=detail or f"La revisión de candidatos terminó con código {code}.",
                process_pid=None,
            )
    except Exception as error:  # pragma: no cover - protección del monitor local
        try:
            _write_review_state(
                job_id,
                status="failed",
                error=f"{type(error).__name__}: {error}",
                process_pid=None,
            )
        except Exception:
            pass
    finally:
        with REVIEW_LOCK:
            REVIEW_PROCESSES.pop(str(job_id), None)


def _launch_review(job_id: UUID, run: Path, reviewed_file: Path) -> None:
    python = density_python()
    if python is None or not _review_engine_available():
        raise HTTPException(
            status_code=503,
            detail="El motor local instalado no incorpora la revisión técnica de candidatos.",
        )

    with REVIEW_LOCK:
        current = REVIEW_PROCESSES.get(str(job_id))
        if current is not None and current.poll() is None:
            raise HTTPException(status_code=409, detail="Ya existe una revisión de candidatos en ejecución.")

        bridge = service_root() / "web_bridge.py"
        command = [
            str(python),
            str(bridge),
            "candidate-review",
            str(run),
            str(reviewed_file),
            str(engine_root()),
        ]
        process = subprocess.Popen(
            command,
            cwd=service_root(),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
        )
        REVIEW_PROCESSES[str(job_id)] = process
        _write_review_state(
            job_id,
            status="running",
            error=None,
            process_pid=process.pid,
            source_file=str(reviewed_file),
        )
        threading.Thread(
            target=_monitor_review,
            args=(job_id, run, process),
            daemon=True,
        ).start()


@router.get(
    "/companies/{company_id}/density/jobs/{job_id}/candidate-review",
    response_model=CandidateReviewStatusResponse,
)
def get_candidate_review_status(
    company_id: int,
    job_id: UUID,
    legacy_session: LegacySession,
    user: CurrentUser,
) -> CandidateReviewStatusResponse:
    job = authorize_job(company_id, legacy_session, user, job_id)
    return _response(job_id, job)


@router.get("/companies/{company_id}/density/jobs/{job_id}/candidates")
def download_candidates(
    company_id: int,
    job_id: UUID,
    legacy_session: LegacySession,
    user: CurrentUser,
) -> FileResponse:
    job = authorize_job(company_id, legacy_session, user, job_id)
    if str(job.get("status") or "") != "completed":
        raise HTTPException(status_code=409, detail="Los candidatos estarán disponibles cuando finalice el análisis completo.")
    run = _run_directory(job)
    candidate = _candidate_file(run)
    if candidate is None:
        raise HTTPException(status_code=404, detail="No se encontró la capa de candidatos de siembra de esta ejecución.")
    return FileResponse(
        candidate,
        media_type="application/geopackage+sqlite3",
        filename=f"candidatos_siembra_{str(job_id)[:8]}.gpkg",
    )


@router.post(
    "/companies/{company_id}/density/jobs/{job_id}/candidate-review",
    response_model=CandidateReviewStatusResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
def incorporate_candidate_review(
    company_id: int,
    job_id: UUID,
    legacy_session: LegacySession,
    user: CurrentUser,
    reviewed_candidates: UploadFile = File(...),
) -> CandidateReviewStatusResponse:
    job = authorize_job(company_id, legacy_session, user, job_id)
    if str(job.get("status") or "") != "completed":
        raise HTTPException(status_code=409, detail="La revisión de candidatos requiere un análisis completo finalizado.")
    if not _review_engine_available():
        raise HTTPException(status_code=503, detail="El motor local instalado no incorpora la revisión técnica de candidatos.")
    if not (reviewed_candidates.filename or "").lower().endswith(".gpkg"):
        raise HTTPException(
            status_code=422,
            detail="Para la integración web cargue la revisión como un único archivo GeoPackage (.gpkg).",
        )

    run = _run_directory(job)
    if _candidate_file(run) is None:
        raise HTTPException(status_code=404, detail="No existe una capa de candidatos que pueda revisarse en esta ejecución.")

    incoming = job_dir(job_id) / "candidate_reviews" / "incoming"
    review_path = incoming / f"{uuid4()}_candidatos_revisados.gpkg"
    save_upload(reviewed_candidates, review_path, 512 * 1024 * 1024)
    _launch_review(job_id, run, review_path)
    return _response(job_id, read_job_compat(job_id))


def read_job_compat(job_id: UUID) -> dict[str, Any]:
    """Lee el job tras lanzar la revisión sin duplicar su contrato de persistencia."""
    from .dbi_density_local import read_job

    return read_job(job_id)
