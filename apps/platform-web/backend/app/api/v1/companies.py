from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.deps import db as get_db, current_user, admin
from app.models.user import User
from app.models.company import Company
from app.models.subscription import Subscription
from app.models.document import Document
from app.services.admin_audit import log_admin_action


router = APIRouter(prefix="/companies", tags=["companies"])


# ---------- Schemas (EXTERNAL ES, INTERNAL EN) ----------
class CompanyIn(BaseModel):
    ruc: str = Field(..., min_length=10, max_length=13)
    # Campos de entrada en español (alias) -> internos en inglés
    name: str = Field(..., min_length=2, max_length=255, alias="nombre")
    activity: str = Field(..., min_length=3, max_length=80, alias="actividad")
    workers: Optional[int] = Field(None, ge=0, alias="trabajadores")
    risk_level: Optional[Literal["BAJO", "MEDIO", "ALTO"]] = Field(None, alias="riesgo")

    model_config = {"populate_by_name": True
    }


class CompanyOut(BaseModel):
    id: int
    ruc: str
    nombre: str = Field(alias="name")
    actividad: str = Field(alias="activity")
    trabajadores: int | None = Field(default=None, alias="workers")
    riesgo: Literal["BAJO", "MEDIO", "ALTO"] | None = Field(default=None, alias="risk_level")

    # Pydantic v2
    model_config = {
        "from_attributes": True,     # ORM mode
        "populate_by_name": False,   # serializa por alias (ES) cuando FastAPI usa by_alias
    }


# === NUEVO: esquema para actualizaciones parciales ===
class CompanyUpdate(BaseModel):
    ruc: Optional[str] = Field(None, min_length=10, max_length=13, alias="ruc")  # ← NUEVO
    name: Optional[str] = Field(None, min_length=2, max_length=255, alias="nombre")
    activity: Optional[str] = Field(None, min_length=3, max_length=80, alias="actividad")
    workers: Optional[int] = Field(None, ge=0, alias="trabajadores")
    risk_level: Optional[Literal["BAJO", "MEDIO", "ALTO"]] = Field(None, alias="riesgo")

    model_config = {"populate_by_name": True}


# ---------- Helpers ----------
def _get_subscription(session: Session, user_id: int) -> Subscription | None:
    return session.query(Subscription).filter(Subscription.user_id == user_id).first()


def _count_user_companies(session: Session, user_id: int) -> int:
    return session.query(Company).filter(Company.owner_id == user_id).count()


def _ensure_quota(session: Session, user: User):
    # Admin no tiene límite
    if user.role.upper() == "ADMIN":
        return

    sub = _get_subscription(session, user.id)
    if not sub:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="No tienes una suscripción activa o trial disponible."
        )

    used = _count_user_companies(session, user.id)
    if used >= (sub.companies_quota or 0):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Cupo agotado ({used}/{sub.companies_quota}). Amplía tu plan para más empresas."
        )


def _ensure_owner_or_admin(session: Session, user: User, company_id: int, allow_deleted: bool = False) -> Company:
    obj = session.get(Company, company_id)
    if not obj:
        raise HTTPException(status_code=404, detail="Empresa no encontrada")

    if obj.is_deleted and not allow_deleted:
        raise HTTPException(status_code=404, detail="Empresa no encontrada")

    if obj.owner_id == user.id or user.role.upper() == "ADMIN":
        return obj

    raise HTTPException(status_code=403, detail="No autorizado")

def _aware_utc(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


# ---------- Routes ----------
@router.post("", response_model=CompanyOut, response_model_by_alias=True, status_code=201)
def create_company(
    payload: CompanyIn,
    session: Session = Depends(get_db),
    user: User = Depends(current_user),
):

    _ensure_quota(session, user)  # admin queda exento adentro

    # No duplicar RUC para el mismo owner
    exists = (
        session.query(Company)
        .filter(Company.owner_id == user.id, Company.ruc == payload.ruc)
        .first()
    )
    if exists:
        raise HTTPException(status_code=400, detail="Ya existe una empresa con ese RUC")

    obj = Company(
        owner_id=user.id,
        ruc=payload.ruc,
        name=payload.name,
        activity=payload.activity,
        workers=payload.workers if payload.workers is not None else 0,
        risk_level=payload.risk_level,
    )


    try:
        session.add(obj)
        session.commit()
        session.refresh(obj)
    except IntegrityError as e:
        session.rollback()
        # Postgres expone el nombre de la restricción; además dejamos un fallback por texto
        constraint = getattr(getattr(e.orig, "diag", None), "constraint_name", None)
        msg = str(e.orig).lower()
        if (
            constraint == "ix_companies_ruc"
            or "ix_companies_ruc" in msg
            or ("unique" in msg and "ruc" in msg)
        ):
            raise HTTPException(status_code=409, detail="RUC ya registrado")
        raise  # otras integridades, propagar

    return obj


@router.get("", response_model=list[CompanyOut], response_model_by_alias=True)
def list_companies(session: Session = Depends(get_db), user: User = Depends(current_user)):
    if user.role.upper() == "ADMIN":
        rows = (
            session.query(Company)
            .filter(Company.is_deleted.is_(False))
            .order_by(Company.id.desc())
            .all()
        )
    else:
        rows = (
            session.query(Company)
            .filter(Company.owner_id == user.id, Company.is_deleted.is_(False))
            .order_by(Company.id.desc())
            .all()
        )
    return rows


# NUEVO: GET /companies/{company_id}
@router.get("/{company_id}", response_model=CompanyOut, response_model_by_alias=True)
def get_company(
    company_id: int,
    session: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    # Reutilizamos el helper existente (no cambiamos lógica)
    obj = _ensure_owner_or_admin(session, user, company_id)
    return obj


@router.get("/{company_id}/known-fields")
def get_known_fields(
    company_id: int,
    session: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    # import local para evitar ciclos y mantener el módulo limpio
    from app.services.known_fields import collect_known_fields, collect_field_provenance

    data = collect_known_fields(session, company_id)
    prov = collect_field_provenance(session, company_id)
    return {"company_id": company_id, "known": data, "provenance": prov}


@router.put("/{company_id}", response_model=CompanyOut, response_model_by_alias=True)
def update_company(
    company_id: int,
    payload: CompanyUpdate,
    session: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    obj = _ensure_owner_or_admin(session, user, company_id)

    # Solo aplica los campos enviados
    updates = payload.model_dump(exclude_unset=True)

    # Validar RUC si viene en el payload
    if "ruc" in updates and updates["ruc"] is not None:
        if user.role.upper() != "ADMIN":
            raise HTTPException(status_code=403, detail="Solo ADMIN puede modificar el RUC")
        new_ruc = updates["ruc"].strip()
        if new_ruc and new_ruc != obj.ruc:
            # Evita colisión con otro registro (índice único)
            exists = session.query(Company).filter(Company.ruc == new_ruc).first()
            if exists:
                raise HTTPException(status_code=409, detail="RUC ya registrado")

    # Aplicar el resto de campos
    for field, value in updates.items():
        setattr(obj, field, value)

    session.commit()
    session.refresh(obj)
    return obj


@router.delete("/{company_id}")
def delete_company(company_id: int, session: Session = Depends(get_db), user: User = Depends(current_user)):
    obj = _ensure_owner_or_admin(session, user, company_id, allow_deleted=True)

    if obj.is_deleted:
        raise HTTPException(status_code=409, detail="La empresa ya está archivada")

    obj.is_deleted = True
    obj.deleted_at = datetime.utcnow()

    log_admin_action(
        session,
        user,
        action="COMPANY_ARCHIVE",
        entity_type="COMPANY",
        entity_id=obj.id,
        target_user_id=obj.owner_id,
        company_id=obj.id,
        description=f"Archivó la empresa {obj.name}",
        payload={
            "company_name": obj.name,
            "company_ruc": obj.ruc,
            "owner_user_id": obj.owner_id,
        },
    )

    session.commit()
    return {"ok": True, "archived": True, "company_id": obj.id}

@router.patch("/{company_id}/restore", response_model=dict)
def restore_company(
    company_id: int,
    session: Session = Depends(get_db),
    user: User = Depends(admin),
):
    obj = _ensure_owner_or_admin(session, user, company_id, allow_deleted=True)

    if not obj.is_deleted:
        raise HTTPException(status_code=409, detail="La empresa no está archivada")

    owner = session.get(User, obj.owner_id)
    if owner and owner.is_deleted:
        raise HTTPException(
            status_code=409,
            detail="No puedes restaurar esta empresa mientras su usuario propietario esté archivado",
        )

    obj.is_deleted = False
    obj.deleted_at = None

    log_admin_action(
        session,
        user,
        action="COMPANY_RESTORE",
        entity_type="COMPANY",
        entity_id=obj.id,
        target_user_id=obj.owner_id,
        company_id=obj.id,
        description=f"Restauró la empresa {obj.name}",
        payload={
            "company_name": obj.name,
            "company_ruc": obj.ruc,
            "owner_user_id": obj.owner_id,
        },
    )

    session.commit()
    return {"ok": True, "restored": True, "company_id": obj.id}

@router.delete("/{company_id}/hard", status_code=204)
def hard_delete_company(
    company_id: int,
    session: Session = Depends(get_db),
    user: User = Depends(admin),
):
    obj = _ensure_owner_or_admin(session, user, company_id, allow_deleted=True)

    if not obj.is_deleted:
        raise HTTPException(
            status_code=409,
            detail="Primero debes archivar la empresa antes de eliminarla definitivamente",
        )

    log_admin_action(
        session,
        user,
        action="COMPANY_HARD_DELETE",
        entity_type="COMPANY",
        entity_id=obj.id,
        target_user_id=obj.owner_id,
        company_id=obj.id,
        description=f"Eliminó definitivamente la empresa {obj.name}",
        payload={
            "company_name": obj.name,
            "company_ruc": obj.ruc,
            "owner_user_id": obj.owner_id,
        },
    )

    session.delete(obj)
    session.commit()
    return

@router.get("/{company_id}/requirements")
def get_company_requirements(
    company_id: int,
    session: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    obj = _ensure_owner_or_admin(session, user, company_id)
    from app.services.sst_requirements import build_requirements

    # --- 1) matriz base como hoy ---
    req = build_requirements(obj.activity, obj.workers or 0, obj.risk_level or "MEDIO")

    # --- 2) documentos existentes de la empresa ---
    docs: list[Document] = (
        session.query(Document)
        .filter(Document.company_id == obj.id)
        .all()
    )

    # --- 3) helpers de periodicidad ---
    PERIODICITY_MONTHS = {
        "ANUAL": 12,
        "BIENAL": 24,
        "SEMESTRAL": 6,
        "TRIMESTRAL": 3,
        "MENSUAL": 1,
    }
    ALWAYS_ACTIVE_CODES = {"INV-AT-01"}  # investigación de accidentes/incidentes
    ALWAYS_ACTIVE_KEYWORDS = ("ACCIDENTE", "INCIDENTE", "INVESTIGACIÓN")

    def _period_months(txt: str | None) -> int | None:
        s = (txt or "").strip().upper()
        for k, v in PERIODICITY_MONTHS.items():
            if k in s:
                return v
        # "SEGÚN CAMBIOS", "PERMANENTE", vacío, etc. => sin vencimiento programado
        return None

    def _add_months(dt: datetime, months: int) -> datetime:
        # suma robusta de meses sin dependencias externas
        y = dt.year + (dt.month - 1 + months) // 12
        m = (dt.month - 1 + months) % 12 + 1
        # ajustar el día válido del nuevo mes
        import calendar
        last_day = calendar.monthrange(y, m)[1]
        d = min(dt.day, last_day)
        return dt.replace(year=y, month=m, day=d)

    now = datetime.now(timezone.utc)

    # --- 4) enriquecer cada item con exists/último/next_due/can_generate ---
    for it in req["items"]:
        code = (it.get("code") or "").strip().upper()
        name = (it.get("name") or "").strip().upper()
        periodicity = it.get("periodicity") or ""

        # existe si hay un doc cuyo kind sea code o cuyo title contenga el code
        matches = []
        for d in docs:
            if code == ((d.kind or "").strip().upper()) or (code and code in ((d.title or "").strip().upper())):
                matches.append(_aware_utc(d.created_at))

        last_dt = max(matches) if matches else None
        it["exists"] = bool(matches)

        # casos siempre activos (eventuales, investigación, etc.)
        always_active = (
            code in ALWAYS_ACTIVE_CODES
            or any(kw in name for kw in ALWAYS_ACTIVE_KEYWORDS)
        )

        months = _period_months(periodicity)
        can_generate = True
        next_due_date = None
        disabled_reason = None

        if always_active:
            # Siempre se puede generar, no hay próximo "vencimiento" programado
            can_generate = True
        else:
            if last_dt is None:
                can_generate = True  # nunca se ha generado
            else:
                if months is None:
                    # sin vencimiento programado (p. ej. "según cambios"/"permanente"):
                    can_generate = False
                    disabled_reason = "Cumplido."
                else:
                    # last_dt ya viene aware; _add_months preserva tz con .replace()
                    due = _add_months(last_dt, months)
                    due = _aware_utc(due)
                    next_due_date = due.isoformat()
                    can_generate = (now >= due)
                    if not can_generate:
                        disabled_reason = f"Cumplido. Próxima: {due.date().isoformat()}"

        it["last_document_at"] = last_dt.isoformat() if last_dt else None
        it["next_due_date"] = next_due_date
        it["can_generate"] = can_generate
        it["disabled_reason"] = disabled_reason

    return req

@router.get("/{company_id}/alerts")
def get_company_alerts(
    company_id: int,
    within_days: int = 30,
    session: Session = Depends(get_db),
    user: User = Depends(current_user),
):

    # Reutiliza la lógica actual pasando session y user
    req = get_company_requirements(company_id=company_id, session=session, user=user)
    now = datetime.utcnow().date()
    threshold = now + timedelta(days=within_days)
    alerts = []

    for it in req["items"]:
        due = it.get("next_due_date")
        if not due:
            continue
        try:
            d = datetime.fromisoformat(str(due)).date()
        except Exception:
            continue
        if now <= d <= threshold:
            alerts.append({
                "code": it["code"],
                "title": it.get("name") or it.get("title") or it["code"],
                "next_due_date": due,
                "legal": it.get("legal"),
                "periodicity": it.get("periodicity"),
            })

    return {"company_id": company_id, "within_days": within_days, "alerts": alerts}
