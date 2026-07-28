# backend/app/services/iperc_derivatives.py
from typing import List, Dict, Any, Optional, Iterable
from sqlalchemy.orm import Session
from app.models.iperc_item import IPERCItem

# ----------------------------
# Helpers de normalización
# ----------------------------

def classify_np(npv: int) -> str:
    if 24 <= npv <= 40: return "MA"
    if 10 <= npv <= 20: return "A"
    if  6 <= npv <=  8: return "M"
    return "B"  # 2–4

def classify_nr(nrv: int) -> str:
    if nrv >= 600: return "I"
    if nrv >= 150: return "II"
    if nrv >= 40:  return "III"
    return "IV"  # =20

def _as_list(x: Any) -> List[Any]:
    """Convierte entrada en lista. Si llega string 'a, b; c' la divide en ítems limpios."""
    if x is None:
        return []
    if isinstance(x, list):
        return x
    if isinstance(x, (tuple, set)):
        return list(x)
    if isinstance(x, dict):
        for k in ("items", "lista", "values"):
            if k in x and isinstance(x[k], list):
                return x[k]
        return list(x.values())
    # strings CSV/semicolon a lista
    if isinstance(x, str):
        if "," in x or ";" in x:
            parts = [p.strip() for p in x.replace(";", ",").split(",")]
            return [p for p in parts if p]
        return [x.strip()] if x.strip() else []
    # cualquier otro escalar
    return [x]


def _norm(s: Optional[str]) -> str:
    return (s or "").strip()

def _is_high(risk_level: Optional[str], nr_level: Optional[str] = None) -> bool:
    # Alto según nueva metodología: NR I o II
    if nr_level and nr_level.strip().upper() in ("I", "II"):
        return True
    v = (risk_level or "").strip().lower()
    return v in ("alto", "intolerable", "no aceptable", "noaceptable")

# ----------------------------
# Acceso a datos
# ----------------------------

def _row_to_dict(obj: IPERCItem) -> Dict[str, Any]:
    nd = getattr(obj, "nd", None)
    ne = getattr(obj, "ne", None)
    nc = getattr(obj, "nc", None)

    np_val = nr_val = None
    np_level = nr_level = ""
    if nd is not None and ne is not None:
        try:
            np_val = int(nd) * int(ne)
            np_level = classify_np(np_val)
        except Exception:
            pass
    if np_val is not None and nc is not None:
        try:
            nr_val = int(np_val) * int(nc)
            nr_level = classify_nr(nr_val)
        except Exception:
            pass

    def _list2txt(x):
        return ", ".join([str(i) for i in x]) if isinstance(x, list) else (str(x) if x is not None else "")

    d: Dict[str, Any] = {
        "id": obj.id,
        "company_id": obj.company_id,
        "activity": _norm(obj.activity),
        "process": _norm(obj.process),
        "job": _norm(obj.job),
        "task": _norm(obj.task),
        "hazard_group": _norm(obj.hazard_group),
        "hazard": _norm(obj.hazard),
        "event": _norm(obj.event),
        "consequence": _norm(obj.consequence),
        "exposed_persons": _norm(getattr(obj, "exposed_persons", None)),

        "probability": float(getattr(obj, "probability", 0)) if getattr(obj, "probability", None) is not None else None,
        "severity": float(getattr(obj, "severity", 0)) if getattr(obj, "severity", None) is not None else None,
        "risk_level": _norm(getattr(obj, "risk_level", None)),

        "nd": nd, "ne": ne, "nc": nc,
        "np_val": np_val, "np_level": np_level,
        "nr_val": nr_val, "nr_level": nr_level,

        "controls_existing_engineering": _as_list(getattr(obj, "controls_existing_engineering", None)),
        "controls_existing_admin": _as_list(getattr(obj, "controls_existing_admin", None)),
        "controls_existing_epp": _as_list(getattr(obj, "controls_existing_epp", None)),
        "controls_planned_engineering": _as_list(getattr(obj, "controls_planned_engineering", None)),
        "controls_planned_admin": _as_list(getattr(obj, "controls_planned_admin", None)),
        "controls_planned_epp": _as_list(getattr(obj, "controls_planned_epp", None)),
        "requires_work_permit": bool(getattr(obj, "requires_work_permit", False)),
        "needs_health_surveillance": bool(getattr(obj, "needs_health_surveillance", False)),
        "needs_env_monitoring": bool(getattr(obj, "needs_env_monitoring", False)),
        "critical_epp": _as_list(getattr(obj, "critical_epp", None)),
        "evidence_refs": _as_list(getattr(obj, "evidence_refs", None)),
        "review_date": getattr(obj, "review_date", None).isoformat() if getattr(obj, "review_date", None) else None,
        "next_review": getattr(obj, "next_review", None).isoformat() if getattr(obj, "next_review", None) else None,
        "status": _norm(getattr(obj, "status", None)),
    }

    # (opcional) version texto para Excel si tu plantilla usa las llaves *_txt
    d["controls_existing_engineering_txt"] = _list2txt(d["controls_existing_engineering"])
    d["controls_existing_admin_txt"]      = _list2txt(d["controls_existing_admin"])
    d["controls_existing_epp_txt"]        = _list2txt(d["controls_existing_epp"])
    d["controls_planned_engineering_txt"] = _list2txt(d["controls_planned_engineering"])
    d["controls_planned_admin_txt"]       = _list2txt(d["controls_planned_admin"])
    d["controls_planned_epp_txt"]         = _list2txt(d["controls_planned_epp"])

    # 🔹 NUEVO: proposed (la plantilla R usa 'controls_proposed')
    def _uniq_clean(seq):
        seen = set()
        out = []
        for x in (seq or []):
            s = str(x).strip()
            if not s: 
                continue
            if s not in seen:
                seen.add(s)
                out.append(s)
        return out

    _planned_combo = _uniq_clean(
        d["controls_planned_engineering"]
        + d["controls_planned_admin"]
        + d["controls_planned_epp"]
    )
    d["controls_proposed"] = _planned_combo
    d["controls_proposed_txt"] = _list2txt(_planned_combo)

    if not d.get("critical_epp"):
        if d.get("controls_existing_epp"):
            d["critical_epp"] = _uniq_clean(d["controls_existing_epp"])[:1]
        elif _planned_combo:
            d["critical_epp"] = _planned_combo[:1]
    d["critical_epp_txt"] = _list2txt(d.get("critical_epp", []))

    return d


def _fetch_iperc(db: Session, company_id: int, activity: Optional[str] = None) -> List[Dict[str, Any]]:
    """
    Lee iperc_items de BD para la empresa.
    Si 'activity' viene (ya normalizada), filtra además por actividad.
    """
    q = db.query(IPERCItem).filter(IPERCItem.company_id == company_id)
    if activity:
        q = q.filter(IPERCItem.activity == activity)
    rows: Iterable[IPERCItem] = q.all()
    return [_row_to_dict(r) for r in rows]

# ----------------------------
# Derivadores (firmas con db)
# ----------------------------

def derive_training_topics(db: Session, company_id: int, activity: Optional[str] = None) -> List[Dict[str, Any]]:
    rows = _fetch_iperc(db, company_id, activity)
    topics: List[Dict[str, Any]] = []
    for r in rows:
        if _is_high(r.get("risk_level"), r.get("nr_level")):
            topics.append({
                "proceso": r["process"],
                "puesto": r["job"],
                "tema": f"Peligro: {r['hazard']} / Controles críticos",
                "objetivo": "Controlar el riesgo y asegurar cumplimiento de procedimientos",
                "controles_criticos": (r.get("controls_existing_admin") or []) + (r.get("controls_existing_engineering") or []),
                "periodicidad": "Anual"  # puedes ajustar por agente/criticidad si lo deseas
            })
    return topics

def derive_health_surveillance(db: Session, company_id: int, activity: Optional[str] = None) -> List[Dict[str, Any]]:
    rows = _fetch_iperc(db, company_id, activity)
    out: List[Dict[str, Any]] = []
    for r in rows:
        if r.get("needs_health_surveillance"):
            out.append({
                "agente": r["hazard_group"],
                "poblacion": r["job"],
                "examen": "Definir según agente",
                "periodicidad": "Anual"
            })
    return out

def derive_env_monitoring(db: Session, company_id: int, activity: Optional[str] = None) -> List[Dict[str, Any]]:
    rows = _fetch_iperc(db, company_id, activity)
    out: List[Dict[str, Any]] = []
    for r in rows:
        if r.get("needs_env_monitoring"):
            out.append({
                "agente": r["hazard_group"],
                "metodo": "Norma técnica aplicable",
                "puntos": "Definir por proceso",
                "frecuencia": "Anual"
            })
    return out

def derive_work_permits(db: Session, company_id: int, activity: Optional[str] = None) -> List[Dict[str, Any]]:
    rows = _fetch_iperc(db, company_id, activity)
    out: List[Dict[str, Any]] = []
    for r in rows:
        if r.get("requires_work_permit"):
            out.append({
                "tipo_permiso": "Definir (altura/caliente/eléc./confinados/izaje)",
                "proceso": r["process"],
                "tarea": r["task"],
                "controles_previos": r.get("controls_existing_admin") or []
            })
    return out

def derive_critical_epp(db: Session, company_id: int, activity: Optional[str] = None) -> List[Dict[str, Any]]:
    rows = _fetch_iperc(db, company_id, activity)
    out: List[Dict[str, Any]] = []
    for r in rows:
        epp = (r.get("critical_epp") or []) + (r.get("controls_existing_epp") or [])
        if epp:
            out.append({
                "puesto": r["job"],
                "epp": epp,
                "riesgo_controlado": r["hazard"]
            })
    return out

def derive_emergency_scenarios(db: Session, company_id: int, activity: Optional[str] = None) -> List[Dict[str, Any]]:
    rows = _fetch_iperc(db, company_id, activity)
    out: List[Dict[str, Any]] = []
    for r in rows:
        if _is_high(r.get("risk_level"), r.get("nr_level")):
            out.append({
                "escenario": f"Emergencia por {r['hazard']}",
                "detonante": r["event"],
                "recursos": ["Extintores", "Kit derrames", "Primeros auxilios"],
                "brigada": ["Evacuación", "Incendios", "Primeros auxilios"],
                "simulacro": "Anual"
            })
    return out
