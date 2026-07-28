from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, status, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.deps import db, current_user
from app.core.config import settings
from app.models.user import User
from app.models.subscription import Subscription

router = APIRouter(prefix="/subscriptions", tags=["subscriptions"])

# ------- Schemas -------
class StatusOut(BaseModel):
    plan: str
    status: str
    free_trial_until: datetime | None = None
    current_period_end: datetime | None = None
    companies_quota: int
    days_left: int | None = None

class CheckoutIn(BaseModel):
    item: str = Field(..., pattern="^(BASE_PLAN|EXTRA_COMPANY)$")

class CheckoutOut(BaseModel):
    provider: str
    checkout_url: str
    session_id: str
    expires_at: str

# ------- Helpers -------
def _get_or_bootstrap_sub(session: Session, user: User) -> Subscription:
    sub = session.query(Subscription).filter(Subscription.user_id == user.id).first()
    if sub:
        return sub
    sub = Subscription.new_trial(user_id=user.id)
    session.add(sub)
    session.commit()
    session.refresh(sub)
    return sub

def _resolve_checkout_amount(item: str) -> int:
    if item == "BASE_PLAN":
        return 15
    if item == "EXTRA_COMPANY":
        return 5
    raise HTTPException(status_code=400, detail="Item inválido")


def _build_checkout_stub(payload: CheckoutIn) -> CheckoutOut:
    amount = _resolve_checkout_amount(payload.item)
    return CheckoutOut(
        provider=getattr(settings, "PAYMENT_PROVIDER", "KUSHKI"),
        checkout_url=f"https://sandbox.example/{amount}",
        session_id="stub",
        expires_at=datetime.utcnow().isoformat()
    )


def _assert_webhook_request_allowed(request: Request) -> None:
    """
    Validación mínima y opcional.
    - Si WEBHOOK_SECRET está vacío, mantiene el comportamiento actual (sin bloquear).
    - Si WEBHOOK_SECRET tiene valor, exige header X-Webhook-Secret.
    Más adelante, este helper será el punto único para adaptar la firma real
    del proveedor (Kushki / Stripe / Datafast).
    """
    expected_secret = (getattr(settings, "WEBHOOK_SECRET", "") or "").strip()
    if not expected_secret:
        return

    received_secret = (request.headers.get("X-Webhook-Secret") or "").strip()
    if received_secret != expected_secret:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Webhook no autorizado",
        )


def _parse_webhook_payload(body: dict) -> "WebhookIn":
    """
    Punto único de adaptación futura del payload del proveedor.
    Por ahora mantiene el formato actual del stub.
    """
    return WebhookIn(**body)


def _apply_payment_result(sub: Subscription, data: "WebhookIn") -> None:
    if not data.success:
        sub.status = "PAST_DUE"
        return

    if data.item == "BASE_PLAN":
        sub.plan = "PROFESSIONAL_BASE"
        sub.status = "ACTIVE"
        sub.companies_quota = max(sub.companies_quota or 0, 2)
        sub.free_trial_until = None
        sub.current_period_end = datetime.utcnow()
        sub.last_payment_at = datetime.utcnow()
    elif data.item == "EXTRA_COMPANY":
        sub.companies_quota = (sub.companies_quota or 0) + 1
        sub.last_payment_at = datetime.utcnow()
        
# ------- Endpoints -------
@router.get("/status", response_model=StatusOut)
def subscription_status(session: Session = Depends(db), user: User = Depends(current_user)):
    sub = _get_or_bootstrap_sub(session, user)

    if (
        sub.plan == "FREE_TRIAL"
        and sub.free_trial_until is not None
        and sub.free_trial_until < datetime.utcnow()
        and sub.status == "ACTIVE"
    ):
        sub.status = "PAST_DUE"
        session.commit()
        session.refresh(sub)

    days_left = None
    if sub.plan == "FREE_TRIAL" and sub.free_trial_until:
        delta = sub.free_trial_until.date() - datetime.utcnow().date()
        days_left = max(delta.days, 0)

    return StatusOut(
        plan=sub.plan,
        status=sub.status,
        free_trial_until=sub.free_trial_until,
        current_period_end=sub.current_period_end,
        companies_quota=sub.companies_quota,
        days_left=days_left
    )

# Stub minimal de checkout (puedes mantenerlo por ahora)
@router.post("/checkout-session", response_model=CheckoutOut)
def create_checkout_session(
    payload: CheckoutIn,
    session: Session = Depends(db),
    user: User = Depends(current_user),
):
    # Por ahora seguimos en modo stub.
    # Más adelante, cuando ya exista pasarela real, solo se reemplaza
    # el contenido de _build_checkout_stub() o se deriva desde aquí
    # a un builder real por proveedor.
    return _build_checkout_stub(payload)

class WebhookIn(BaseModel):
    session_id: str
    item: str
    user_email: str
    success: bool = True

@router.post("/webhook")
async def webhook(request: Request, session: Session = Depends(db)):
    _assert_webhook_request_allowed(request)

    body = await request.json()
    data = _parse_webhook_payload(body)

    user = session.query(User).filter(User.email == data.user_email).first()
    if not user:
        raise HTTPException(status_code=404, detail="Usuario no encontrado")

    sub = session.query(Subscription).filter(Subscription.user_id == user.id).first()
    if not sub:
        sub = Subscription.new_trial(user.id)
        session.add(sub)
        session.commit()
        session.refresh(sub)

    _apply_payment_result(sub, data)

    session.commit()
    return {
        "ok": True,
        "plan": sub.plan,
        "companies_quota": sub.companies_quota,
        "status": sub.status,
    }
