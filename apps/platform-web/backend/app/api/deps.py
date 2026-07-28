from typing import Generator
from fastapi import Depends
from sqlalchemy.orm import Session

from app.db.session import get_db as _get_db
from app.core.security import get_current_user, require_roles
from app.models.user import User

# ✅ Compatibilidad: ambos nombres disponibles
def db() -> Generator[Session, None, None]:
    yield from _get_db()

get_db = db  # ✅ alias para quienes importan get_db

def current_user(user: User = Depends(get_current_user)) -> User:
    return user

def admin(user: User = Depends(require_roles("ADMIN"))) -> User:
    return user

def subscriber(user: User = Depends(require_roles("SUBSCRIBER", "ADMIN"))) -> User:
    return user
