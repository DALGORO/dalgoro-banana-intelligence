from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.deps import db as get_db, current_user
from app.models.company import Company
from app.models.user import User
from app.services.incident_assistant import (
    answer_company_question,
    create_incident_case,
    create_worker_epp_delivery,
    create_worker_profile,
    generate_incident_procedure_pdf,
    get_incident_module_state,
    update_incident_case,
    upsert_incident_procedure,
)

router = APIRouter(prefix="/companies", tags=["companies"])


class IncidentAssistantQueryIn(BaseModel):
    question: str = Field(..., min_length=3, max_length=4000)


class IncidentAssistantQueryOut(BaseModel):
    answer: str
    blocked: bool = False
    sources: list[str] = Field(default_factory=list)
    system_state: dict[str, Any] = Field(default_factory=dict)


class IncidentProcedureIn(BaseModel):
    approved_by: str = ""
    approved_role: str = ""
    approved_at: str = ""
    notes: str = ""


class WorkerProfileIn(BaseModel):
    full_name: str = Field(..., min_length=3, max_length=200)
    id_number: str = ""
    job: str = ""
    start_date: str = ""
    status: str = "ACTIVO"
    notes: str = ""


class WorkerEPPDeliveryIn(BaseModel):
    worker_document_id: int
    delivery_date: str = ""
    items_text: str = ""
    return_notes: str = ""
    observations: str = ""
    worker_receipt_name: str = ""
    employer_receipt_name: str = ""


class IncidentCaseIn(BaseModel):
    event_type: str = "INCIDENTE"
    status: str = "ABIERTO"
    happened_at: str = ""
    worker_document_id: int = 0
    place: str = ""
    description: str = ""
    consequences: str = ""
    witnesses: str = ""
    causes: str = ""
    immediate_actions: str = ""
    corrective_actions: str = ""
    preventive_actions: str = ""
    reported_to_authority: bool = False


def _ensure_company_access(session: Session, company_id: int, user: User) -> Company:
    company = session.get(Company, company_id)
    if not company:
        raise HTTPException(status_code=404, detail="Empresa no encontrada")

    if getattr(user, "role", "").upper() == "ADMIN" or company.owner_id == user.id:
        return company

    raise HTTPException(status_code=403, detail="No autorizado")


@router.get("/{company_id}/incident-assistant/state")
def get_incident_assistant_state(
    company_id: int,
    session: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    company = _ensure_company_access(session, company_id, user)
    return get_incident_module_state(session, company)


@router.post(
    "/{company_id}/incident-assistant/query",
    response_model=IncidentAssistantQueryOut,
)
def query_incident_assistant(
    company_id: int,
    payload: IncidentAssistantQueryIn,
    session: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    company = _ensure_company_access(session, company_id, user)
    result = answer_company_question(
        session=session,
        company=company,
        question=payload.question,
    )
    return IncidentAssistantQueryOut(**result)


@router.post("/{company_id}/incident-assistant/procedure")
def save_incident_procedure(
    company_id: int,
    payload: IncidentProcedureIn,
    session: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    company = _ensure_company_access(session, company_id, user)
    return upsert_incident_procedure(session, company, payload.model_dump())

@router.post("/{company_id}/incident-assistant/procedure/pdf")
def export_incident_procedure_pdf(
    company_id: int,
    session: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    company = _ensure_company_access(session, company_id, user)

    try:
        return generate_incident_procedure_pdf(
            session=session,
            company=company,
            user_id=user.id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    
@router.post("/{company_id}/incident-assistant/workers")
def save_worker_profile(
    company_id: int,
    payload: WorkerProfileIn,
    session: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    company = _ensure_company_access(session, company_id, user)
    try:
        return create_worker_profile(session, company, payload.model_dump())
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.post("/{company_id}/incident-assistant/epp-deliveries")
def save_worker_epp_delivery(
    company_id: int,
    payload: WorkerEPPDeliveryIn,
    session: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    company = _ensure_company_access(session, company_id, user)
    try:
        return create_worker_epp_delivery(session, company, payload.model_dump())
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.post("/{company_id}/incident-assistant/cases")
def save_incident_case(
    company_id: int,
    payload: IncidentCaseIn,
    session: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    company = _ensure_company_access(session, company_id, user)
    try:
        return create_incident_case(session, company, payload.model_dump())
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.patch("/{company_id}/incident-assistant/cases/{document_id}")
def patch_incident_case(
    company_id: int,
    document_id: int,
    payload: IncidentCaseIn,
    session: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    company = _ensure_company_access(session, company_id, user)

    try:
        return update_incident_case(session, company, document_id, payload.model_dump())
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))