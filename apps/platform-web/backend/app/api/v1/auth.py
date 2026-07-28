# backend/app/api/v1/auth.py
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from pydantic import BaseModel, EmailStr
from sqlalchemy.orm import Session

from app.api.deps import db, current_user
from app.core.security import get_password_hash, verify_password, create_access_token
from app.models.user import User

from app.services.feature_flags import get_payment_required

MAX_BCRYPT_BYTES = 72

def _too_long_for_bcrypt(password: str) -> bool:
    # bcrypt opera sobre bytes; no caracteres
    return len(password.encode("utf-8")) > MAX_BCRYPT_BYTES

router = APIRouter(prefix="/auth", tags=["auth"])

class RegisterIn(BaseModel):
    email: EmailStr
    password: str

class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"

class UserOut(BaseModel):
    id: int
    email: EmailStr
    roles: list[str] | None = None

# 1) Decorador de register (añade status_code=201)
@router.post("/register", response_model=UserOut, status_code=201)
def register(payload: RegisterIn, session: Session = Depends(db)):
    exists = session.query(User).filter(User.email == payload.email).first()
    if exists:
        raise HTTPException(status_code=400, detail="Email ya registrado")

    # ✅ Bloqueo preventivo para bcrypt
    if _too_long_for_bcrypt(payload.password):
        raise HTTPException(
            status_code=400,
            detail=f"La contraseña supera el límite permitido de {MAX_BCRYPT_BYTES} bytes.",
        )

    required = get_payment_required()
    user = User(
        email=payload.email,
        hashed_password=get_password_hash(payload.password),
        role=("PENDING" if required else "SUBSCRIBER"),
        is_active=True,
    )
    session.add(user)
    session.commit()
    session.refresh(user)
    roles = (user.role.replace(" ", "").split(",") if isinstance(user.role, str) else [])
    return UserOut(id=user.id, email=user.email, roles=roles)

# 2) En login, opcionalmente bloquea usuarios inactivos:
@router.post("/token", response_model=TokenOut)
def login(
    form: OAuth2PasswordRequestForm = Depends(),
    session: Session = Depends(db),
):
    db_user = session.query(User).filter(User.email == form.username).first()

    # ✅ Evitar el ValueError de bcrypt por >72 bytes
    if _too_long_for_bcrypt(form.password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Credenciales inválidas",
        )

    try:
        valid = (db_user is not None) and verify_password(form.password, db_user.hashed_password)
    except Exception:
        # Cualquier excepción en verificación → 401 (evita 500)
        valid = False

    if not valid:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Credenciales inválidas",
        )

    roles = (db_user.role.replace(" ", "").split(",") if isinstance(db_user.role, str) else [])
    token = create_access_token(subject=db_user.email, roles=roles)
    return TokenOut(access_token=token)

@router.get("/me", response_model=UserOut)
def me(user = Depends(current_user)):
    roles = (user.role.replace(" ", "").split(",") if isinstance(user.role, str) else [])
    return UserOut(id=user.id, email=user.email, roles=roles)
