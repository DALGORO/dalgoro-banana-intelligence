# backend/app/core/security.py
from datetime import datetime, timedelta, timezone
from typing import Iterable, List

from jose import jwt, JWTError
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session
from passlib.context import CryptContext
from app.db.session import get_db  # <- fuente canónica de sesión

from app.core.config import settings
from app.models.user import User

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/token")


# --- Password helpers ---
def get_password_hash(password: str) -> str:
    return pwd_context.hash(password)

def verify_password(plain: str, hashed: str) -> bool:
    return pwd_context.verify(plain, hashed)

# --- JWT helpers ---
def create_access_token(subject: str, roles: Iterable[str] | None = None, expires_minutes: int | None = None, uid: int | None = None) -> str:
    if expires_minutes is None:
        expires_minutes = settings.JWT_EXPIRE_MINUTES
    exp = datetime.now(tz=timezone.utc) + timedelta(minutes=expires_minutes)
    payload = {"sub": subject, "roles": list(roles or []), "exp": exp}
    if uid is not None:
        payload["uid"] = uid
    return jwt.encode(payload, settings.JWT_SECRET, algorithm=settings.JWT_ALGORITHM)

def decode_token(token: str) -> dict:
    try:
        return jwt.decode(token, settings.JWT_SECRET, algorithms=[settings.JWT_ALGORITHM])
    except JWTError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token inválido")

# --- Current user & roles ---
def _normalize_roles(value) -> List[str]:
    # Acepta None | str (p.ej. "SUBSCRIBER,ADMIN")
    if value is None:
        return []
    if isinstance(value, list):
        return [r.upper().replace(" ", "") for r in value]
    if isinstance(value, str):
        return [r.upper() for r in value.replace(" ", "").split(",") if r]
    return []

# --- Current user & roles ---
def get_current_user(token: str = Depends(oauth2_scheme), db: Session = Depends(get_db)) -> User:
    payload = decode_token(token)
    sub = payload.get("sub")
    uid = payload.get("uid")
    if not sub and uid is None:
        raise HTTPException(status_code=401, detail="Token sin sujeto")
    q = db.query(User)
    user = q.filter(User.email == sub).first() if sub else None
    if user is None and uid is not None:
        user = q.filter(User.id == uid).first()
    if not user or not getattr(user, "is_active", True):
        raise HTTPException(status_code=401, detail="Usuario no válido o inactivo")
    return user

def require_roles(*required: str):
    required_set = {r.upper() for r in required}
    def dep(user: User = Depends(get_current_user)):
        # OJO: tu modelo usa 'role' (singular)
        user_roles = _normalize_roles(getattr(user, "role", None))
        if not (set(user_roles) & required_set):
            raise HTTPException(status_code=403, detail="Permisos insuficientes")
        return user
    return dep
