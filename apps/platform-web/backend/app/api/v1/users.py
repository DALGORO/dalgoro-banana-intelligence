from __future__ import annotations

from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from app.api.deps import admin
from app.core.security import get_password_hash
from app.db.session import get_db
from app.models.company import Company
from app.models.subscription import Subscription
from app.models.user import User

from app.models.admin_audit_log import AdminAuditLog
from app.services.admin_audit import log_admin_action, serialize_admin_audit_log

router = APIRouter(prefix="/users", tags=["users"])

MAX_BCRYPT_BYTES = 72


class UserCreateIn(BaseModel):
    full_name: str | None = Field(default=None, max_length=255)
    email: EmailStr
    id_number: str | None = Field(default=None, max_length=20)
    phone: str | None = Field(default=None, max_length=32)
    role: str = Field(default="SUBSCRIBER", max_length=64)
    is_active: bool = True
    password: str = Field(..., min_length=8)


class UserUpdateIn(BaseModel):
    full_name: str | None = Field(default=None, max_length=255)
    email: EmailStr | None = None
    id_number: str | None = Field(default=None, max_length=20)
    phone: str | None = Field(default=None, max_length=32)
    role: str | None = Field(default=None, max_length=64)
    is_active: bool | None = None


class PasswordResetIn(BaseModel):
    password: str = Field(..., min_length=8)

class SubscriptionAdminUpdateIn(BaseModel):
    plan: str | None = Field(default=None, max_length=32)
    status: str | None = Field(default=None, max_length=32)
    companies_quota: int | None = Field(default=None, ge=0)
    free_trial_until: str | None = None
    current_period_end: str | None = None
    last_payment_at: str | None = None
    provider: str | None = Field(default=None, max_length=32)
    customer_ref: str | None = Field(default=None, max_length=128)

def _too_long_for_bcrypt(password: str) -> bool:
    return len(password.encode("utf-8")) > MAX_BCRYPT_BYTES


def _clean_text(value: str | None) -> str | None:
    text = (value or "").strip()
    return text or None


def _normalize_role(value: str | None) -> str:
    return (value or "SUBSCRIBER").strip().upper()


def _count_admins(db: Session) -> int:
    return (
        db.query(User)
        .filter(func.upper(User.role) == "ADMIN")
        .count()
    )


def _count_active_admins(db: Session) -> int:
    return (
        db.query(User)
        .filter(func.upper(User.role) == "ADMIN", User.is_active.is_(True))
        .count()
    )


def _ensure_email_available(db: Session, email: str, exclude_user_id: int | None = None) -> None:
    q = db.query(User).filter(func.lower(User.email) == email.strip().lower())
    if exclude_user_id is not None:
        q = q.filter(User.id != exclude_user_id)

    if q.first():
        raise HTTPException(status_code=409, detail="Email ya registrado")


def _ensure_id_number_available(db: Session, id_number: str | None, exclude_user_id: int | None = None) -> None:
    clean_id = _clean_text(id_number)
    if not clean_id:
        return

    q = db.query(User).filter(User.id_number == clean_id)
    if exclude_user_id is not None:
        q = q.filter(User.id != exclude_user_id)

    if q.first():
        raise HTTPException(status_code=409, detail="La cédula ya está registrada en otro usuario")


def _serialize_subscription(sub: Subscription | None) -> dict | None:
    if not sub:
        return None

    return {
        "id": sub.id,
        "plan": sub.plan,
        "status": sub.status,
        "companies_quota": sub.companies_quota,
        "free_trial_until": sub.free_trial_until.isoformat() if sub.free_trial_until else None,
        "current_period_end": sub.current_period_end.isoformat() if sub.current_period_end else None,
        "last_payment_at": sub.last_payment_at.isoformat() if sub.last_payment_at else None,
        "provider": sub.provider,
        "customer_ref": sub.customer_ref,
    }

def _parse_optional_datetime(value: str | None, field_name: str) -> datetime | None:
    text = (value or "").strip()
    if not text:
        return None

    try:
        return datetime.fromisoformat(text)
    except Exception:
        raise HTTPException(
            status_code=400,
            detail=f"El campo '{field_name}' debe estar en formato ISO válido, por ejemplo 2026-04-12T15:30",
        )


def _get_or_create_subscription_for_admin(db: Session, user_id: int) -> Subscription:
    sub = db.query(Subscription).filter(Subscription.user_id == user_id).first()
    if sub:
        return sub

    sub = Subscription.new_trial(user_id=user_id)
    db.add(sub)
    db.flush()
    return sub

def _serialize_company(c: Company) -> dict:
    return {
        "id": c.id,
        "ruc": c.ruc,
        "name": c.name,
        "activity": c.activity,
        "workers": c.workers,
        "risk_level": c.risk_level,
        "is_deleted": c.is_deleted,
        "deleted_at": c.deleted_at.isoformat() if c.deleted_at else None,
        "created_at": c.created_at.isoformat() if c.created_at else None,
        "updated_at": c.updated_at.isoformat() if c.updated_at else None,
    }


def _serialize_user(
    user: User,
    companies_count: int = 0,
    subscription: Subscription | None = None,
) -> dict:
    return {
        "id": user.id,
        "full_name": user.full_name,
        "email": user.email,
        "id_number": user.id_number,
        "phone": user.phone,
        "is_active": user.is_active,
        "role": user.role,
        "is_deleted": user.is_deleted,
        "deleted_at": user.deleted_at.isoformat() if user.deleted_at else None,
        "created_at": user.created_at.isoformat() if user.created_at else None,
        "updated_at": user.updated_at.isoformat() if getattr(user, "updated_at", None) else None,
        "companies_count": companies_count,
        "subscription": _serialize_subscription(subscription),
    }

@router.post("", response_model=dict)
def create_user(
    payload: UserCreateIn,
    db: Session = Depends(get_db),
    acting_admin: User = Depends(admin),
):
    email = payload.email.strip().lower()
    role = _normalize_role(payload.role)
    full_name = _clean_text(payload.full_name)
    id_number = _clean_text(payload.id_number)
    phone = _clean_text(payload.phone)

    _ensure_email_available(db, email)
    _ensure_id_number_available(db, id_number)

    if _too_long_for_bcrypt(payload.password):
        raise HTTPException(
            status_code=400,
            detail=f"La contraseña supera el límite permitido de {MAX_BCRYPT_BYTES} bytes.",
        )

    user = User(
        full_name=full_name,
        email=email,
        id_number=id_number,
        phone=phone,
        role=role,
        is_active=payload.is_active,
        hashed_password=get_password_hash(payload.password),
    )

    db.add(user)
    db.flush()

    subscription = None
    if role != "ADMIN":
        subscription = Subscription.new_trial(user.id)
        db.add(subscription)

    log_admin_action(
        db,
        acting_admin,
        action="USER_CREATE",
        entity_type="USER",
        entity_id=user.id,
        target_user_id=user.id,
        description=f"Creó el usuario {user.email}",
        payload={
            "email": user.email,
            "role": user.role,
            "is_active": user.is_active,
            "full_name": user.full_name,
            "id_number": user.id_number,
        },
    )

    db.commit()
    db.refresh(user)
    if subscription is not None:
        db.refresh(subscription)

    return _serialize_user(user, companies_count=0, subscription=subscription)


@router.get("", response_model=list[dict])
def list_users(
    q: str | None = Query(default=None),
    role: str | None = Query(default=None),
    is_active: bool | None = Query(default=None),
    archived_mode: str = Query(default="active", pattern="^(active|archived|all)$"),
    db: Session = Depends(get_db),
    acting_admin: User = Depends(admin),
):
    query = db.query(User)
    
    query = _apply_user_archive_filter(query, archived_mode)

    search = (q or "").strip()
    if search:
        like = f"%{search}%"
        query = query.filter(
            or_(
                User.email.ilike(like),
                User.full_name.ilike(like),
                User.id_number.ilike(like),
            )
        )

    if role:
        query = query.filter(func.upper(User.role) == _normalize_role(role))

    if is_active is not None:
        query = query.filter(User.is_active.is_(is_active))

    users = query.order_by(User.created_at.desc()).all()
    if not users:
        return []

    user_ids = [u.id for u in users]

    company_rows = (
        db.query(Company.owner_id, func.count(Company.id))
        .filter(Company.owner_id.in_(user_ids))
        .group_by(Company.owner_id)
        .all()
    )
    company_count_map = {owner_id: total for owner_id, total in company_rows}

    subscription_rows = (
        db.query(Subscription)
        .filter(Subscription.user_id.in_(user_ids))
        .all()
    )
    subscription_map = {s.user_id: s for s in subscription_rows}

    return [
        _serialize_user(
            u,
            companies_count=company_count_map.get(u.id, 0),
            subscription=subscription_map.get(u.id),
        )
        for u in users
    ]


@router.get("/{user_id}", response_model=dict)
def get_user_detail(
    user_id: int,
    db: Session = Depends(get_db),
    acting_admin: User = Depends(admin),
):
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="Usuario no encontrado")

    active_companies = (
        db.query(Company)
        .filter(Company.owner_id == user.id, Company.is_deleted.is_(False))
        .order_by(Company.created_at.desc())
        .all()
    )

    archived_companies = (
        db.query(Company)
        .filter(Company.owner_id == user.id, Company.is_deleted.is_(True))
        .order_by(Company.deleted_at.desc(), Company.created_at.desc())
        .all()
    )

    subscription = (
        db.query(Subscription)
        .filter(Subscription.user_id == user.id)
        .first()
    )

    data = _serialize_user(
        user,
        companies_count=len(active_companies),
        subscription=subscription,
    )
    data["companies"] = [_serialize_company(c) for c in active_companies]
    data["archived_companies"] = [_serialize_company(c) for c in archived_companies]
    return data


@router.get("/{user_id}/companies", response_model=list[dict])
def get_user_companies(
    user_id: int,
    db: Session = Depends(get_db),
    acting_admin: User = Depends(admin),
):
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="Usuario no encontrado")

    companies = (
        db.query(Company)
        .filter(Company.owner_id == user.id)
        .order_by(Company.created_at.desc())
        .all()
    )
    return [_serialize_company(c) for c in companies]


@router.patch("/{user_id}", response_model=dict)
def update_user(
    user_id: int,
    payload: UserUpdateIn,
    db: Session = Depends(get_db),
    acting_admin: User = Depends(admin),
):
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="Usuario no encontrado")

    if payload.email is not None:
        new_email = payload.email.strip().lower()
        _ensure_email_available(db, new_email, exclude_user_id=user.id)
        user.email = new_email

    if payload.full_name is not None:
        user.full_name = _clean_text(payload.full_name)

    if payload.id_number is not None:
        clean_id = _clean_text(payload.id_number)
        _ensure_id_number_available(db, clean_id, exclude_user_id=user.id)
        user.id_number = clean_id

    if payload.phone is not None:
        user.phone = _clean_text(payload.phone)

    if payload.role is not None:
        new_role = _normalize_role(payload.role)
        current_role = _normalize_role(user.role)

        if current_role == "ADMIN" and new_role != "ADMIN" and _count_admins(db) <= 1:
            raise HTTPException(
                status_code=409,
                detail="No puedes quitar el rol al último ADMIN del sistema",
            )

        user.role = new_role

    if payload.is_active is not None:
        current_role = _normalize_role(user.role)
        if current_role == "ADMIN" and user.is_active and payload.is_active is False and _count_active_admins(db) <= 1:
            raise HTTPException(
                status_code=409,
                detail="No puedes desactivar al último ADMIN activo del sistema",
            )

        user.is_active = payload.is_active

    db.commit()
    db.refresh(user)

    companies_count = db.query(Company).filter(Company.owner_id == user.id).count()
    subscription = db.query(Subscription).filter(Subscription.user_id == user.id).first()

    return _serialize_user(user, companies_count=companies_count, subscription=subscription)

def _apply_user_archive_filter(query, archived_mode: str):
    mode = (archived_mode or "active").strip().lower()
    if mode == "archived":
        return query.filter(User.is_deleted.is_(True))
    if mode == "all":
        return query
    return query.filter(User.is_deleted.is_(False))

@router.patch("/{user_id}/password", response_model=dict)
def reset_user_password(
    user_id: int,
    payload: PasswordResetIn,
    db: Session = Depends(get_db),
    acting_admin: User = Depends(admin),
):
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="Usuario no encontrado")

    if _too_long_for_bcrypt(payload.password):
        raise HTTPException(
            status_code=400,
            detail=f"La contraseña supera el límite permitido de {MAX_BCRYPT_BYTES} bytes.",
        )

    user.hashed_password = get_password_hash(payload.password)

    log_admin_action(
        db,
        acting_admin,
        action="USER_PASSWORD_RESET",
        entity_type="USER",
        entity_id=user.id,
        target_user_id=user.id,
        description=f"Restableció la contraseña del usuario {user.email}",
        payload={"email": user.email},
    )
    
    db.commit()
    db.refresh(user)

    return {
        "ok": True,
        "message": "Contraseña actualizada correctamente",
        "user_id": user.id,
        "email": user.email,
    }


@router.delete("/{user_id}", response_model=dict)
def delete_user(
    user_id: int,
    db: Session = Depends(get_db),
    acting_admin: User = Depends(admin),
):
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="Usuario no encontrado")

    if user.id == acting_admin.id:
        raise HTTPException(
            status_code=400,
            detail="No puedes archivar tu propio usuario desde el panel administrativo",
        )

    if user.is_deleted:
        raise HTTPException(status_code=409, detail="El usuario ya está archivado")

    if _normalize_role(user.role) == "ADMIN" and user.is_active and _count_active_admins(db) <= 1:
        raise HTTPException(
            status_code=409,
            detail="No puedes archivar al último ADMIN activo del sistema",
        )

    active_companies = db.query(Company).filter(
        Company.owner_id == user.id,
        Company.is_deleted.is_(False),
    ).count()

    if active_companies > 0:
        raise HTTPException(
            status_code=409,
            detail="No puedes archivar este usuario porque todavía tiene empresas activas. Primero archiva o reasigna esas empresas.",
        )

    user.is_active = False
    user.is_deleted = True
    user.deleted_at = datetime.utcnow()

    log_admin_action(
        db,
        acting_admin,
        action="USER_ARCHIVE",
        entity_type="USER",
        entity_id=user.id,
        target_user_id=user.id,
        description=f"Archivó el usuario {user.email}",
        payload={"email": user.email, "role": user.role},
    )

    db.commit()
    db.refresh(user)

    return {
        "ok": True,
        "archived": True,
        "user_id": user.id,
        "email": user.email,
    }

class CompanyReassignIn(BaseModel):
    new_owner_user_id: int
    
@router.patch("/{user_id}/restore", response_model=dict)
def restore_user(
    user_id: int,
    db: Session = Depends(get_db),
    acting_admin: User = Depends(admin),
):
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="Usuario no encontrado")

    if not user.is_deleted:
        raise HTTPException(status_code=409, detail="El usuario no está archivado")

    user.is_deleted = False
    user.deleted_at = None
    user.is_active = True

    log_admin_action(
        db,
        acting_admin,
        action="USER_RESTORE",
        entity_type="USER",
        entity_id=user.id,
        target_user_id=user.id,
        description=f"Restauró el usuario {user.email}",
        payload={"email": user.email},
    )

    db.commit()
    db.refresh(user)

    return {
        "ok": True,
        "restored": True,
        "user_id": user.id,
        "email": user.email,
    }
    
@router.delete("/{user_id}/hard", status_code=204)
def hard_delete_user(
    user_id: int,
    db: Session = Depends(get_db),
    acting_admin: User = Depends(admin),
):
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="Usuario no encontrado")

    if user.id == acting_admin.id:
        raise HTTPException(
            status_code=400,
            detail="No puedes eliminar definitivamente tu propio usuario desde el panel administrativo",
        )

    if not user.is_deleted:
        raise HTTPException(
            status_code=409,
            detail="Primero debes archivar el usuario antes de eliminarlo definitivamente",
        )

    owned_companies = db.query(Company).filter(Company.owner_id == user.id).count()
    if owned_companies > 0:
        raise HTTPException(
            status_code=409,
            detail="No puedes eliminar definitivamente este usuario porque todavía tiene empresas asociadas, incluso archivadas.",
        )

    if _normalize_role(user.role) == "ADMIN" and _count_admins(db) <= 1:
        raise HTTPException(
            status_code=409,
            detail="No puedes eliminar definitivamente al último ADMIN del sistema",
        )

    log_admin_action(
        db,
        acting_admin,
        action="USER_HARD_DELETE",
        entity_type="USER",
        entity_id=user.id,
        target_user_id=user.id,
        description=f"Eliminó definitivamente el usuario {user.email}",
        payload={"email": user.email, "role": user.role},
    )

    subscriptions = db.query(Subscription).filter(Subscription.user_id == user.id).all()
    for sub in subscriptions:
        db.delete(sub)

    db.delete(user)
    db.commit()
    return

@router.get("/{user_id}/subscription", response_model=dict | None)
def get_user_subscription(
    user_id: int,
    db: Session = Depends(get_db),
    acting_admin: User = Depends(admin),
):
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="Usuario no encontrado")

    sub = db.query(Subscription).filter(Subscription.user_id == user.id).first()
    return _serialize_subscription(sub)

@router.patch("/{user_id}/subscription", response_model=dict)
def update_user_subscription(
    user_id: int,
    payload: SubscriptionAdminUpdateIn,
    db: Session = Depends(get_db),
    acting_admin: User = Depends(admin),
):
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="Usuario no encontrado")

    sub = _get_or_create_subscription_for_admin(db, user.id)

    owned_companies = db.query(Company).filter(Company.owner_id == user.id).count()

    if payload.plan is not None:
        sub.plan = (payload.plan or "").strip().upper()

    if payload.status is not None:
        sub.status = (payload.status or "").strip().upper()

    if payload.companies_quota is not None:
        if payload.companies_quota < owned_companies:
            raise HTTPException(
                status_code=409,
                detail=f"No puedes fijar un cupo menor que las empresas actuales del usuario ({owned_companies}).",
            )
        sub.companies_quota = payload.companies_quota

    if payload.free_trial_until is not None:
        sub.free_trial_until = _parse_optional_datetime(payload.free_trial_until, "free_trial_until")

    if payload.current_period_end is not None:
        sub.current_period_end = _parse_optional_datetime(payload.current_period_end, "current_period_end")

    if payload.last_payment_at is not None:
        sub.last_payment_at = _parse_optional_datetime(payload.last_payment_at, "last_payment_at")

    if payload.provider is not None:
        sub.provider = (payload.provider or "").strip().upper() or "KUSHKI"

    if payload.customer_ref is not None:
        sub.customer_ref = (payload.customer_ref or "").strip() or None

    sub.updated_at = datetime.utcnow()

    log_admin_action(
        db,
        acting_admin,
        action="SUBSCRIPTION_UPDATE",
        entity_type="SUBSCRIPTION",
        entity_id=sub.id,
        target_user_id=user.id,
        description=f"Actualizó la suscripción del usuario {user.email}",
        payload={
            "user_email": user.email,
            "plan": sub.plan,
            "status": sub.status,
            "companies_quota": sub.companies_quota,
            "free_trial_until": sub.free_trial_until.isoformat() if sub.free_trial_until else None,
            "current_period_end": sub.current_period_end.isoformat() if sub.current_period_end else None,
            "last_payment_at": sub.last_payment_at.isoformat() if sub.last_payment_at else None,
            "provider": sub.provider,
            "customer_ref": sub.customer_ref,
        },
    )
    
    db.commit()
    db.refresh(sub)

    return _serialize_subscription(sub)

@router.patch("/{user_id}/companies/{company_id}/reassign", response_model=dict)
def reassign_user_company(
    user_id: int,
    company_id: int,
    payload: CompanyReassignIn,
    db: Session = Depends(get_db),
    acting_admin: User = Depends(admin),
):
    current_user = db.get(User, user_id)
    if not current_user:
        raise HTTPException(status_code=404, detail="Usuario origen no encontrado")

    new_owner = db.get(User, payload.new_owner_user_id)
    if not new_owner:
        raise HTTPException(status_code=404, detail="Usuario destino no encontrado")

    company = db.get(Company, company_id)
    if not company:
        raise HTTPException(status_code=404, detail="Empresa no encontrada")

    if company.owner_id != current_user.id:
        raise HTTPException(
            status_code=409,
            detail="La empresa indicada no pertenece al usuario origen seleccionado",
        )

    company.owner_id = new_owner.id
    
    log_admin_action(
        db,
        acting_admin,
        action="COMPANY_REASSIGN",
        entity_type="COMPANY",
        entity_id=company.id,
        target_user_id=new_owner.id,
        company_id=company.id,
        description=f"Reasignó la empresa {company.name} del usuario {current_user.email} al usuario {new_owner.email}",
        payload={
            "previous_owner_user_id": current_user.id,
            "previous_owner_email": current_user.email,
            "new_owner_user_id": new_owner.id,
            "new_owner_email": new_owner.email,
            "company_name": company.name,
            "company_ruc": company.ruc,
        },
    )
    
    db.commit()
    db.refresh(company)

    return {
        "ok": True,
        "message": "Empresa reasignada correctamente",
        "company_id": company.id,
        "previous_owner_user_id": current_user.id,
        "new_owner_user_id": new_owner.id,
    }

@router.get("/audit/logs", response_model=list[dict])
def list_admin_audit_logs(
    q: str | None = Query(default=None),
    action: str | None = Query(default=None),
    entity_type: str | None = Query(default=None),
    target_user_id: int | None = Query(default=None),
    company_id: int | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    db: Session = Depends(get_db),
    acting_admin: User = Depends(admin),
):
    query = db.query(AdminAuditLog)

    if action:
        query = query.filter(func.upper(AdminAuditLog.action) == action.strip().upper())

    if entity_type:
        query = query.filter(func.upper(AdminAuditLog.entity_type) == entity_type.strip().upper())

    if target_user_id is not None:
        query = query.filter(AdminAuditLog.target_user_id == target_user_id)

    if company_id is not None:
        query = query.filter(AdminAuditLog.company_id == company_id)

    search = (q or "").strip()
    if search:
        like = f"%{search}%"
        query = query.filter(
            or_(
                AdminAuditLog.description.ilike(like),
                func.cast(AdminAuditLog.payload, String).ilike(like),
            )
        )

    rows = query.order_by(AdminAuditLog.created_at.desc()).limit(limit).all()
    return [serialize_admin_audit_log(row) for row in rows]