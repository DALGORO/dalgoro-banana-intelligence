from sqlalchemy import select
from app.core.config import settings
from app.db.session import get_db
from app.models.user import User
from app.core.security import verify_password

TARGETS = [
    ("admin@dalgoro.ec", "Admin!SST2025"),
    ("tester4167@dal.goro", "demo1234"),
]

def main():
    print("DATABASE_URL =", settings.DATABASE_URL)
    with next(get_db()) as db:
        for email, plain in TARGETS:
            u = db.scalars(select(User).where(User.email == email)).first()
            if not u:
                print(f"[NO EXISTE] {email}")
                continue
            try:
                ok = verify_password(plain, u.hashed_password)
            except Exception as e:
                print(f"[ERROR VERIFY] {email}: {e}")
                ok = False
            print(f"[EXISTE] {email} | activo={getattr(u,'is_active',None)} | role={getattr(u,'role',None)} | password_ok={ok}")

if __name__ == "__main__":
    main()
