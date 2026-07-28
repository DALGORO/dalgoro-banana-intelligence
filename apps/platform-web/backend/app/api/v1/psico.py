from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from typing import List, Any, Dict
from sqlalchemy.orm import Session
from sqlalchemy import text, bindparam
from sqlalchemy.dialects.postgresql import JSONB
from app.db.session import get_db

router = APIRouter(prefix="/psico", tags=["psico"])

class PsicoPackIn(BaseModel):
    worker_index: int
    fields: Dict[str, Any]
    respuestas: List[Dict[str, Any]]

@router.get("/company/{company_id}")
def list_psico(company_id: int, db: Session = Depends(get_db)):
    rows = db.execute(
        text("""
            SELECT worker_index,
                   fields_json     AS fields,
                   respuestas_json AS respuestas,
                   updated_at
            FROM psico_responses
            WHERE company_id = :cid
            ORDER BY worker_index
        """),
        {"cid": company_id}
    ).mappings().all()

    # Si quieres “expected” puedes leerlo con la columna que sí tengas:
    # expected = db.execute(text("SELECT COALESCE(workers, 0) FROM companies WHERE id = :id"), {"id": company_id}).scalar()
    expected = None
    return {"expected": expected, "items": rows or []}

@router.post("/company/{company_id}")
def save_psico(company_id: int, pack: PsicoPackIn, db: Session = Depends(get_db)):
    if not pack.respuestas or len(pack.respuestas) != 58:
        raise HTTPException(400, "Se requieren 58 respuestas")
    if any(int(r.get("puntuacion", 0)) not in (1, 2, 3, 4) for r in pack.respuestas):
        raise HTTPException(400, "Puntuación fuera de rango")

    stmt = text("""
        INSERT INTO psico_responses
            (company_id, worker_index, fields_json, respuestas_json, updated_at)
        VALUES
            (:company_id, :worker_index, :fields, :respuestas, now())
        ON CONFLICT (company_id, worker_index) DO UPDATE
            SET fields_json     = EXCLUDED.fields_json,
                respuestas_json = EXCLUDED.respuestas_json,
                updated_at      = now()
    """).bindparams(
        bindparam("fields", type_=JSONB),
        bindparam("respuestas", type_=JSONB),
    )

    db.execute(stmt, {
        "company_id": company_id,
        "worker_index": pack.worker_index,
        "fields": pack.fields,               # dict -> JSONB (lo castea SQLAlchemy)
        "respuestas": pack.respuestas,       # list -> JSONB
    })
    db.commit()
    return {"ok": True}