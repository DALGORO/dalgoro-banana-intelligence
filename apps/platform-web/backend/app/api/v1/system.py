from fastapi import APIRouter, Depends
from pydantic import BaseModel
from app.api.deps import admin, current_user
from app.services.feature_flags import load_flags, set_payment_required

router = APIRouter(prefix="/system", tags=["system"])

@router.get("/flags")
def get_flags(user = Depends(current_user)):
    # cualquier autenticado puede leer flags
    return load_flags()

class PaymentToggleIn(BaseModel):
    value: bool

@router.patch("/flags/payment-required", dependencies=[Depends(admin)])
def toggle_payment_required(payload: PaymentToggleIn):
    return set_payment_required(payload.value)
