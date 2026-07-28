from typing import Dict, Any
from sqlalchemy.orm import Session
from app.models.company import Company
from app.models.document import Document
from app.services.sst_rules import classify_by_workers

CANONICAL_KEYS = {
    "razon_social", "ruc", "actividad", "riesgo", "trabajadores",
    "representante_legal", "identificacion_rl",
    "direccion", "ciudad", "provincia", "telefono", "correo",
    # agrega las que se repiten mucho (ej. “sucursal”, “ubicacion_geografica”, etc.)
}

def collect_known_fields(db: Session, company_id: int) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    # 1) Company
    company = db.query(Company).filter(Company.id == company_id).first()
    if company:
        def add_if(val, key):
            v = getattr(company, val, None)
            if v not in (None, "", " "):
                out[key] = v
        add_if("name", "razon_social")
        add_if("ruc", "ruc")
        add_if("activity", "actividad")
        add_if("risk_level", "riesgo")
        add_if("workers", "trabajadores")
        add_if("legal_representative", "representante_legal")
        add_if("legal_rep_id", "identificacion_rl")
        add_if("address", "direccion")
        add_if("city", "ciudad")
        add_if("province", "provincia")
        add_if("phone", "telefono")
        add_if("email", "correo")
        try:
            clasif = classify_by_workers(getattr(company, "workers", 0))
            if clasif:
                out["tamano_empresa"] = clasif  # valores: MICRO, PEQUEÑA, MEDIANA, GRANDE
        except Exception:
            pass

    # 2) Últimos documentos → meta.form
    docs = (
        db.query(Document)
        .filter(Document.company_id == company_id)
        .order_by(Document.created_at.desc())
        .limit(200)  # cota razonable
        .all()
    )
    for d in docs:
        try:
            form = (d.meta or {}).get("form") or {}
            if isinstance(form, dict):
                for k, v in form.items():
                    if v not in (None, "", " "):
                        out[k] = v
        except Exception:
            pass

    # 3) depurar sólo claves canónicas (opcional, puedes omitir si quieres todo)
    # out = {k: v for k, v in out.items() if k in CANONICAL_KEYS}

    # 4) Derivación inteligente desde IPERC (si existe) para pre-llenado
    try:
        from app.services.iperc_derivatives import _fetch_iperc
        iperc_rows = _fetch_iperc(db, company_id)
        if iperc_rows:
            # A) EPP Químico (para AGRO-PLAG-01)
            chem_rows = [r for r in iperc_rows if str(r.get("hazard_group","")).strip().upper().startswith(("QUIM", "QUÍM"))]
            epp_set = set()
            for r in chem_rows:
                # Prioridad: crítico > existente > planificado
                src = (r.get("critical_epp") or []) + (r.get("controls_existing_epp") or []) + (r.get("controls_planned_epp") or [])
                for e in src:
                    if e and isinstance(e, str):
                        epp_set.add(e.strip())
            if epp_set:
                # Solo si no tenemos ya un valor (aunque known fields suele sobrescribir, aquí es fallback inteligente)
                if "epp_obligatorio" not in out:
                    out["epp_obligatorio"] = "\n".join(sorted(list(epp_set)))

            # B) Vigilancia de la salud (Genérico)
            health_needs = [r for r in iperc_rows if r.get("needs_health_surveillance")]
            if health_needs:
                items = []
                for r in health_needs:
                    agente = r.get("hazard_group") or "Riesgo específico"
                    puesto = r.get("job") or "Puesto"
                    items.append(f"Examen para {agente} en puesto {puesto}")
                if items and "vigilancia_items" not in out:
                    out["vigilancia_items"] = "\n".join(items)

            # C) Temas de capacitación (Genérico, basado en riesgos altos)
            high_risk = [r for r in iperc_rows if str(r.get("risk_level","")).upper() in ("ALTO", "INTOLERABLE", "CRITICO")]
            if high_risk:
                temas = set()
                for r in high_risk:
                    temas.add(f"Prevención de riesgos: {r.get('hazard')} ({r.get('process')})")
                if temas and "capacitacion_temas" not in out:
                    out["capacitacion_temas"] = "\n".join(sorted(list(temas)))

    except Exception:
        pass

    return out


def collect_field_provenance(db: Session, company_id: int) -> Dict[str, Dict[str, Any]]:
    """
    Retorna la procedencia del ÚLTIMO valor conocido por campo.
    Formato:
    {
      "<campo>": {
        "value": <valor>,
        "source_code": "<código de documento, p.ej. RHS-01>",
        "source_title": "<título legible>",
        "document_id": <id>,
        "updated_at": "<ISO8601>"
      }, ...
    }
    """
    prov: Dict[str, Dict[str, Any]] = {}

    docs = (
        db.query(Document)
        .filter(Document.company_id == company_id)
        .order_by(Document.created_at.desc())
        .limit(200)
        .all()
    )
    for d in docs:
        form = (d.meta or {}).get("form") or {}
        if not isinstance(form, dict):
            continue
        for k, v in form.items():
            if v in (None, "", " "):
                continue
            if k not in prov:  # al ir en orden descendente, la primera vez es el más reciente
                prov[k] = {
                    "value": v,
                    "source_code": (d.kind or "").strip().upper(),
                    "source_title": d.title,
                    "document_id": d.id,
                    "updated_at": d.created_at.isoformat(),
                }
    return prov
