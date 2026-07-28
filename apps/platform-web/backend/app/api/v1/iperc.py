import json, os
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from typing import Optional, List, Dict, Any
from sqlalchemy.orm import Session
from app.db.session import get_db
from app.models.iperc_item import IPERCItem
from app.api.deps import current_user
from app.models.company import Company
from app.services.iperc_presets import get_activity_presets, list_process_names, find_process

class IPERCItemIn(BaseModel):
    activity: str
    process: str
    job: str
    task: str
    hazard_group: str
    hazard: str
    event: str
    consequence: str
    exposed_persons: Optional[str] = None
    probability: Optional[float] = None
    severity: Optional[float] = None
    risk_level: Optional[str] = None
    controls_existing_engineering: Optional[List[str] | Dict[str, Any]] = None
    controls_existing_admin: Optional[List[str] | Dict[str, Any]] = None
    controls_existing_epp: Optional[List[str] | Dict[str, Any]] = None
    controls_planned_engineering: Optional[List[str] | Dict[str, Any]] = None
    controls_planned_admin: Optional[List[str] | Dict[str, Any]] = None
    controls_planned_epp: Optional[List[str] | Dict[str, Any]] = None
    requires_work_permit: bool = False
    needs_health_surveillance: bool = False
    needs_env_monitoring: bool = False
    critical_epp: Optional[List[str] | Dict[str, Any]] = None
    evidence_refs: Optional[List[str] | Dict[str, Any]] = None
    review_date: Optional[str] = None
    next_review: Optional[str] = None
    status: Optional[str] = "vigente"
    sheet: Optional[str] = "BASE"     # ← NUEVO
    nd: Optional[int] = None          # ← NUEVO
    ne: Optional[int] = None          # ← NUEVO
    nc: Optional[int] = None          # ← NUEVO
    
router = APIRouter(prefix="/iperc", tags=["iperc"])

def gtc45_calc(nd: int|None, ne: int|None, nc: int|None):
    if nd is None or ne is None or nc is None:
        return None, None, None, None
    np = int(nd) * int(ne)
    nr = int(np) * int(nc)
    # rangos típicos GTC-45
    if nr <= 20:
        interp, acc = "TRIVIAL", "ACEPTABLE"
    elif nr <= 70:
        interp, acc = "TOLERABLE", "ACEPTABLE"
    elif nr <= 200:
        interp, acc = "MODERADO", "MEJORAR"
    elif nr <= 400:
        interp, acc = "IMPORTANTE", "NO ACEPTABLE"
    else:
        interp, acc = "INTOLERABLE", "NO ACEPTABLE"
    return np, nr, interp, acc

def serialize(o: IPERCItem) -> Dict[str, Any]:
    return {
        "id": o.id,
        "company_id": o.company_id,
        "activity": o.activity,
        "process": o.process,
        "job": o.job,
        "task": o.task,
        "hazard_group": o.hazard_group,
        "hazard": o.hazard,
        "event": o.event,
        "consequence": o.consequence,
        "exposed_persons": o.exposed_persons,
        "probability": float(o.probability) if o.probability is not None else None,
        "severity": float(o.severity) if o.severity is not None else None,
        "risk_level": o.risk_level,
        "controls_existing_engineering": o.controls_existing_engineering,
        "controls_existing_admin": o.controls_existing_admin,
        "controls_existing_epp": o.controls_existing_epp,
        "controls_planned_engineering": o.controls_planned_engineering,
        "controls_planned_admin": o.controls_planned_admin,
        "controls_planned_epp": o.controls_planned_epp,
        "requires_work_permit": o.requires_work_permit,
        "needs_health_surveillance": o.needs_health_surveillance,
        "needs_env_monitoring": o.needs_env_monitoring,
        "critical_epp": o.critical_epp,
        "evidence_refs": o.evidence_refs,
        "review_date": str(o.review_date) if o.review_date else None,
        "next_review": str(o.next_review) if o.next_review else None,
        "status": o.status,
        "sheet": o.sheet,
        "nd": o.nd, "ne": o.ne, "nc": o.nc,
        "np": o.np, "nr": o.nr,
        "risk_interp": o.risk_interp,
        "acceptable": o.acceptable,
    }

def _check_access(db: Session, company_id: int, user) -> None:
    company = db.query(Company).filter(Company.id == company_id).first()
    if not company:
        raise HTTPException(status_code=404, detail="Empresa no encontrada")
    if not (getattr(user, "role", "").upper() == "ADMIN" or company.owner_id == user.id):
        raise HTTPException(status_code=403, detail="No autorizado")

@router.get("/company/{company_id}")
def list_iperc(company_id: int,
               process: Optional[str] = Query(None),
               job: Optional[str] = Query(None),
               sheet: Optional[str] = Query(None),  # ← sin "BASE" por defecto
               db: Session = Depends(get_db),
               user=Depends(current_user)):
    _check_access(db, company_id, user)
    q = db.query(IPERCItem).filter(IPERCItem.company_id == company_id)
    if sheet:
        q = q.filter(IPERCItem.sheet == sheet)  # ← solo si lo envían
    if process:
        q = q.filter(IPERCItem.process == process)
    if job:
        q = q.filter(IPERCItem.job == job)
    return [serialize(obj) for obj in q.all()]

@router.post("/company/{company_id}")
def create_iperc_items(company_id: int, items: List[IPERCItemIn],
                       db: Session = Depends(get_db),
                       user=Depends(current_user)):
    _check_access(db, company_id, user)
    objs = []
    for it in items:
        data = it.dict()
        data["company_id"] = company_id
        data["sheet"] = (data.get("sheet") or "BASE").upper()
        # cálculo GTC-45 si hay nd/ne/nc
        np, nr, interp, acc = gtc45_calc(data.get("nd"), data.get("ne"), data.get("nc"))
        data["np"], data["nr"], data["risk_interp"], data["acceptable"] = np, nr, interp, acc
        objs.append(IPERCItem(**data))
    db.add_all(objs)
    db.commit()
    for o in objs: db.refresh(o)
    return [serialize(o) for o in objs]

@router.put("/{item_id}")
def update_iperc_item(item_id: int, item: IPERCItemIn,
                      db: Session = Depends(get_db),
                      user=Depends(current_user)):
    obj = db.get(IPERCItem, item_id)
    if not obj:
        raise HTTPException(status_code=404, detail="IPERC item not found")
    _check_access(db, obj.company_id, user)
    for k, v in item.dict().items():
        if v is not None:
            setattr(obj, k, v)
    # recalcular GTC-45
    np, nr, interp, acc = gtc45_calc(obj.nd, obj.ne, obj.nc)
    obj.np, obj.nr, obj.risk_interp, obj.acceptable = np, nr, interp, acc
    db.commit()
    db.refresh(obj)
    return serialize(obj)

@router.delete("/{item_id}")
def delete_iperc_item(item_id: int,
                      db: Session = Depends(get_db),
                      user=Depends(current_user)):
    obj = db.get(IPERCItem, item_id)
    if not obj:
        return {"ok": True}
    _check_access(db, obj.company_id, user)
    db.delete(obj)
    db.commit()
    return {"ok": True}


@router.post("/company/{company_id}/seed/{activity}")
def seed_iperc(company_id: int, activity: str,
               sheet: Optional[str] = Query("BASE"),         # ← NUEVO
               db: Session = Depends(get_db),
               user=Depends(current_user)):
    _check_access(db, company_id, user)

    activity_norm = (activity or "").strip().upper()
    sheet_norm = (sheet or "BASE").strip().upper()          # ← NUEVO

    exists = (
        db.query(IPERCItem)
        .filter(IPERCItem.company_id == company_id,
                IPERCItem.activity == activity_norm,
                IPERCItem.sheet == sheet_norm)              # ← NUEVO
        .first()
    )
    if exists:
        return {"ok": True, "seeded": False, "reason": "already-exists"}

    base_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
    preset_path = os.path.join(base_dir, "presets", "iperc", f"{activity_norm}.json")
    if not os.path.exists(preset_path):
        return {"ok": False, "seeded": False, "error": f"Preset no encontrado: {preset_path}"}

    with open(preset_path, "r", encoding="utf-8") as f:
        preset = json.load(f)

    rows = preset.get("rows", [])
    objs = []
    for r in rows:
        data = dict(r)
        data["company_id"] = company_id
        data["activity"] = activity_norm
        data["sheet"] = sheet_norm
        # si vienen nd/ne/nc en el preset (más adelante), calcula; si no, intenta con probability/severity
        np, nr, interp, acc = gtc45_calc(data.get("nd"), data.get("ne"), data.get("nc"))
        data["np"], data["nr"], data["risk_interp"], data["acceptable"] = np, nr, interp, acc
        objs.append(IPERCItem(**data))

    if not objs:
        return {"ok": False, "seeded": False, "error": "Preset sin filas"}

    db.add_all(objs)
    db.commit()
    return {"ok": True, "seeded": True, "count": len(objs)}

@router.get("/company/{company_id}/sheets")
def list_sheets(company_id: int,
                db: Session = Depends(get_db),
                user=Depends(current_user)):
    _check_access(db, company_id, user)
    rows = db.query(IPERCItem.sheet).filter(IPERCItem.company_id == company_id).distinct().all()
    return sorted({r[0] or "BASE" for r in rows}) or ["BASE"]

@router.get("/presets/{activity}")
def get_presets(activity: str):
    """Devuelve todos los procesos y defaults para una actividad normalizada."""
    return get_activity_presets((activity or "").upper())


@router.get("/presets/{activity}/processes")
def get_process_list(activity: str):
    """Devuelve sólo los nombres de proceso (para poblar el <select>)."""
    return list_process_names((activity or "").upper())


@router.get("/presets/{activity}/process")
def get_process_defaults(activity: str, name: str):
    """Devuelve los defaults de un proceso específico."""
    p = find_process((activity or "").upper(), name)
    return p or {}
