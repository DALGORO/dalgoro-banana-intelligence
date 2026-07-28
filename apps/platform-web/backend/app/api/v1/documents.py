from typing import Dict, Any, List
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from pydantic import BaseModel

from app.api.deps import db as get_db, current_user
from app.api.deps import admin
from app.models.company import Company
from app.models.document import Document
from app.models.user import User
from app.services.templates import generate_document
from app.services import iperc_derivatives as ipd
from app.services.sst_rules import normalize_activity
from pathlib import Path
from fastapi.responses import FileResponse, Response
from app.services.sst_requirements import build_requirements
from app.services.storage import delete_storage_path
from app.services.storage import get_bytes_any
from fastapi.responses import StreamingResponse

router = APIRouter(prefix="/documents", tags=["documents"])


# --------- Pydantic payloads ---------
class GeneratePayload(BaseModel):
    company_id: int
    template_code: str
    data: Dict[str, Any]
    
def _ensure_company_access(session: Session, company_id: int, user: User) -> Company:
    company = session.get(Company, company_id)
    if not company:
        raise HTTPException(status_code=404, detail="Empresa no encontrada")

    if getattr(user, "role", "").upper() == "ADMIN" or company.owner_id == user.id:
        return company

    raise HTTPException(status_code=403, detail="No autorizado")


def _ensure_document_access(session: Session, doc_id: int, user: User) -> Document:
    doc = session.get(Document, doc_id)
    if not doc:
        raise HTTPException(status_code=404, detail="Documento no encontrado")

    _ensure_company_access(session, doc.company_id, user)
    return doc

# --------- Endpoints ---------

@router.get("/company/{company_id}")
def list_company_documents(
    company_id: int,
    session: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    """
    Lista documentos ya generados (instancias) para una empresa.
    """
    _ensure_company_access(session, company_id, user)

    docs: List[Document] = (
        session.query(Document)
        .filter(Document.company_id == company_id)
        .filter(Document.storage_path.isnot(None))
        .filter(Document.storage_path != "")
        .order_by(Document.created_at.desc())
        .all()
    )

    return [
        {
            "id": d.id,
            "title": getattr(d, "title", None),
            "kind": getattr(d, "kind", None),
            "created_at": d.created_at,
            "mime": d.mime,
        }
        for d in docs
    ]

@router.get("/{doc_id}/stream")
def stream_document(
    doc_id: int,
    session: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    """
    Devuelve el archivo binario del documento (para visor/descarga).
    """
    doc: Document = _ensure_document_access(session, doc_id, user)

    # 1) Intentar servir como archivo local (mejor performance/memoria)
    p = Path(doc.storage_path or "")
    if not p.is_file():
        # si la ruta guardada es relativa, resuélvela respecto a /backend/storage
        base_storage = Path(__file__).resolve().parents[2] / "storage"
        rp = (base_storage / (doc.storage_path or "")).resolve()
        if rp.is_file():
            p = rp

    if p.is_file():
        # Deriva extensión de la ruta física (si por alguna razón fuera .bin,
        # igual cae al cálculo por MIME más abajo)
        suffix = p.suffix or ""
        # Si no hay suffix útil, intenta por MIME:
        if not suffix or suffix.lower() == ".bin":
            mime_ = (doc.mime or "").lower()
            if "spreadsheetml.sheet" in mime_:
                suffix = ".xlsx"
            elif "wordprocessingml.document" in mime_:
                suffix = ".docx"
            elif "pdf" in mime_:
                suffix = ".pdf"
            elif "json" in mime_:
                suffix = ".json"
            else:
                suffix = ".bin"

        file_resp = FileResponse(
            path=str(p),
            media_type=doc.mime or "application/octet-stream",
        )
        # Forzamos nombre con trazabilidad (el title YA es IPERC-2025-11-20-V001):
        file_resp.headers["Content-Disposition"] = f'attachment; filename="{doc.title}{suffix}"'
        # Exponer headers al front:
        file_resp.headers["Access-Control-Expose-Headers"] = "Content-Disposition, Content-Type"
        return file_resp

    # --- Fallback bytes (GCS, etc.) ---
    mime = (doc.mime or "application/octet-stream").lower()
    ext = ".bin"
    if "spreadsheetml.sheet" in mime:
        ext = ".xlsx"
    elif "wordprocessingml.document" in mime:
        ext = ".docx"
    elif "pdf" in mime:
        ext = ".pdf"
    elif "json" in mime:
        ext = ".json"

    # Leer bytes desde el storage abstracto (S3, GCS, etc.)
    data = get_bytes_any(doc.storage_path or "") or b""

    return Response(
        content=data,
        media_type=mime,
        headers={
            "Content-Disposition": f'attachment; filename="{doc.title}{ext}"',
            "Access-Control-Expose-Headers": "Content-Disposition, Content-Type",
        },
    )

@router.post("/generate")
def generate(
    payload: GeneratePayload,
    db: Session = Depends(get_db),
    user=Depends(current_user),
):
    """
    Genera una nueva instancia con código BASE-YYYY-MM-DD-VNNN y guarda el archivo.
    Completa actividad/riesgo/trabajadores si no llegan o vienen vacíos.
    """
    company = db.query(Company).filter(Company.id == payload.company_id).first()
    if not company:
        raise HTTPException(status_code=404, detail="Empresa no encontrada")

    # ✅ permitir ADMIN o dueño de la empresa
    if not (getattr(user, "role", "").upper() == "ADMIN" or company.owner_id == user.id):
        raise HTTPException(status_code=403, detail="No autorizado")

    # 1) Tomar datos base desde la empresa
    activity = (
        getattr(company, "actividad", None)
        or getattr(company, "activity", None)
        or "GENERICO"
    )
    risk = (
        getattr(company, "riesgo", None)
        or getattr(company, "risk_level", None)
        or ""
    )
    workers = (
        getattr(company, "trabajadores", None)
        or getattr(company, "workers", None)
        or 0
    )

    # 2) Asegurar que viajen al motor de plantillas (sobrescribe si vienen vacíos)
    data = dict(payload.data or {})  # copia segura

    def _blank(v):
        if v is None:
            return True
        if isinstance(v, str) and v.strip() == "":
            return True
        return False

    # actividad
    if _blank(data.get("actividad")):
        data["actividad"] = activity

    # riesgo (en mayúsculas)
    if _blank(data.get("riesgo")):
        data["riesgo"] = str(risk).upper()

    # trabajadores: si viene vacío, None o 0 ⇒ usa el de la empresa
    t_val = data.get("trabajadores")
    try:
        t_num = int(t_val) if (t_val is not None and str(t_val).strip() != "") else None
    except Exception:
        t_num = None
    if t_num is None or t_num == 0:
        data["trabajadores"] = int(workers or 0)
    else:
        data["trabajadores"] = t_num

    # 3) Normalizar actividad para búsqueda de plantilla
    activity_norm = normalize_activity(activity)

    # 4) Generar documento con los datos ya corregidos
    legal_txt = None
    try:
        req = build_requirements(activity_norm, data["trabajadores"], data["riesgo"])
        for it in req.get("items", []):
            if str(it.get("code")).upper() == str(payload.template_code).upper():
                legal_txt = it.get("legal")
                break
    except Exception:
        legal_txt = None

    # ← NUEVO: Enriquecer `data` con derivados del IPERC según el código de plantilla
    code_upper = (payload.template_code or "").upper()

    if code_upper == "CAP-01" and "iperc_training_topics" not in data:
        data["iperc_training_topics"] = ipd.derive_training_topics(db=db, company_id=company.id, activity=activity_norm)
    elif code_upper == "VIG-SAL-01" and "iperc_health_surveillance" not in data:
        data["iperc_health_surveillance"] = ipd.derive_health_surveillance(db=db, company_id=company.id, activity=activity_norm)
    elif code_upper == "EPP-01" and "iperc_critical_epp" not in data:
        data["iperc_critical_epp"] = ipd.derive_critical_epp(db=db, company_id=company.id, activity=activity_norm)
    elif code_upper == "EMG-01" and "iperc_emergency_scenarios" not in data:
        data["iperc_emergency_scenarios"] = ipd.derive_emergency_scenarios(db=db, company_id=company.id, activity=activity_norm)
    elif code_upper == "MON-AMB-01" and "iperc_env_monitoring" not in data:
        data["iperc_env_monitoring"] = ipd.derive_env_monitoring(db=db, company_id=company.id, activity=activity_norm)
    elif (code_upper.startswith("PT-") or code_upper.startswith("PROC-")) and "iperc_work_permits" not in data:
        data["iperc_work_permits"] = ipd.derive_work_permits(db=db, company_id=company.id, activity=activity_norm)

    # 5) Generar documento con los datos ya corregidos y meta extra (legal)
    try:
        inst = generate_document(
            db=db,
            company=company,
            template_code=payload.template_code,
            activity=activity_norm,
            data=data,
            risk_level=data["riesgo"],
            workers=data["trabajadores"],
            extra_meta={"legal": legal_txt},
            user_id=user.id,  # ← PASA EL USUARIO
        )

    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    return {
        "id": inst.id,
        "code_full": inst.title,
        "storage_path": inst.storage_path,
        "created_at": inst.created_at,
    }

@router.delete("/{doc_id}", status_code=204, dependencies=[Depends(admin)])
def delete_document(
    doc_id: int,
    session: Session = Depends(get_db),
):
    doc = session.get(Document, doc_id)
    if not doc:
        raise HTTPException(status_code=404, detail="Documento no encontrado")

    # 1) intentar eliminar el archivo físico (GCS o local) sin romper la petición
    try:
        if doc.storage_path:
            delete_storage_path(doc.storage_path)
    except Exception:
        # no elevamos error: aunque falle el borrado físico, se remueve el registro
        pass

    # 2) eliminar el registro en BD
    session.delete(doc)
    session.commit()
    return
    