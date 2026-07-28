from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.db.session import get_db
from app.models.user import User
from sqlalchemy import select

# ✅ importar solo la dependencia de admin (no cambia tu get_db actual)
from app.api.deps import admin
# (opcional para update por contraseña)
from pydantic import BaseModel, EmailStr
from app.core.security import get_password_hash

router = APIRouter(prefix="/users", tags=["users"])

@router.post("", response_model=dict)
def create_user(email: str, password_hash: str, db: Session = Depends(get_db)):
    if db.scalar(select(User).where(User.email == email)):
        raise HTTPException(status_code=400, detail="Email ya registrado")
    u = User(email=email, hashed_password=password_hash)
    db.add(u); db.commit(); db.refresh(u)
    return {"id": u.id, "email": u.email}

@router.get("", response_model=list[dict])
def list_users(db: Session = Depends(get_db)):
    return [{"id": u.id, "email": u.email, "active": u.is_active} for u in db.scalars(select(User)).all()]

# ✅ NUEVO: borrar cualquier usuario (solo ADMIN)
@router.delete("/{user_id}", status_code=204, dependencies=[Depends(admin)])
def delete_user(user_id: int, db: Session = Depends(get_db)):
    u = db.get(User, user_id)
    if not u:
        raise HTTPException(status_code=404, detail="Usuario no encontrado")
    db.delete(u); db.commit()
    return

# ✅ (OPCIONAL, mínimo) actualizar datos de usuario (solo ADMIN)
class UserUpdate(BaseModel):
    email: EmailStr | None = None
    role: str | None = None
    is_active: bool | None = None
    password: str | None = None  # si llega, se rehashea

@router.patch("/{user_id}", response_model=dict, dependencies=[Depends(admin)])
def update_user(user_id: int, payload: UserUpdate, db: Session = Depends(get_db)):
    u = db.get(User, user_id)
    if not u:
        raise HTTPException(status_code=404, detail="Usuario no encontrado")
    if payload.email is not None:
        u.email = payload.email
    if payload.role is not None:
        u.role = payload.role
    if payload.is_active is not None:
        u.is_active = payload.is_active
    if payload.password:
        u.hashed_password = get_password_hash(payload.password)
    db.commit(); db.refresh(u)
    return {"id": u.id, "email": u.email, "active": u.is_active, "role": u.role}
