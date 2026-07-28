import os, sys
from datetime import datetime, timedelta

# --- asegurar imports desde backend/app aunque ejecutes desde la raíz ---
HERE = os.path.dirname(os.path.abspath(__file__))              # .../backend/scripts
BACKEND_DIR = os.path.abspath(os.path.join(HERE, ".."))        # .../backend
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)
os.chdir(BACKEND_DIR)  # para que .env se lea igual que cuando corres uvicorn

from app.db.session import SessionLocal
from app.models.user import User
from app.models.subscription import Subscription

def upsert_trial(email: str):
    now = datetime.utcnow()
    s = SessionLocal()
    try:
        u = s.query(User).filter(User.email == email).first()
        if not u:
            raise SystemExit(f"Usuario no encontrado: {email}")

        sub = s.query(Subscription).filter(Subscription.user_id == u.id).first()
        if not sub:
            sub = Subscription(
                user_id=u.id,
                plan="trial",
                status="active",
                free_trial_until=now + timedelta(days=15),
                companies_quota=1,
                provider="internal",
                created_at=now,
                updated_at=now,
            )
            s.add(sub)
        else:
            sub.plan = "trial"
            sub.status = "active"
            sub.free_trial_until = now + timedelta(days=15)
            sub.companies_quota = 1
            sub.provider = "internal"
            sub.updated_at = now

        s.commit()
        print(f"OK: trial activo para {email}")
    finally:
        s.close()

if __name__ == "__main__":
    if len(sys.argv) < 2:
        raise SystemExit("Uso: python backend/scripts/activate_trial.py <email>")
    upsert_trial(sys.argv[1])
