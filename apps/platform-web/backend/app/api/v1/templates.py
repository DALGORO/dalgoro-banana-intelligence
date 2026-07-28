from pathlib import Path
import json
from fastapi import APIRouter, Depends, Query, Body
from sqlalchemy.orm import Session
from typing import List, Optional
from app.api.deps import admin
from app.db.session import get_db
from app.models.document_template import DocumentTemplate
from app.services.sst_rules import normalize_activity
from app.services.sst_requirements import build_requirements  # al inicio del archivo

router = APIRouter(prefix="/templates", tags=["templates"])

BASE_DIR = Path("app/static/templates")

def _ci_match_dir(base: Path, name: str) -> Path | None:
    target = name.strip()
    if (base / target).exists():
        return base / target
    # buscar carpeta ignorando mayúsculas/minúsculas
    for p in base.iterdir():
        if p.is_dir() and p.name.lower() == target.lower():
            return p
    return None

def _sidecar_fields(activity: str, code: str) -> list:
    act_dir = _ci_match_dir(BASE_DIR, activity)  # actividad normalizada
    if not act_dir:
        return []
    # candidatos de archivo
    patt = [
        f"{code}.json",
        f"{code.upper()}.json",
        f"{code.lower()}.json",
        f"{code}-V" + "[0-9]"*3 + ".json",  # soporta -V001, -V123, etc.
    ]

    candidates = []
    for p in patt:
        if "[" in p:
            candidates.extend(act_dir.glob(p.replace("[0-9]"*3, "[0-9][0-9][0-9]")))
        else:
            candidates.append(act_dir / p)

    for c in candidates:
        if c.exists():
            try:
                with open(c, "r", encoding="utf-8-sig") as f:
                    data = json.load(f)
                if isinstance(data, dict) and isinstance(data.get("fields"), list):
                    return data["fields"]
                if isinstance(data, list):
                    return data
            except Exception:
                # loguea y sigue probando con otros candidatos
                pass
    return []


@router.get("", response_model=list[dict])
def list_templates(
    db: Session = Depends(get_db),
    activity: Optional[str] = Query(None),
    code: Optional[str] = Query(None),
):
    q = db.query(DocumentTemplate)
    if activity:
        q = q.filter(DocumentTemplate.activity == normalize_activity(activity))
    if code:
        q = q.filter(DocumentTemplate.code == code)

    rows = q.order_by(DocumentTemplate.created_at.desc()).all()

    result = []
    for r in rows:
        fields = r.fields_json or _sidecar_fields(r.activity, r.code)
        # intentar derivar base legal si viene filtrado por actividad
        legal_txt = None
        try:
            if activity:
                # Armamos una matriz mínima para “pescar” el item por código:
                req = build_requirements(activity, trabajadores=10, riesgo="MEDIO")
                for it in req["items"]:
                    if it.get("code") == r.code:
                        legal_txt = it.get("legal")
                        break
        except Exception:
            legal_txt = None

        result.append({
            "id": r.id,
            "code": r.code,
            "activity": r.activity,
            "title": r.title,
            "version": r.version,
            "fields": fields,
            "file_path": r.file_path,
            "created_at": r.created_at,
            "legal": legal_txt,  # ← NUEVO
        })
    return result



@router.post("/sync", dependencies=[Depends(admin)])
def sync_templates(
    db: Session = Depends(get_db),
    base_dir: Optional[str] = Body(default=None),
):
    """
    Recorre app/static/templates/<ACTIVIDAD>/*.docx y registra/actualiza
    DocumentTemplate. Si base_dir viene en el body, lo usa.
    """
    # cálculo por defecto: backend/app/static/templates
    here = Path(__file__).resolve()
    default_base = here.parents[3] / "app" / "static" / "templates"  # sube hasta backend
    root = Path(base_dir) if base_dir else default_base

    if not root.exists():
        return {"updated": 0, "detail": f"Carpeta no existe: {root}"}

    updated = 0
    for act_dir in root.iterdir():
        if not act_dir.is_dir():
            continue
        activity = normalize_activity(act_dir.name)
        for tpl in act_dir.glob("*.docx"):
            code = tpl.stem.upper()
            # sidecar opcional
            sidecar = tpl.with_suffix(".json")
            title, version, fields = code, 1, []
            if sidecar.exists():
                try:
                    data = json.loads(sidecar.read_text(encoding="utf-8"))
                    title = str(data.get("title", title))
                    version = int(data.get("version", version))
                    fields = list(data.get("fields", fields))
                except Exception:
                    pass

            rel_path = tpl.relative_to(root).as_posix()
            row = (
                db.query(DocumentTemplate)
                .filter(DocumentTemplate.activity == activity, DocumentTemplate.code == code)
                .order_by(DocumentTemplate.created_at.desc())
                .first()
            )
            if row is None:
                row = DocumentTemplate(
                    activity=activity,
                    code=code,
                    title=title,
                    version=version,
                    fields_json=fields,
                    file_path=rel_path,
                )
                db.add(row)
            else:
                row.file_path = rel_path
                if version > int(row.version or 0):
                    row.version = version
                if fields:
                    row.fields_json = fields

            updated += 1

    db.commit()
    return {"updated": updated, "base_dir": str(root)}
