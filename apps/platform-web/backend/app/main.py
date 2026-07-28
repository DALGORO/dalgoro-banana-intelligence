from datetime import datetime

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.v1 import get_api_router
from app.core.config import settings
from app.core.security import decode_token
from app.db.session import SessionLocal
from app.models.subscription import Subscription
from app.models.user import User

def _is_billing_exempt_path(path: str, method: str = "GET") -> bool:
    if path == "/":
        return True

    current_method = method.upper()

    readonly_companies_preview = (
        current_method == "GET"
        and path == "/api/v1/companies"
    )

    readonly_documents_preview = (
        current_method == "GET"
        and path.startswith("/api/v1/documents/company/")
    )

    return (
        readonly_companies_preview
        or readonly_documents_preview
        or path.startswith("/docs")
        or path.startswith("/redoc")
        or path.startswith("/openapi.json")
        or path.startswith("/api/v1/health")
        or path.startswith("/api/v1/auth")
        or path.startswith("/api/v1/subscriptions")
    )


def _extract_bearer_token(request: Request) -> str | None:
    auth_header = (request.headers.get("Authorization") or "").strip()
    if not auth_header:
        return None

    scheme, _, token = auth_header.partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        return None

    return token.strip()

def _normalize_plan(value: str | None) -> str:
    raw = (value or "").strip().upper().replace("-", "_").replace(" ", "_")
    if raw in {"TRIAL", "FREE_TRIAL"}:
        return "FREE_TRIAL"
    return raw


def _normalize_status(value: str | None) -> str:
    return (value or "").strip().upper().replace("-", "_").replace(" ", "_")


def _billing_block_response(code: str, detail: str, sub: Subscription) -> JSONResponse:
    return JSONResponse(
        status_code=402,
        content={
            "detail": detail,
            "code": code,
            "plan": sub.plan,
            "status": sub.status,
            "free_trial_until": sub.free_trial_until.isoformat() if sub.free_trial_until else None,
        },
        headers={"X-Billing-Block": code},
    )

app = FastAPI(title="SST Compliance API")

# Monta TODA la API v1; psico viene desde app/api/v1/__init__.py
app.include_router(get_api_router(), prefix="/api/v1")

ALLOWED_ORIGINS = [
    "http://localhost:3000",
    "http://127.0.0.1:3000",
    "http://localhost:5173",
    "http://127.0.0.1:5173",
    "http://127.0.0.1:8000",
    "http://localhost:8000",
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.middleware("http")
async def enforce_subscription_access(request: Request, call_next):
    path = request.url.path

    if request.method == "OPTIONS":
        return await call_next(request)

    if not path.startswith("/api/v1"):
        return await call_next(request)

    if _is_billing_exempt_path(path, request.method):
        return await call_next(request)

    token = _extract_bearer_token(request)
    if not token:
        return await call_next(request)

    db = SessionLocal()
    try:
        try:
            payload = decode_token(token)
        except Exception:
            return await call_next(request)

        subject = payload.get("sub")
        uid = payload.get("uid")

        q = db.query(User)
        user = q.filter(User.email == subject).first() if subject else None
        if user is None and uid is not None:
            user = q.filter(User.id == uid).first()

        if not user or not getattr(user, "is_active", True):
            return await call_next(request)

        if getattr(user, "role", "").upper() == "ADMIN":
            return await call_next(request)

        sub = db.query(Subscription).filter(Subscription.user_id == user.id).first()
        if not sub:
            return await call_next(request)

        now = datetime.utcnow()
        normalized_plan = _normalize_plan(sub.plan)
        normalized_status = _normalize_status(sub.status)

        if (
            normalized_plan == "FREE_TRIAL"
            and sub.free_trial_until is not None
            and sub.free_trial_until < now
        ):
            if normalized_status == "ACTIVE":
                sub.status = "PAST_DUE"
                db.commit()
                normalized_status = "PAST_DUE"

            return _billing_block_response(
                code="TRIAL_EXPIRED",
                detail="Tu periodo de prueba ha expirado. Debes activar un plan para continuar.",
                sub=sub,
            )

        if normalized_plan != "FREE_TRIAL" and normalized_status in {"PAST_DUE", "CANCELED"}:
            return _billing_block_response(
                code="SUBSCRIPTION_INACTIVE",
                detail="Tu suscripción no está activa. Debes regularizar el pago para continuar.",
                sub=sub,
            )

    except Exception:
        return await call_next(request)
    finally:
        db.close()

    return await call_next(request)

@app.get("/")
def root():
    return {"message": "API SST-Compliance funcionando correctamente 🚀"}
